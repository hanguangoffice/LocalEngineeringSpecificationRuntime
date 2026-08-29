"""Frozen LESR 1.0 repository and capability contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from lesr.domain.semantic import FrozenModel, document_hash

CANONICAL_FORMAT_VERSION = "1.0.0"
RUNTIME_CONTRACT_VERSION = "1.0.0"


class GateState(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    PASS = "PASS"
    FAIL = "FAIL"
    DEFERRED = "DEFERRED"


class CapabilityAccess(StrEnum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class RuntimeCapability(FrozenModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]+$")
    access: CapabilityAccess
    cli: bool = False
    mcp: bool = False
    persistent_task: bool = False


SCHEMA_CATALOG: tuple[str, ...] = (
    "applied-change.schema.json",
    "approval-attestation.schema.json",
    "approval-revocation.schema.json",
    "audit-anchor.schema.json",
    "baseline-manifest.schema.json",
    "baseline-preparation.schema.json",
    "candidate-revision.schema.json",
    "canonical-resource.schema.json",
    "capability-descriptor.schema.json",
    "checkpoint.schema.json",
    "comment-resolution.schema.json",
    "common.schema.json",
    "condition-satisfaction.schema.json",
    "configuration.schema.json",
    "conflict-resolution.schema.json",
    "context-bundle.schema.json",
    "context-contract.schema.json",
    "delegation-grant.schema.json",
    "domain-error.schema.json",
    "edit-operation.schema.json",
    "effective-model.schema.json",
    "facet-definition.schema.json",
    "graph-snapshot.schema.json",
    "immutable-record.schema.json",
    "impact-report.schema.json",
    "kind-definition.schema.json",
    "logical-object.schema.json",
    "mapping-pack.schema.json",
    "merge-conflict.schema.json",
    "normative-profile.schema.json",
    "provenance.schema.json",
    "relation-assertion.schema.json",
    "relation-identity.schema.json",
    "relation-type.schema.json",
    "repository-manifest.schema.json",
    "review-comment.schema.json",
    "review-package.schema.json",
    "revision.schema.json",
    "rule-definition.schema.json",
    "semantic-diff.schema.json",
    "semantic-transaction.schema.json",
    "tailoring-overlay.schema.json",
    "task-record.schema.json",
    "trusted-actor.schema.json",
    "validation-finding.schema.json",
    "validation-run.schema.json",
    "workflow.schema.json",
    "workspace.schema.json",
)

# Mission execution, decision routing, and presentation are local-runtime
# resources.  They deliberately stay outside the canonical repository manifest:
# restarting or upgrading the agent runtime must not change the engineering
# state contract of an existing 1.0 repository.
RUNTIME_SCHEMA_CATALOG: tuple[str, ...] = (
    "agent-run.schema.json",
    "decision-request.schema.json",
    "mission-mandate.schema.json",
    "mission.schema.json",
    "presentation-mapping.schema.json",
    "work-package.schema.json",
)

CONSTRUCTION_SCHEMA_CATALOG: tuple[str, ...] = tuple(
    sorted((*SCHEMA_CATALOG, *RUNTIME_SCHEMA_CATALOG))
)


CAPABILITIES: tuple[RuntimeCapability, ...] = tuple(
    sorted(
        (
            RuntimeCapability(
                name=name,
                access=access,
                cli=cli,
                mcp=mcp,
                persistent_task=task,
            )
            for name, access, cli, mcp, task in (
                ("resolve", CapabilityAccess.READ, True, True, False),
                ("inspect", CapabilityAccess.READ, True, True, False),
                ("query", CapabilityAccess.READ, True, True, False),
                ("traverse", CapabilityAccess.READ, True, True, False),
                ("impact", CapabilityAccess.READ, True, True, False),
                ("context.plan", CapabilityAccess.READ, True, True, False),
                ("context.read", CapabilityAccess.READ, True, True, False),
                ("context.trace", CapabilityAccess.READ, True, True, True),
                ("configuration.plan", CapabilityAccess.READ, True, False, False),
                ("configuration.create", CapabilityAccess.WRITE, True, False, False),
                ("governance.approval-record", CapabilityAccess.WRITE, True, False, False),
                ("workspace.open", CapabilityAccess.WRITE, True, True, False),
                ("workspace.edit", CapabilityAccess.WRITE, True, True, False),
                ("workspace.checkpoint", CapabilityAccess.WRITE, True, False, False),
                ("workspace.submit", CapabilityAccess.WRITE, True, True, False),
                ("workspace.rebase", CapabilityAccess.WRITE, True, True, False),
                ("workspace.merge", CapabilityAccess.WRITE, True, True, False),
                ("workspace.resolve", CapabilityAccess.WRITE, True, True, False),
                ("review.comment", CapabilityAccess.WRITE, True, True, False),
                ("review.resolve", CapabilityAccess.WRITE, True, True, False),
                ("review.condition", CapabilityAccess.WRITE, True, True, False),
                ("review.revoke", CapabilityAccess.WRITE, True, True, False),
                ("reconciliation.open", CapabilityAccess.WRITE, True, True, False),
                ("apply", CapabilityAccess.WRITE, True, True, False),
                ("baseline.prepare", CapabilityAccess.WRITE, True, True, False),
                ("baseline.apply", CapabilityAccess.WRITE, True, True, False),
                ("baseline.tag-rebuild", CapabilityAccess.WRITE, True, False, False),
                ("projection.rebuild", CapabilityAccess.ADMIN, True, False, False),
                ("backup", CapabilityAccess.ADMIN, True, False, False),
                ("restore", CapabilityAccess.ADMIN, True, False, False),
                ("migrate", CapabilityAccess.ADMIN, True, False, False),
                ("gc", CapabilityAccess.ADMIN, True, False, False),
            )
        ),
        key=lambda item: item.name,
    )
)


class RepositoryManifest(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["repository_manifest"] = "repository_manifest"
    canonical_format_version: Literal["1.0.0"] = "1.0.0"
    runtime_contract_version: Literal["1.0.0"] = "1.0.0"
    schema_catalog: tuple[str, ...] = SCHEMA_CATALOG
    capabilities: tuple[RuntimeCapability, ...] = CAPABILITIES
    compatibility: Literal["breaking_from_0.5_no_migration"] = "breaking_from_0.5_no_migration"
    repository_scope: Literal["local_single_repository_single_user"] = (
        "local_single_repository_single_user"
    )
    manifest_hash: str = ""

    @model_validator(mode="after")
    def validate_manifest(self) -> RepositoryManifest:
        if self.schema_catalog != SCHEMA_CATALOG:
            raise ValueError("schema_catalog does not match runtime 1.0")
        expected_capabilities = [item.model_dump(mode="json") for item in CAPABILITIES]
        actual_capabilities = [item.model_dump(mode="json") for item in self.capabilities]
        if actual_capabilities != expected_capabilities:
            raise ValueError("capability descriptor does not match runtime 1.0")
        expected = document_hash(self.model_dump(mode="json"), "manifest_hash")
        if self.manifest_hash and self.manifest_hash != expected:
            raise ValueError("manifest_hash does not match repository contract")
        object.__setattr__(self, "manifest_hash", expected)
        return self


def default_repository_manifest() -> RepositoryManifest:
    return RepositoryManifest()
