from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
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
RUNTIME_ROOTS = (
    ROOT / "src" / "lesr",
    ROOT / "schemas" / "v1",
)


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
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1:
        raise ValueError(f"expected one {version} wheel, found: {wheels}")
    if len(sdists) != 1:
        raise ValueError(f"expected one {version} sdist, found: {sdists}")
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
        expected_assets = {
            path.relative_to(ROOT / "src").as_posix(): path
            for asset_root in (
                ROOT / "src" / "lesr" / "web",
                ROOT / "src" / "lesr" / "intake",
            )
            for path in asset_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".py", ".pyc"}
        }
        expected_assets["lesr/py.typed"] = ROOT / "src" / "lesr" / "py.typed"
        packaged_assets = {
            name
            for name in names
            if (
                name.startswith(("lesr/web/", "lesr/intake/"))
                and not name.endswith(".py")
            )
            or name == "lesr/py.typed"
        }
        if packaged_assets != set(expected_assets):
            raise ValueError(
                "wheel runtime asset set differs from src: "
                f"missing={sorted(set(expected_assets) - packaged_assets)}, "
                f"unexpected={sorted(packaged_assets - set(expected_assets))}"
            )
        for name, source in expected_assets.items():
            if name not in names:
                raise ValueError(f"wheel is missing runtime asset: {name}")
            if archive.read(name) != source.read_bytes():
                raise ValueError(f"wheel asset differs byte-for-byte from src: {name}")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        if metadata["Version"] != version:
            raise ValueError(
                f"wheel metadata version {metadata['Version']} differs from {version}"
            )
    _verify_sdist(sdists[0], version)
    _installed_smoke(wheel, version)
    print(
        f"Verified {wheel.name} and {sdists[0].name}: exact runtime source/assets, "
        f"metadata, {len(EXPECTED_SCHEMAS)} schemas, and isolated installation."
    )
    return 0


def _verify_sdist(sdist: Path, version: str) -> None:
    prefix = f"lesr-{version}/"
    with tarfile.open(sdist, "r:gz") as archive:
        members = {item.name: item for item in archive.getmembers() if item.isfile()}
        expected: dict[str, Path] = {}
        for root in RUNTIME_ROOTS:
            for path in root.rglob("*"):
                if path.is_file():
                    if "__pycache__" in path.parts or path.suffix == ".pyc":
                        continue
                    expected[prefix + path.relative_to(ROOT).as_posix()] = path
        for name, source in expected.items():
            member = members.get(name)
            if member is None:
                raise ValueError(f"sdist is missing runtime source: {name}")
            extracted = archive.extractfile(member)
            if extracted is None or extracted.read() != source.read_bytes():
                raise ValueError(f"sdist source differs byte-for-byte: {name}")
        forbidden = [
            name
            for name in members
            if "/prototypes/" in name or name.lower().endswith(".pdf")
        ]
        if forbidden:
            raise ValueError(f"sdist contains prototype/licensed material: {forbidden}")


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
                        "from lesr.intake import IntakeCatalog, IntakeRequest, IntakeService; ",
                        f"assert importlib.metadata.version('lesr') == {version!r}; ",
                        "assert lesr.__version__ == importlib.metadata.version('lesr'); ",
                        "catalog = IntakeCatalog(); ",
                        "assert catalog.verify_vendored_sources(); ",
                        "analysis = IntakeService(catalog).analyze(IntakeRequest(",
                        "description='Build an MQTT edge telemetry service with repeatable tests.'",
                        ")); ",
                        "assert analysis.selected_pack.pack_uid == 'event-driven-integration'",
                    )
                ),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        command = environment / ("Scripts/lesr.exe" if sys.platform == "win32" else "bin/lesr")
        subprocess.run(
            [str(command), "--help"],
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
