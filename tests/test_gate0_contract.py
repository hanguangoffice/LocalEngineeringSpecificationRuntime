from __future__ import annotations

import json
from pathlib import Path

import pytest

from lesr.adapters.git import GitCanonicalRepository, IntegrityError
from lesr.domain.catalog import CAPABILITIES, SCHEMA_CATALOG, RepositoryManifest


def test_manifest_is_complete_deterministic_and_self_hashed() -> None:
    first = RepositoryManifest()
    second = RepositoryManifest.model_validate(first.model_dump(mode="json"))
    assert first == second
    assert first.schema_catalog == SCHEMA_CATALOG
    assert first.manifest_hash.startswith("sha256:")
    assert [item.name for item in first.capabilities] == sorted(item.name for item in CAPABILITIES)


def test_repository_initialization_installs_and_requires_manifest(tmp_path: Path) -> None:
    repository = GitCanonicalRepository(tmp_path / "v1")
    commit = repository.initialize()
    manifest = repository.read_json(commit, ".repository-manifest.json")
    assert manifest is not None
    assert repository.require_v1_manifest(commit)["canonical_format_version"] == "1.0.0"


def test_pre_1_0_repository_is_rejected(tmp_path: Path) -> None:
    repository = GitCanonicalRepository(tmp_path / "legacy")
    repository.path.mkdir(parents=True)
    repository._git("init", "--quiet")
    tree = repository._git("mktree", input_text="")
    commit = repository._commit_tree(tree, (), "legacy empty state")
    repository._git("update-ref", repository.CANONICAL_REF, commit)
    with pytest.raises(IntegrityError, match="LESR-MANIFEST-MISSING"):
        repository.initialize()


def test_manifest_schema_catalog_matches_files() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas" / "v1"
    assert tuple(sorted(path.name for path in root.glob("*.schema.json"))) == SCHEMA_CATALOG
    for path in root.glob("*.schema.json"):
        json.loads(path.read_text(encoding="utf-8"))
