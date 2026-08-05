"""Verify that the accepted LESR design baseline is byte-for-byte intact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "LESR_Solution_Design_Baseline_v1.0"


def main() -> None:
    manifest_path = BASELINE / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    files = manifest.get("files", [])
    for entry in files:
        relative = Path(entry["path"])
        path = BASELINE / relative
        if not path.is_file():
            failures.append(f"missing: {relative.as_posix()}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            failures.append(f"hash mismatch: {relative.as_posix()}")
        if path.stat().st_size != entry["bytes"]:
            failures.append(f"size mismatch: {relative.as_posix()}")
    if len(files) != manifest.get("file_count_excluding_manifest"):
        failures.append("manifest file count does not match the entries")
    if failures:
        raise SystemExit("Baseline integrity failed:\n" + "\n".join(failures))
    print(f"Verified {len(files)} baseline files ({manifest['version']}).")


if __name__ == "__main__":
    main()
