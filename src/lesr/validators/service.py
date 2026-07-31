"""Validation services; validators only report findings and never modify source data."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from jsonschema import Draft202012Validator

from lesr.domain.models import Artifact, Finding, Relation
from lesr.profiles.loader import Profile, RelationPolicy


class ValidationService:
    def validate_artifact(self, artifact: Artifact, profiles: Iterable[Profile], relations: Iterable[Relation]) -> list[Finding]:
        findings: list[Finding] = []
        relation_list = list(relations)
        for profile in profiles:
            schema = profile.schemas.get(artifact.artifact_type)
            if schema:
                findings.extend(self._schema_findings(artifact, schema))
            findings.extend(self._workflow_findings(artifact, profile))
            findings.extend(self._required_relation_findings(artifact, profile.relation_policies, relation_list))
        return findings

    def validate_relation(self, relation: Relation, source: Artifact, target: Artifact, profiles: Iterable[Profile]) -> list[Finding]:
        findings: list[Finding] = []
        for profile in profiles:
            matching = [policy for policy in profile.relation_policies if policy.relation_type == relation.relation_type]
            if matching and not any(self._is_allowed(policy, source, target) for policy in matching):
                findings.append(self._finding("relation.policy", source.id, "error", f"{relation.relation_type} is not allowed from {source.artifact_type} to {target.artifact_type}", {"relation_id": relation.id}))
        return findings

    def can_transition(self, artifact: Artifact, target_status: str, profiles: Iterable[Profile]) -> list[Finding]:
        findings: list[Finding] = []
        for profile in profiles:
            workflow = profile.workflows.get(profile.default_workflow or "")
            if workflow and (artifact.status, target_status) not in workflow.transitions:
                findings.append(self._finding("workflow.transition", artifact.id, "error", f"Transition {artifact.status} -> {target_status} is not allowed", {"profile_id": profile.profile_id}))
        return findings

    def _schema_findings(self, artifact: Artifact, schema: dict[str, object]) -> list[Finding]:
        instance = artifact.model_dump(mode="json")
        errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda error: list(error.path))
        return [self._finding("schema.json", artifact.id, "error", error.message, {"path": list(error.path)}) for error in errors]

    def _workflow_findings(self, artifact: Artifact, profile: Profile) -> list[Finding]:
        workflow = profile.workflows.get(profile.default_workflow or "")
        if workflow and artifact.status not in workflow.states:
            return [self._finding("workflow.state", artifact.id, "error", f"Status {artifact.status} is not in workflow {workflow.workflow_id}", {})]
        return []

    def _required_relation_findings(self, artifact: Artifact, policies: Iterable[RelationPolicy], relations: list[Relation]) -> list[Finding]:
        findings: list[Finding] = []
        for policy in policies:
            required = policy.minimum_by_status.get(artifact.status, 0)
            if required and artifact.artifact_type in policy.source_types:
                count = sum(1 for relation in relations if relation.source_id == artifact.id and relation.relation_type == policy.relation_type and relation.status == "active")
                if count < required:
                    findings.append(self._finding("traceability.required_relation", artifact.id, "error", f"{artifact.status} {artifact.artifact_type} requires {required} {policy.relation_type} relation(s)", {"actual": count, "relation_type": policy.relation_type}))
        return findings

    @staticmethod
    def _is_allowed(policy: RelationPolicy, source: Artifact, target: Artifact) -> bool:
        return (not policy.source_types or source.artifact_type in policy.source_types) and (not policy.target_types or target.artifact_type in policy.target_types)

    @staticmethod
    def _finding(validator_id: str, artifact_id: str, severity: str, message: str, details: dict[str, object]) -> Finding:
        return Finding(id=f"FIND-{uuid.uuid4().hex[:10].upper()}", validator_id=validator_id, artifact_id=artifact_id, severity=severity, message=message, details=details)
