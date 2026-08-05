"""Synthetic and copyright-safe P1 gate dataset."""

from __future__ import annotations

from dataclasses import dataclass

from lesr.domain.semantic import (
    BindingMode,
    CoreFacet,
    CoreRelationRole,
    CoreResourceClass,
    LogicalObject,
    ProvenanceKind,
    RelationAssertion,
    RelationEndpoint,
    Revision,
    SemanticField,
)


@dataclass(frozen=True, slots=True)
class SemanticGateDataset:
    logical_objects: tuple[LogicalObject, ...]
    revisions: tuple[Revision, ...]
    relations: tuple[RelationAssertion, ...]


def build_semantic_gate_dataset() -> SemanticGateDataset:
    specs = (
        [(f"REQ-SW-{index:04d}", "software_requirement") for index in range(1, 11)]
        + [(f"DES-SW-{index:04d}", "software_design") for index in range(1, 11)]
        + [(f"TEST-SW-{index:04d}", "test_case") for index in range(1, 11)]
        + [(f"RULE-C-{index:04d}", "coding_rule") for index in range(1, 21)]
        + [(f"SIG-CAN-{index:04d}", "can_signal") for index in range(1, 21)]
        + [(f"CHG-{index:04d}", "change") for index in range(1, 5)]
        + [(f"DEV-{index:04d}", "deviation") for index in range(1, 4)]
        + [(f"EVD-{index:04d}", "evidence") for index in range(1, 4)]
    )
    objects: list[LogicalObject] = []
    revisions: list[Revision] = []
    for human_key, kind in specs:
        facets = _facets(kind)
        core_class = (
            CoreResourceClass.IMMUTABLE_RECORD
            if kind == "evidence"
            else CoreResourceClass.GOVERNED_OBJECT
        )
        logical = LogicalObject(
            namespace="tests/automotive",
            human_key=human_key,
            kind=kind,
            core_class=core_class,
            facets=facets,
        )
        objects.append(logical)
        revisions.append(
            Revision(
                object_uid=logical.entity_uid,
                revision_number=1,
                human_key=human_key,
                kind=kind,
                facets=facets,
                fields=(
                    SemanticField.from_value("title", f"Synthetic {kind} {human_key}"),
                    SemanticField.from_value("source.license", "synthetic"),
                ),
                provenance_origin=ProvenanceKind.AUTHORED,
            )
        )

    by_key = {item.human_key: item for item in objects}
    relations: list[RelationAssertion] = []
    for index in range(1, 11):
        relations.extend(
            (
                _relation(
                    by_key[f"DES-SW-{index:04d}"],
                    "design_realizes_requirement",
                    CoreRelationRole.REALIZES,
                    by_key[f"REQ-SW-{index:04d}"],
                    "realization",
                ),
                _relation(
                    by_key[f"TEST-SW-{index:04d}"],
                    "test_verifies_requirement",
                    CoreRelationRole.VERIFIES,
                    by_key[f"REQ-SW-{index:04d}"],
                    "verification",
                ),
            )
        )
    return SemanticGateDataset(tuple(objects), tuple(revisions), tuple(relations))


def _facets(kind: str) -> tuple[str, ...]:
    if kind == "coding_rule":
        return (
            CoreFacet.AUTHORED,
            CoreFacet.LIFECYCLE,
            CoreFacet.NORMATIVE,
            CoreFacet.APPLICABILITY,
            CoreFacet.EXECUTABLE,
        )
    if kind == "evidence":
        return (CoreFacet.RECORD, CoreFacet.EVIDENCE)
    return (CoreFacet.AUTHORED, CoreFacet.LIFECYCLE, CoreFacet.TRACEABILITY)


def _relation(
    source: LogicalObject,
    predicate: str,
    role: CoreRelationRole,
    target: LogicalObject,
    trace_category: str,
) -> RelationAssertion:
    return RelationAssertion(
        predicate=predicate,
        core_role=role,
        source=RelationEndpoint(binding=BindingMode.LOGICAL, object_uid=source.entity_uid),
        target=RelationEndpoint(binding=BindingMode.LOGICAL, object_uid=target.entity_uid),
        scope="tests/default",
        provenance_kind=ProvenanceKind.ASSERTED,
        formal_trace_categories=(trace_category,),
    )
