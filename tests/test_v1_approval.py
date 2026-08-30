from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload, verify_approval
from lesr.domain.semantic import semantic_hash


def test_ed25519_approval_binds_package_model_scope_and_role(tmp_path) -> None:
    store = ApprovalKeyStore(tmp_path / "keys")
    trust = store.generate("USER-1", "Reviewer", ("technical",))
    key_document = json.loads(next((tmp_path / "keys").glob("*.json")).read_text())
    assert "private_key" not in key_document
    assert key_document["protection"] == (
        "windows-dpapi-current-user" if os.name == "nt" else "scrypt-aesgcm-pkcs8"
    )
    payload = ApprovalPayload(
        package_hash="sha256:package",
        effective_model_hash="sha256:model",
        scope={"revision_uids": ["REV-1"]},
        approval_type="technical",
    )
    approval = store.sign(trust, "technical", payload)
    assert "scope_hash" not in approval.model_dump(mode="json")
    verify_approval(
        approval,
        trust,
        package_hash="sha256:package",
        effective_model_hash="sha256:model",
    )
    with pytest.raises(PermissionError, match="review package"):
        verify_approval(
            approval,
            trust,
            package_hash="sha256:tampered",
            effective_model_hash="sha256:model",
        )


def test_revoked_expired_and_modified_approval_are_rejected(tmp_path) -> None:
    store = ApprovalKeyStore(tmp_path / "keys")
    trust = store.generate("USER-1", "Reviewer", ("technical",))
    payload = ApprovalPayload(
        package_hash="sha256:package",
        effective_model_hash="sha256:model",
        scope={"revision_uids": ["REV-1"]},
        approval_type="technical",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    approval = store.sign(trust, "technical", payload)
    with pytest.raises(PermissionError, match="expired"):
        verify_approval(
            approval,
            trust,
            package_hash=payload.package_hash,
            effective_model_hash=payload.effective_model_hash,
            now=datetime.now(UTC) + timedelta(minutes=2),
        )
    with pytest.raises(PermissionError, match="not currently trusted"):
        verify_approval(
            approval,
            trust.model_copy(
                update={
                    "revoked_by_record_uid": "018f0000-0000-7000-8000-000000000099"
                }
            ),
            package_hash=payload.package_hash,
            effective_model_hash=payload.effective_model_hash,
        )
    modified = approval.model_copy(update={"scope": {"revision_uids": ["REV-2"]}})
    with pytest.raises(PermissionError, match="signature"):
        verify_approval(
            modified,
            trust,
            package_hash=payload.package_hash,
            effective_model_hash=payload.effective_model_hash,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("approval_uid", "018f0000-0000-7000-8000-000000000091"),
        ("issued_at", datetime(2026, 8, 5, 1, 2, tzinfo=UTC)),
        ("provenance_uid", "018f0000-0000-7000-8000-000000000092"),
    ],
)
def test_signature_binds_complete_attestation_identity_and_time(
    tmp_path, field: str, value: object
) -> None:
    store = ApprovalKeyStore(tmp_path / "keys")
    trust = store.generate("USER-1", "Reviewer", ("technical",))
    payload = ApprovalPayload(
        package_hash="sha256:package",
        effective_model_hash="sha256:model",
        scope={"revision_uids": ["REV-1"]},
        approval_type="technical",
    )
    approval = store.sign(trust, "technical", payload)
    with pytest.raises(PermissionError, match="signature"):
        verify_approval(
            approval.model_copy(update={field: value}),
            trust,
            package_hash=payload.package_hash,
            effective_model_hash=payload.effective_model_hash,
        )


def test_public_trust_and_approval_documents_match_v1_schemas(tmp_path) -> None:
    actor_uid = "018f0000-0000-7000-8000-000000000001"
    store = ApprovalKeyStore(tmp_path / "keys")
    trust = store.generate(actor_uid, "Reviewer", ("technical",))
    approval = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=semantic_hash({"package": "reviewed"}),
            effective_model_hash=semantic_hash({"profile": "demo"}),
            scope={"revision_uids": ["018f0000-0000-7000-8000-000000000002"]},
            approval_type="technical",
        ),
    )
    catalog = SchemaCatalog()
    catalog.validate("trusted-actor.schema.json", trust.model_dump(mode="json"))
    catalog.validate(
        "approval-attestation.schema.json", approval.model_dump(mode="json")
    )
