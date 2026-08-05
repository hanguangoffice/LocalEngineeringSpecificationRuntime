from __future__ import annotations

from pathlib import Path

import pytest

from lesr.adapters.pdf_import import EncryptedPdfRejected, preview_pdf
from lesr.adapters.schemas import SchemaCatalog

CORPUS = Path(__file__).parents[1] / "测试文档"


@pytest.mark.local_corpus
def test_rights_clear_aspice_pages_form_schema_valid_workspace_candidates() -> None:
    source = CORPUS / "ASPICE_4.0_中文版.pdf"
    if not source.exists():
        pytest.skip("local ASPICE-like evaluation source is not installed")
    candidates = preview_pdf(
        source,
        namespace="local-evaluation",
        kind="process_reference",
        page_numbers=(48, 55, 88),
    )
    assert len(candidates) == 3
    assert all(item.source_hash.startswith("sha256:") for item in candidates)
    catalog = SchemaCatalog()
    for candidate in candidates:
        catalog.validate("logical-object.schema.json", candidate.operations[0]["resource"])
        catalog.validate("revision.schema.json", candidate.operations[1]["resource"])


@pytest.mark.local_corpus
def test_encrypted_misra_source_is_refused_without_decryption_attempt() -> None:
    source = CORPUS / "MISRA-C-2023.pdf"
    if not source.exists():
        pytest.skip("local restricted evaluation source is not installed")
    with pytest.raises(EncryptedPdfRejected, match="refused"):
        preview_pdf(
            source,
            namespace="local-evaluation",
            kind="coding_rule",
            page_numbers=(1,),
        )
