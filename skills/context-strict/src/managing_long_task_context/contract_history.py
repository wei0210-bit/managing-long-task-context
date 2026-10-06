"""Retain superseded contract bytes and compare contract versions (stdlib only)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _verify_existing(path: Path, data: bytes) -> None:
    from . import ContextError

    if path.is_symlink() or path.read_bytes() != data:
        raise ContextError(f"contract history collision or corruption: {path}")


def retain_contract(contract_path: Path) -> Path | None:
    """Archive existing bytes before replacement; never overwrite a history file.

    The caller supplies serialization: publish_contract holds its task lock, while
    the compatibility migrate_contract entry does not protect this step with a lock.
    """
    from . import ContextError

    temporary: Path | None = None
    try:
        if not contract_path.exists():
            return None
        data = contract_path.read_bytes()
        history = contract_path.parent / 'contract-history'
        if history.is_symlink():
            raise ContextError(f"contract history directory is a symlink: {history}")
        history.mkdir(exist_ok=True)
        destination = history / (hashlib.sha256(data).hexdigest() + '.json')
        if destination.exists() or destination.is_symlink():
            _verify_existing(destination, data)
            return destination
        # Write completely and make read-only before publishing the name. Hard
        # linking fails on an existing destination, unlike an overwriting rename.
        descriptor, name = tempfile.mkstemp(prefix='.contract-', dir=history)
        temporary = Path(name)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o444)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            _verify_existing(destination, data)
        return destination
    except OSError as exc:
        raise ContextError(f"contract history retention failed: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_contract(path: Path, *, history: bool = False) -> dict[str, Any]:
    from . import ContextError

    try:
        data = path.read_bytes()
        if history and (path.is_symlink() or path.name != hashlib.sha256(data).hexdigest() + '.json'):
            raise ContextError(f"contract history digest mismatch: {path}")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ContextError(f"contract history is not an object: {path}")
        return value
    except (OSError, ValueError) as exc:
        raise ContextError(f"cannot read contract version: {path}: {exc}") from exc


def contract_diff(
    task_id: str, from_version: int, to_version: int, *, base_dir: str | Path,
) -> dict[str, Any]:
    """Return top-level changes from retained/current versions, without writing.

    Each changed field has ``from`` and/or ``to`` values; an absent key indicates
    an absent field (distinct from JSON null). Missing versions are reported,
    never reconstructed. History digests are checked regardless of file mode,
    since Git does not preserve read-only permissions across checkouts.
    """
    from . import ContextError, _paths

    paths = _paths(task_id, base_dir)
    history = paths['root'] / 'contract-history'
    if history.is_symlink():
        raise ContextError(f"contract history directory is a symlink: {history}")
    versions: dict[int, dict[str, Any]] = {}
    candidates = [(path, True) for path in sorted(history.glob('*.json'))]
    if paths['contract'].exists():
        candidates.append((paths['contract'], False))
    for path, archived in candidates:
        value = _read_contract(path, history=archived)
        version = value.get('version')
        if type(version) is int and version >= 0:
            versions[version] = value
    for version in (from_version, to_version):
        if type(version) is not int or version < 0 or version not in versions:
            return {'status': 'missing', 'version': version}
    before, after = versions[from_version], versions[to_version]
    changes = {}
    for field in sorted(before.keys() | after.keys()):
        if field in before and field in after and before[field] == after[field]:
            continue
        changes[field] = {}
        if field in before:
            changes[field]['from'] = before[field]
        if field in after:
            changes[field]['to'] = after[field]
    return {'status': 'ok', 'from_version': from_version, 'to_version': to_version, 'changes': changes}
