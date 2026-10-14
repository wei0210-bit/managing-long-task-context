#!/usr/bin/env python3
"""Search original context files through a disposable, project-local SQLite cache."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import managing_long_task_context as context
from managing_long_task_context.project_store import (
    CONTEXT_PATHS, RELATIVE_CONTEXT, resolve_worktree_root,
)

INDEX_PATH = Path(RELATIVE_CONTEXT).parent / 'search' / 'index.sqlite'
TEXT_SUFFIXES = {'.md', '.txt', '.rst', '.json', '.jsonl'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _create_fts(connection):
    connection.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(text, tokenize='trigram')")


def _connect(path):
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA busy_timeout=5000')
    try:
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise sqlite3.DatabaseError('corrupt search index')
    except sqlite3.DatabaseError:
        connection.close()
        raise
    return connection


def _schema(connection):
    connection.execute('CREATE TABLE files(path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, sha256 TEXT)')
    connection.execute('CREATE TABLE chunks(id INTEGER PRIMARY KEY, path TEXT, line INTEGER, text TEXT, '
                       'task TEXT, kind TEXT, history INTEGER, metadata TEXT, file_mtime REAL)')
    connection.execute('CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)')
    try:
        _create_fts(connection)
        mode = 'trigram'
    except sqlite3.OperationalError as exc:
        if not any(word in str(exc).lower() for word in ('tokenizer', 'no such module')):
            raise
        mode = 'like-scan'
    connection.execute('INSERT INTO settings VALUES (?, ?)', ('mode', mode))


def _sources(root, include):
    paths = set()
    ledger = root / RELATIVE_CONTEXT
    if ledger.is_dir():
        for directory in ledger.iterdir():
            if directory.is_dir() and not directory.is_symlink():
                for name in ('snapshot.json', 'events.jsonl', 'task-contract.json'):
                    path = directory / name
                    if path.is_file() and not path.is_symlink():
                        paths.add(path)
    for name in (CONTEXT_PATHS[0], 'CONTEXT.md'):
        path = root / name
        if path.is_file() and not path.is_symlink():
            paths.add(path)
    for directory in [root / 'docs', root / 'references', *[Path(p) if Path(p).is_absolute() else root / p for p in include]]:
        if not directory.is_dir():
            continue
        for path in directory.rglob('*'):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and not path.is_symlink():
                # Explicit broad includes must not bypass ledger semantics or index the index.
                resolved = path.resolve()
                if resolved == (root / INDEX_PATH).resolve() or (root / INDEX_PATH).parent.resolve() in resolved.parents:
                    continue
                if ledger.resolve() in resolved.parents and path.name not in ('snapshot.json', 'events.jsonl', 'task-contract.json'):
                    continue
                if any(parent.is_symlink() for parent in path.parents if parent != root):
                    continue
                paths.add(path)
    return sorted(paths)


def _label(root, path):
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _paragraphs(text):
    start, lines = None, []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or re.match(r'^#{1,6}\s', line):
            if lines:
                yield start, '\n'.join(lines)
                start, lines = None, []
            if line.strip():
                yield number, line
        else:
            if start is None:
                start = number
            lines.append(line)
    if lines:
        yield start, '\n'.join(lines)


def _item_locations(text):
    """Decode each item boundary, retaining the original JSON object's source line."""
    match = re.search(r'"items"\s*:\s*\{', text)
    if not match:
        return {}
    decoder, offset, locations = json.JSONDecoder(), match.end(), {}
    while offset < len(text):
        while offset < len(text) and text[offset] in ' \r\n\t,':
            offset += 1
        if offset >= len(text) or text[offset] == '}':
            break
        identifier, end = decoder.raw_decode(text, offset)
        locations[identifier] = text.count('\n', 0, offset) + 1
        offset = end
        while text[offset] in ' \r\n\t:':
            offset += 1
        _, offset = decoder.raw_decode(text, offset)
    return locations


def _ledger_view(path):
    task = path.parent.name
    paths = context._paths(task, base_dir=path.parent.parent)
    return context._load_snapshot(task, paths)


def _blocks(root, path, text):
    ledger = (root / RELATIVE_CONTEXT).resolve() in path.resolve().parents
    task = path.parent.name if ledger else None
    if ledger and path.name == 'snapshot.json':
        snapshot = _ledger_view(path)
        locations = _item_locations(text)
        for identifier, item in snapshot.get('items', {}).items():
            if item.get('status') == 'superseded':
                continue
            if identifier not in locations:
                # Rebuild-marker snapshots have no item text: point to the original event.
                continue
            yield locations[identifier], json.dumps(item, ensure_ascii=False), task, _kind(item), False, item
    elif ledger and path.name == 'events.jsonl':
        snapshot = _ledger_view(path)
        current = snapshot.get('items', {})
        events = iter(context._read_events(path))
        for line, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            event = next(events)
            item = event.get('payload', {}).get('item', {})
            metadata = dict(item)
            latest = current.get(item.get('id'), {})
            if latest.get('status') == 'superseded' or (item and item != latest):
                metadata.update(status='superseded', superseded_by=latest.get('superseded_by'))
            yield line, raw, task, _kind(item) if item else 'contract' if event.get('event_type') == 'contract-published' else 'fact', True, metadata
    else:
        blocks = ((i, line) for i, line in enumerate(text.splitlines(), 1) if line.strip()) if path.suffix == '.jsonl' else _paragraphs(text)
        for line, block in blocks:
            yield line, block, task, 'contract' if ledger else 'doc', False, {}


def _kind(item):
    return 'decision' if item.get('type') == 'decision' else 'fact'


def _refresh(connection, root, sources, force=False):
    """One atomic refresh; readers retain the previous complete cache on lock conflict."""
    try:
        connection.execute('BEGIN IMMEDIATE')
        initialized = connection.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone()
        if not initialized:
            _schema(connection)
        old = {row['path']: row for row in connection.execute('SELECT * FROM files')}
        labels = {_label(root, p): p for p in sources}
        changed = set(old) - set(labels)
        contents = {}
        stats = {}
        for label, path in labels.items():
            stat = path.stat()
            stats[label] = stat
            previous = old.get(label)
            if force or previous is None or (stat.st_size, stat.st_mtime_ns) != (previous['size'], previous['mtime']):
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                contents[label] = data.decode('utf-8')
                if force or previous is None or digest != previous['sha256']:
                    changed.add(label)
                connection.execute('INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)', (label, stat.st_size, stat.st_mtime_ns, digest))
                connection.execute('UPDATE chunks SET file_mtime=? WHERE path=?', (stat.st_mtime, label))
        # Historical item labels depend on the current snapshot, and rebuilds depend on events.
        for label in list(changed):
            path = labels.get(label)
            if path and (root / RELATIVE_CONTEXT).resolve() in path.resolve().parents:
                changed.update(_label(root, p) for p in sources if p.parent == path.parent and p.name in ('snapshot.json', 'events.jsonl'))
        mode = connection.execute("SELECT value FROM settings WHERE key='mode'").fetchone()[0]
        for label in sorted(changed):
            if mode == 'trigram':
                connection.execute('DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE path=?)', (label,))
            connection.execute('DELETE FROM chunks WHERE path=?', (label,))
            if label not in labels:
                connection.execute('DELETE FROM files WHERE path=?', (label,))
                continue
            path = labels[label]
            content = contents.get(label)
            if content is None:
                content = path.read_text(encoding='utf-8')
            for line, block, task, kind, history, metadata in _blocks(root, path, content):
                cursor = connection.execute('INSERT INTO chunks(path,line,text,task,kind,history,metadata,file_mtime) VALUES (?,?,?,?,?,?,?,?)',
                    (label, line, block, task, kind, int(history), json.dumps(metadata, ensure_ascii=False), stats[label].st_mtime))
                if mode == 'trigram':
                    connection.execute('INSERT INTO chunks_fts(rowid,text) VALUES (?,?)', (cursor.lastrowid, block))
        if changed or not initialized:
            connection.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('built_at', _now()))
        connection.commit()
        return False
    except sqlite3.OperationalError as exc:
        connection.rollback()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower():
            return True
        raise
    except Exception:
        connection.rollback()
        raise


def _open_index(root):
    path = root / INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _connect(path)
    except sqlite3.DatabaseError as exc:
        if not any(word in str(exc).lower() for word in ('malformed', 'not a database', 'corrupt')):
            raise
        # Only disposable index bytes are removed; source files are never changed.
        path.unlink(missing_ok=True)
        return _connect(path)


def search(root, words, *, task=None, kind=None, include=(), limit=20, history=False):
    root = Path(root).resolve()
    if not words or any(not word for word in words) or limit < 1:
        raise ValueError('search needs non-empty words and a positive limit')
    sources = _sources(root, include)
    connection = _open_index(root)
    try:
        stale = _refresh(connection, root, sources)
        settings = dict(connection.execute('SELECT key,value FROM settings'))
        mode, built_at = settings['mode'], settings.get('built_at')
        long_words = [word for word in words if len(word) >= 3]
        where, parameters = [], []
        fts = mode == 'trigram' and bool(long_words)
        if fts:
            where.append('chunks_fts MATCH ?')
            parameters.append(' AND '.join('"' + word.replace('"', '""') + '"' for word in long_words))
        for word in words:
            if not fts:
                where.append("lower(c.text) LIKE lower(?) ESCAPE '\\'")
                parameters.append('%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
            elif len(word) < 3:
                where.append('instr(lower(c.text),lower(?)) > 0')
                parameters.append(word)
        if not history:
            where.append('c.history=0')
        if task is not None:
            where.append('c.task=?')
            parameters.append(task)
        if kind is not None:
            where.append('c.kind=?')
            parameters.append(kind)
        # A previous explicit include must never leak into a later query during lock fallback.
        labels = [_label(root, p) for p in sources]
        where.append('c.path IN (' + ','.join('?' for _ in labels) + ')' if labels else '0')
        parameters.extend(labels)
        score = 'bm25(chunks_fts)' if fts else '0.0'
        join = ' JOIN chunks_fts ON chunks_fts.rowid=c.id' if fts else ''
        rows = connection.execute('SELECT c.*, ' + score + ' AS score FROM chunks c' + join + ' WHERE ' + ' AND '.join(where) + ' ORDER BY score,c.path,c.line,c.id LIMIT ?', [*parameters, limit])
        results = []
        for row in rows:
            item = json.loads(row['metadata'])
            text = row['text']
            positions = [text.casefold().find(word.casefold()) for word in words]
            offset = max(0, min((p for p in positions if p >= 0), default=0) - 80)
            result = {'path': row['path'], 'line': row['line'], 'snippet': text[offset:offset + 480],
                      'score': row['score'], 'index_built_at': built_at, 'index_stale': stale,
                      'degraded': 'like-scan' if mode != 'trigram' else None}
            if item.get('type') == 'verified-fact':
                result['verified_at'] = item.get('verified_at')
            else:
                result['file_mtime'] = row['file_mtime']
            if row['task'] is not None:
                result.update(item_id=item.get('id'), status=item.get('status'), superseded_by=item.get('superseded_by'),
                              stale=context._item_is_stale(item), history=bool(row['history']))
            results.append(result)
        return {'results': results, 'index_built_at': built_at, 'index_stale': stale,
                'degraded': 'like-scan' if mode != 'trigram' else None}
    finally:
        connection.close()


def rebuild(root, *, include=()):
    root = Path(root).resolve()
    connection = _open_index(root)
    try:
        stale = _refresh(connection, root, _sources(root, include), force=True)
        return {'index_stale': stale, 'index_path': str(root / INDEX_PATH),
                'files': connection.execute('SELECT count(*) FROM files').fetchone()[0],
                'chunks': connection.execute('SELECT count(*) FROM chunks').fetchone()[0]}
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    query = commands.add_parser('search')
    query.add_argument('words', nargs='+')
    query.add_argument('--task')
    query.add_argument('--kind', choices=('fact', 'decision', 'contract', 'doc'))
    query.add_argument('--limit', type=int, default=20)
    query.add_argument('--history', action='store_true')
    for subparser in (query, commands.add_parser('rebuild')):
        subparser.add_argument('--include', nargs='+', action='extend', default=[])
    args = parser.parse_args(argv)
    try:
        root = resolve_worktree_root()
        if args.command == 'search':
            result = search(root, args.words, task=args.task, kind=args.kind, limit=args.limit, include=args.include, history=args.history)
        else:
            result = rebuild(root, include=args.include)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error, context.ContextError) as exc:
        print(json.dumps({'error': str(exc), 'index_stale': True}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
