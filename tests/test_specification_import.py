import json
from pathlib import Path
from shutil import copyfile

import pytest
from typer.testing import CliRunner

from lesr.cli.main import app
from lesr.errors import LESRError
from lesr.importing.service import ImportService
from lesr.storage.yaml_repository import YamlRepository

FIXTURE = Path("tests/fixtures/specifications/demo-standard.md")


def copy_fixture(project: Path) -> Path:
    source = project / "specifications" / "demo-standard.md"
    source.parent.mkdir(parents=True)
    copyfile(FIXTURE, source)
    return source


def test_markdown_preview_extracts_candidates_with_provenance(tmp_path: Path) -> None:
    source = copy_fixture(tmp_path)

    result = ImportService(tmp_path).preview(
        source.relative_to(tmp_path),
        artifact_type="coding_rule",
        version="1.0",
    )

    assert result.source.source_path == "specifications/demo-standard.md"
    assert result.source.media_type == "text/markdown"
    assert result.source.version == "1.0"
    assert result.source.content_hash.startswith("sha256:")
    assert [item.suggested_artifact_id for item in result.candidates] == [
        "RULE-COM-001",
        "RULE-COM-002",
    ]
    assert [item.title for item in result.candidates] == ["MQTT 断线重连", "重连退避"]
    assert all(item.artifact_type == "coding_rule" for item in result.candidates)
    assert all(item.attributes["normative_level"] == "required" for item in result.candidates)
    assert result.candidates[0].source_location.line_start == 5
    assert result.candidates[0].source_location.line_end == 7
    assert result.candidates[0].review_status == "candidate"
    assert result.warnings == []


def test_preview_is_stable_across_line_ending_styles(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    text = FIXTURE.read_text(encoding="utf-8")
    source = project / "standard.md"
    source.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))

    service = ImportService(project)
    left_result = service.preview(Path("standard.md"))
    source.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    right_result = service.preview(Path("standard.md"))

    assert left_result.source.content_hash == right_result.source.content_hash
    assert [item.candidate_id for item in left_result.candidates] == [
        item.candidate_id for item in right_result.candidates
    ]


def test_missing_id_and_empty_section_produce_warnings(tmp_path: Path) -> None:
    source = tmp_path / "standard.md"
    source.write_text(
        "# Demo\n\n"
        "## Reconnect behavior\n\n"
        "The client should reconnect.\n\n"
        "## RULE-COM-EMPTY Empty rule\n",
        encoding="utf-8",
    )

    result = ImportService(tmp_path).preview(Path("standard.md"))

    assert len(result.candidates) == 1
    assert result.candidates[0].suggested_artifact_id is None
    assert result.candidates[0].attributes["normative_level"] == "advisory"
    assert {warning.code for warning in result.warnings} == {
        "LESR-IMPORT-ID-MISSING",
        "LESR-IMPORT-EMPTY-SECTION",
    }


def test_preview_has_no_formal_repository_side_effects(tmp_path: Path) -> None:
    source = copy_fixture(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    ImportService(tmp_path).preview(source.relative_to(tmp_path))

    after = {
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (tmp_path / "artifacts").exists()
    assert not (tmp_path / "audit").exists()
    assert not (tmp_path / ".lesr").exists()


def test_source_must_stay_inside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.md").write_text("## RULE-OUT-001 Outside\n\nNo.\n", encoding="utf-8")

    with pytest.raises(LESRError) as error:
        ImportService(project).preview(Path("../outside.md"))

    assert error.value.code == "LESR-IMPORT-PATH-INVALID"


def test_unsupported_format_has_stable_error(tmp_path: Path) -> None:
    (tmp_path / "standard.txt").write_text("plain text", encoding="utf-8")

    with pytest.raises(LESRError) as error:
        ImportService(tmp_path).preview(Path("standard.txt"))

    assert error.value.code == "LESR-IMPORT-FORMAT-UNSUPPORTED"


def test_invalid_utf8_has_stable_error(tmp_path: Path) -> None:
    (tmp_path / "standard.md").write_bytes(b"\xff\xfe\x00")

    with pytest.raises(LESRError) as error:
        ImportService(tmp_path).preview(Path("standard.md"))

    assert error.value.code == "LESR-IMPORT-ENCODING-INVALID"


def test_import_preview_cli_outputs_json_without_writing(tmp_path: Path) -> None:
    copy_fixture(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "import-preview",
            str(tmp_path),
            "specifications/demo-standard.md",
            "--artifact-type",
            "coding_rule",
            "--version",
            "1.0",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["source"]["version"] == "1.0"
    assert len(payload["candidates"]) == 2
    assert not (tmp_path / "artifacts").exists()


def test_accept_creates_draft_with_provenance_snapshot_and_audit(tmp_path: Path) -> None:
    YamlRepository(tmp_path).initialize("demo")
    source = copy_fixture(tmp_path)
    service = ImportService(tmp_path)
    preview = service.preview(
        source.relative_to(tmp_path),
        artifact_type="coding_rule",
        version="1.0",
    )
    candidate = preview.candidates[0]

    saved = service.accept(
        source.relative_to(tmp_path),
        candidate.candidate_id,
        expected_source_hash=preview.source.content_hash,
        actor="reviewer",
        artifact_type="coding_rule",
        version="1.0",
    )

    assert saved.id == "RULE-COM-001"
    assert saved.status == "draft"
    assert saved.source_path == "artifacts/RULE-COM-001.yaml"
    assert saved.attributes["normative_level"] == "required"
    provenance = saved.attributes["provenance"]
    assert provenance["source_path"] == "specifications/demo-standard.md"
    assert provenance["source_content_hash"] == preview.source.content_hash
    assert provenance["source_version"] == "1.0"
    assert provenance["line_start"] == 5
    assert provenance["line_end"] == 7
    assert provenance["import_candidate_id"] == candidate.candidate_id
    assert (tmp_path / "artifacts/RULE-COM-001.yaml").is_file()
    assert (tmp_path / ".lesr/versions/RULE-COM-001/v0001.json").is_file()
    audit = (tmp_path / "audit/events.jsonl").read_text(encoding="utf-8")
    assert '"actor":"reviewer"' in audit
    assert '"operation":"artifact.create"' in audit


def test_accept_rejects_changed_source_before_formal_write(tmp_path: Path) -> None:
    YamlRepository(tmp_path).initialize("demo")
    source = copy_fixture(tmp_path)
    service = ImportService(tmp_path)
    preview = service.preview(source.relative_to(tmp_path), artifact_type="coding_rule")
    candidate = preview.candidates[0]
    source.write_text(
        source.read_text(encoding="utf-8") + "\nChanged after review.\n",
        encoding="utf-8",
    )

    with pytest.raises(LESRError) as error:
        service.accept(
            source.relative_to(tmp_path),
            candidate.candidate_id,
            expected_source_hash=preview.source.content_hash,
            actor="reviewer",
            artifact_type="coding_rule",
        )

    assert error.value.code == "LESR-IMPORT-SOURCE-CHANGED"
    assert list((tmp_path / "artifacts").glob("*.yaml")) == []


def test_accept_rejects_unknown_candidate_before_formal_write(tmp_path: Path) -> None:
    YamlRepository(tmp_path).initialize("demo")
    source = copy_fixture(tmp_path)
    service = ImportService(tmp_path)
    preview = service.preview(source.relative_to(tmp_path))

    with pytest.raises(LESRError) as error:
        service.accept(
            source.relative_to(tmp_path),
            "CAND-DOES-NOT-EXIST",
            expected_source_hash=preview.source.content_hash,
            actor="reviewer",
        )

    assert error.value.code == "LESR-IMPORT-CANDIDATE-NOT-FOUND"
    assert list((tmp_path / "artifacts").glob("*.yaml")) == []


def test_accept_rejects_candidate_without_stable_id(tmp_path: Path) -> None:
    YamlRepository(tmp_path).initialize("demo")
    source = tmp_path / "specifications" / "standard.md"
    source.parent.mkdir()
    source.write_text(
        "# Demo\n\n## Reconnect behavior\n\nThe client shall reconnect.\n",
        encoding="utf-8",
    )
    service = ImportService(tmp_path)
    preview = service.preview(Path("specifications/standard.md"))
    candidate = preview.candidates[0]

    with pytest.raises(LESRError) as error:
        service.accept(
            Path("specifications/standard.md"),
            candidate.candidate_id,
            expected_source_hash=preview.source.content_hash,
            actor="reviewer",
        )

    assert error.value.code == "LESR-IMPORT-STABLE-ID-REQUIRED"
    assert list((tmp_path / "artifacts").glob("*.yaml")) == []


@pytest.mark.parametrize(
    ("accepted_type", "accepted_version"),
    [
        ("software_requirement", "1.0"),
        ("coding_rule", "2.0"),
    ],
)
def test_candidate_id_binds_type_and_source_version(
    tmp_path: Path,
    accepted_type: str,
    accepted_version: str,
) -> None:
    YamlRepository(tmp_path).initialize("demo")
    source = copy_fixture(tmp_path)
    service = ImportService(tmp_path)
    preview = service.preview(
        source.relative_to(tmp_path),
        artifact_type="coding_rule",
        version="1.0",
    )

    with pytest.raises(LESRError) as error:
        service.accept(
            source.relative_to(tmp_path),
            preview.candidates[0].candidate_id,
            expected_source_hash=preview.source.content_hash,
            actor="reviewer",
            artifact_type=accepted_type,
            version=accepted_version,
        )

    assert error.value.code == "LESR-IMPORT-CANDIDATE-NOT-FOUND"
    assert list((tmp_path / "artifacts").glob("*.yaml")) == []


def test_accept_requires_human_actor_before_formal_write(tmp_path: Path) -> None:
    YamlRepository(tmp_path).initialize("demo")
    source = copy_fixture(tmp_path)
    service = ImportService(tmp_path)
    preview = service.preview(source.relative_to(tmp_path))

    with pytest.raises(LESRError) as error:
        service.accept(
            source.relative_to(tmp_path),
            preview.candidates[0].candidate_id,
            expected_source_hash=preview.source.content_hash,
            actor=" ",
        )

    assert error.value.code == "LESR-HUMAN-CONFIRMATION-REQUIRED"
    assert list((tmp_path / "artifacts").glob("*.yaml")) == []


def test_accept_rejects_duplicate_artifact_id_without_overwrite(tmp_path: Path) -> None:
    YamlRepository(tmp_path).initialize("demo")
    source = copy_fixture(tmp_path)
    service = ImportService(tmp_path)
    preview = service.preview(source.relative_to(tmp_path), artifact_type="coding_rule")
    candidate = preview.candidates[0]
    service.accept(
        source.relative_to(tmp_path),
        candidate.candidate_id,
        expected_source_hash=preview.source.content_hash,
        actor="reviewer",
        artifact_type="coding_rule",
    )

    with pytest.raises(LESRError) as error:
        service.accept(
            source.relative_to(tmp_path),
            candidate.candidate_id,
            expected_source_hash=preview.source.content_hash,
            actor="reviewer",
            artifact_type="coding_rule",
        )

    assert error.value.code == "LESR-DUPLICATE-ID"
    assert len(list((tmp_path / "artifacts").glob("*.yaml"))) == 1


def test_import_accept_cli_creates_draft_artifact(tmp_path: Path) -> None:
    YamlRepository(tmp_path).initialize("demo")
    source = copy_fixture(tmp_path)
    preview = ImportService(tmp_path).preview(
        source.relative_to(tmp_path),
        artifact_type="coding_rule",
        version="1.0",
    )

    result = CliRunner().invoke(
        app,
        [
            "import-accept",
            str(tmp_path),
            "specifications/demo-standard.md",
            preview.candidates[0].candidate_id,
            "--expected-source-hash",
            preview.source.content_hash,
            "--actor",
            "reviewer",
            "--artifact-type",
            "coding_rule",
            "--version",
            "1.0",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["id"] == "RULE-COM-001"
    assert payload["status"] == "draft"
    assert payload["attributes"]["provenance"]["import_candidate_id"] == (
        preview.candidates[0].candidate_id
    )
