import json
from pathlib import Path
from shutil import copyfile

import pytest
from typer.testing import CliRunner

from lesr.cli.main import app
from lesr.errors import LESRError
from lesr.importing.service import ImportService

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
    left = project / "left.md"
    right = project / "right.md"
    left.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    right.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))

    service = ImportService(project)
    left_result = service.preview(Path("left.md"))
    right_result = service.preview(Path("right.md"))

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
