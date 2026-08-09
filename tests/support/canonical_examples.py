from __future__ import annotations

from lesr.domain.semantic import semantic_hash

OBJECT_UID = "018f0000-0000-7000-8000-000000000001"
REVISION_UID = "018f0000-0000-7000-8000-000000000002"


def canonical_resources() -> tuple[dict[str, object], dict[str, object]]:
    logical: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "logical_object",
        "entity_uid": OBJECT_UID,
        "namespace": "demo",
        "human_key": "REQ-SW-0001",
        "kind": "software_requirement",
        "core_class": "governed_object",
        "facets": ["authored", "traceability"],
        "aliases": [],
        "external_identities": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    revision_without_hash: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "revision",
        "revision_uid": REVISION_UID,
        "object_uid": OBJECT_UID,
        "revision_number": 1,
        "parent_revision_uid": None,
        "human_key": "REQ-SW-0001",
        "kind": "software_requirement",
        "facets": ["authored", "traceability"],
        "fields": [{"path": "/statement", "value": "The client shall reconnect."}],
        "fragments": [],
        "provenance_origin": "authored",
        "created_at": "2026-08-05T00:00:00Z",
    }
    return logical, revision_without_hash | {
        "content_hash": semantic_hash(revision_without_hash)
    }
