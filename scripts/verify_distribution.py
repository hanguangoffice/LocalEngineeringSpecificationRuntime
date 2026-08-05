from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import tomllib
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCHEMAS = {
    path.name for path in (ROOT / "schemas" / "v1").glob("*.schema.json")
}


def verify(distribution: Path | None = None) -> int:
    target = (distribution or ROOT / "dist").resolve()
    version = str(
        tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "version"
        ]
    )
    artifacts = sorted(
        path for path in target.iterdir() if path.name.startswith("lesr-")
    )
    allowed_prefix = f"lesr-{version}"
    wrong_versions = [path.name for path in artifacts if not path.name.startswith(allowed_prefix)]
    if wrong_versions:
        raise ValueError(f"distribution contains another LESR version: {wrong_versions}")
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    if len(wheels) != 1:
        raise ValueError(f"expected one {version} wheel, found: {wheels}")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
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
        source_files = {
            path.relative_to(ROOT / "src").as_posix(): path
            for path in (ROOT / "src" / "lesr").rglob("*.py")
        }
        packaged_python = {name for name in names if name.startswith("lesr/") and name.endswith(".py")}
        if packaged_python != set(source_files):
            raise ValueError(
                "wheel Python file set differs from src: "
                f"missing={sorted(set(source_files) - packaged_python)}, "
                f"unexpected={sorted(packaged_python - set(source_files))}"
            )
        for name, source in source_files.items():
            if archive.read(name) != source.read_bytes():
                raise ValueError(f"wheel source differs byte-for-byte from src: {name}")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        if metadata["Version"] != version:
            raise ValueError(
                f"wheel metadata version {metadata['Version']} differs from {version}"
            )
    _installed_smoke(wheel, version)
    print(
        f"Verified installed wheel {wheel.name}: exact source, metadata, "
        f"and {len(EXPECTED_SCHEMAS)} schemas."
    )
    return 0


def _installed_smoke(wheel: Path, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="lesr-wheel-") as directory:
        root = Path(directory)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        executable = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [str(executable), "-m", "pip", "install", str(wheel)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                str(executable),
                "-c",
                "".join(
                    (
                        "import importlib.metadata, lesr; ",
                        f"assert importlib.metadata.version('lesr') == {version!r}; ",
                        "assert lesr.__version__ == importlib.metadata.version('lesr')",
                    )
                ),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution", nargs="?", type=Path)
    arguments = parser.parse_args()
    raise SystemExit(verify(arguments.distribution))
