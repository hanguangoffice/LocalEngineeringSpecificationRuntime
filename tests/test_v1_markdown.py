from __future__ import annotations

from lesr.adapters.markdown import preview_markdown
from lesr.adapters.schemas import SchemaCatalog


def test_markdown_preview_only_returns_workspace_operations(tmp_path) -> None:
    source = tmp_path / "spec.md"
    source.write_text("# Requirement\n\nThe client shall reconnect.\n", encoding="utf-8")
    before = set(tmp_path.rglob("*"))
    candidates = preview_markdown(
        source,
        namespace="demo",
        kind="requirement",
        rights_basis="author-provided",
        license_id="project-internal",
    )
    assert len(candidates) == 1
    assert [item["operation_type"] for item in candidates[0].operations] == [
        "create_logical_object",
        "create_revision",
    ]
    catalog = SchemaCatalog()
    catalog.validate(
        "logical-object.schema.json", candidates[0].operations[0]["resource"]
    )
    catalog.validate("revision.schema.json", candidates[0].operations[1]["resource"])
    assert set(tmp_path.rglob("*")) == before
