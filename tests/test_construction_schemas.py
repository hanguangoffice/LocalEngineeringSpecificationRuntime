from __future__ import annotations

from lesr.adapters.schemas import SchemaCatalog
from scripts.verify_construction_schemas import verify
from tests.support.canonical_examples import canonical_resources


def test_v1_construction_schemas_are_self_consistent() -> None:
    assert verify() == 0


def test_runtime_catalog_validates_canonical_examples() -> None:
    logical, revision = canonical_resources()
    catalog = SchemaCatalog()
    catalog.validate("logical-object.schema.json", logical)
    catalog.validate("revision.schema.json", revision)
