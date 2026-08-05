from __future__ import annotations

import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
EXPECTED_SCHEMAS = {
    path.name for path in (ROOT / "schemas" / "v1").glob("*.schema.json")
}


def verify() -> int:
    wheels = sorted(DIST.glob("lesr-0.5.0a1-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"expected one 0.5.0a1 wheel, found: {wheels}")
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        packaged_schemas = {
            Path(name).name
            for name in names
            if re.fullmatch(r"lesr/schemas/v1/.+\.schema\.json", name)
        }
        if packaged_schemas != EXPECTED_SCHEMAS:
            raise ValueError(
                "wheel schema mismatch: "
                f"missing={sorted(EXPECTED_SCHEMAS - packaged_schemas)}, "
                f"unexpected={sorted(packaged_schemas - EXPECTED_SCHEMAS)}"
            )
        forbidden = [
            name
            for name in names
            if name.startswith(("测试文档/", "tests/", "prototypes/"))
            or name.lower().endswith(".pdf")
        ]
        if forbidden:
            raise ValueError(f"wheel contains non-runtime or licensed material: {forbidden}")
    print(f"Verified wheel {wheels[0].name} with {len(EXPECTED_SCHEMAS)} schemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(verify())
