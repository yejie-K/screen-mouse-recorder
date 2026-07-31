#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.package import (  # noqa: E402
    JourneyPackageError,
    write_json_atomic,
)
from screen_mouse_recorder.journey_analysis.semantic_input_compat import (  # noqa: E402
    migrate_semantic_input_v1,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="将journey_semantic_input从1.0显式迁移到1.1")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    source = args.input.resolve()
    target = (args.output or source).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise JourneyPackageError("语义输入顶层必须是对象")
        migrated = migrate_semantic_input_v1(payload)
        if target.exists() and target != source and not args.overwrite:
            raise JourneyPackageError(f"输出已存在: {target}")
        backup = ""
        if target == source and payload.get("schema_version") == "1.0":
            backup_path = source.with_suffix(f"{source.suffix}.v1.0.bak")
            if backup_path.exists() and not args.overwrite:
                raise JourneyPackageError(f"迁移备份已存在: {backup_path}")
            shutil.copy2(source, backup_path)
            backup = str(backup_path)
        write_json_atomic(target, migrated)
        print(json.dumps({
            "status": "migrated",
            "input_version": str(payload.get("schema_version") or ""),
            "output_version": migrated["schema_version"],
            "output": str(target),
            "backup": backup,
            "events": len(migrated["events"]),
        }, ensure_ascii=False))
        return 0
    except (JourneyPackageError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"JOURNEY-SEMANTIC-MIGRATE-001: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
