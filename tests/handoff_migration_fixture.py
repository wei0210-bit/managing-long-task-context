"""Real-old-package child used only by the E1-04 local migration analogy.

It deliberately imports the pinned 0.7.0 package through an isolated Python
process.  The parent supplies ``PYTHONPATH``; this file never alters it and
never installs anything.  JSON lines are progress hints, while the parent test
uses the child PID and ``wait`` result as the authoritative process evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


def _emit(**value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def _manifest_for(module_file: str) -> Path:
    location = Path(module_file).resolve()
    for parent in (location.parent, *location.parents):
        candidate = parent / "skill-manifest.json"
        if candidate.is_file():
            return candidate
    raise RuntimeError("old package manifest is unavailable")


def legacy_writer(config_path: str) -> int:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("fixture config must be an object")

    import managing_long_task_context as legacy

    manifest = _manifest_for(str(legacy.__file__))
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    _emit(
        stage="legacy_loaded", pid=__import__("os").getpid(),
        module_file=str(Path(legacy.__file__).resolve()),
        manifest=str(manifest), manifest_sha256=manifest_sha256,
    )
    gate = config.get("gate_path")
    if isinstance(gate, str):
        with Path(gate).open("rb", buffering=0) as stream:
            if stream.read(1) != b"G":
                raise RuntimeError("fixture gate was not released")
    try:
        item = legacy.record(
            str(config["task_id"]), statement="legacy process actual write",
            item_type="observation", actor="legacy:0.7.0",
            source="isolated-real-old-package", base_dir=Path(str(config["base_dir"])),
        )
    except Exception as exc:  # the test reports the actual old-package outcome
        _emit(stage="legacy_result", status="error", error_type=type(exc).__name__, message=str(exc))
        return 3
    _emit(stage="legacy_result", status="pass", item_id=item.get("id"))
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2 or arguments[0] != "legacy_writer":
        raise SystemExit("usage: handoff_migration_fixture.py legacy_writer CONFIG.json")
    return legacy_writer(arguments[1])


if __name__ == "__main__":
    raise SystemExit(main())
