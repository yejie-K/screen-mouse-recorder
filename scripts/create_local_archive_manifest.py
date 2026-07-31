"""Inventory local data that is intentionally excluded from Git."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


DEFAULT_ROOTS = ("sessions", "outputs", "experiments", "release_packages")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(repository: Path, output_dir: Path, roots: tuple[str, ...]) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict] = []
    hash_lines: list[str] = []
    errors: list[dict] = []
    processed = 0

    for root_name in roots:
        root = repository / root_name
        count = 0
        total_bytes = 0
        if root.is_dir():
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative = path.relative_to(repository).as_posix()
                try:
                    size = path.stat().st_size
                    checksum = _sha256(path)
                except OSError as exc:
                    errors.append({"path": relative, "error": str(exc)})
                    continue
                count += 1
                total_bytes += size
                processed += 1
                hash_lines.append(f"{checksum}  {relative}")
                if processed % 500 == 0:
                    print(f"hashed {processed} files", flush=True)
        summaries.append({"path": root_name, "file_count": count, "total_bytes": total_bytes})

    manifest = {
        "schema_version": "1.0",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "snapshot_version": "v2.2.0",
        "roots": summaries,
        "hashed_file_count": processed,
        "errors": errors,
    }
    (output_dir / "ARCHIVE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "FILE_HASHES.sha256").write_text(
        "\n".join(hash_lines) + ("\n" if hash_lines else ""),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--roots", nargs="+", default=list(DEFAULT_ROOTS))
    args = parser.parse_args()

    repository = args.repository.resolve()
    output_dir = (args.output_dir or repository / "local_archive").resolve()
    result = build_manifest(repository, output_dir, tuple(args.roots))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
