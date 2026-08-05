from __future__ import annotations

from lesr.adapters.markdown import preview_markdown


def test_markdown_preview_only_returns_workspace_operations(tmp_path) -> None:
    source = tmp_path / "spec.md"
    source.write_text("# Requirement\n\nThe client shall reconnect.\n", encoding="utf-8")
    before = set(tmp_path.rglob("*"))
    candidates = preview_markdown(source, namespace="demo", kind="requirement")
    assert len(candidates) == 1
    assert [item["operation_type"] for item in candidates[0].operations] == [
        "create_logical_object",
        "create_revision",
    ]
    assert set(tmp_path.rglob("*")) == before
