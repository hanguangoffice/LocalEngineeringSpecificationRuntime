from __future__ import annotations

from scripts.verify_construction_schemas import verify


def test_v1_construction_schemas_are_self_consistent() -> None:
    assert verify() == 0
