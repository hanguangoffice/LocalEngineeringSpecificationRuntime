"""Automatic first-project bootstrap for requirement intake."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lesr.application.runtime import LocalRuntimeService
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload, TrustedActor
from lesr.domain.model import (
    CompositionMode,
    EffectiveModelCompiler,
    FacetDefinitionRevision,
    FieldDefinition,
    KindDefinitionRevision,
    NormativeProfileRevision,
    ProfileContextPolicy,
    ProfileContribution,
    ProfileLayer,
    ProfileReviewPolicy,
    ProfileReviewStage,
)
from lesr.domain.presentation import PresentationMappingRevision
from lesr.domain.semantic import (
    ConfigurationSnapshot,
    CoreResourceClass,
    document_hash,
    uuid7_candidate,
)
from lesr.intake.engineering_model import (
    build_presentation_mapping,
    engineering_model_for,
)
from lesr.intake.models import TemplatePack


class IntakeBootstrapper:
    """Create local trust and the selected template's engineering model once."""

    def __init__(
        self,
        domain: LocalRuntimeService,
        *,
        key_root: Path | None = None,
        key_password: str | None = None,
    ) -> None:
        self.domain = domain
        self.key_store = ApprovalKeyStore(key_root, password=key_password)

    def ensure(
        self,
        display_name: str,
        selected_pack: TemplatePack,
    ) -> dict[str, str | bool]:
        plan = engineering_model_for(selected_pack)
        current = self._current()
        if current is not None:
            return current | {"created": False}
        existing_identity = self._existing_identity()
        if existing_identity is not None:
            return self._complete_configuration(existing_identity, selected_pack) | {
                "created": False
            }

        actor_uid = uuid7_candidate()
        workspace_uid = uuid7_candidate()
        delegation_uid = uuid7_candidate()
        trust = self.key_store.generate(actor_uid, display_name, ("technical",))
        facet = FacetDefinitionRevision(
            name="engineering_content",
            authority=100,
            fields=(
                FieldDefinition(path="/statement", value_type="string", required=True),
            ),
        )
        kinds = tuple(
            KindDefinitionRevision(
                name=name,
                core_class=CoreResourceClass.GOVERNED_OBJECT,
                required_facet_revision_uids=(facet.revision_uid,),
                authority=100,
            )
            for name in plan.kind_names
        )
        definitions: tuple[
            FacetDefinitionRevision | KindDefinitionRevision, ...
        ] = (facet, *kinds)
        profile = NormativeProfileRevision(
            layer=ProfileLayer.PROJECT,
            authority=100,
            contributions=tuple(
                ProfileContribution(
                    mode=CompositionMode.EXTEND,
                    definition_revision_uid=item.revision_uid,
                )
                for item in definitions
            ),
            review_policies=(
                ProfileReviewPolicy(
                    operation="apply_transaction",
                    require_preparer_independence=False,
                    stages=(
                        ProfileReviewStage(
                            stage="apply_transaction",
                            role="technical",
                            minimum_count=1,
                        ),
                    ),
                ),
                ProfileReviewPolicy(
                    operation="baseline.apply",
                    require_preparer_independence=False,
                    stages=(
                        ProfileReviewStage(
                            stage="baseline", role="technical", minimum_count=1
                        ),
                    ),
                ),
            ),
            context_policies=(ProfileContextPolicy(task_type="*"),),
        )
        model = EffectiveModelCompiler().compile((profile,), definitions)
        issued_at = datetime.now(UTC)
        raw_delegation: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "delegation_grant",
            "delegation_uid": delegation_uid,
            "principal_uid": actor_uid,
            "principal_type": "human",
            "workspace_uid": workspace_uid,
            "base_commit": self.domain.base,
            "operations": [
                "open_workspace",
                "propose_operation",
                "prepare_review",
                "apply_transaction",
            ],
            "scope": {"resource_uids": [], "revision_uids": []},
            "limits": {"max_operations": 500, "max_risk_class": "high"},
            "issued_by": actor_uid,
            "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": (issued_at + timedelta(days=3650))
            .isoformat()
            .replace("+00:00", "Z"),
            "stop_conditions": [],
        }
        delegation = raw_delegation | {
            "content_hash": document_hash(raw_delegation, "content_hash")
        }
        governance = tuple(
            {
                "operation_type": "create_record",
                "resource": item.model_dump(mode="json"),
            }
            for item in definitions
        ) + (
            {
                "operation_type": "update_profile_binding",
                "resource": profile.model_dump(mode="json"),
            },
        )
        trust_value = trust.model_dump(mode="json")
        package_hash, model_hash, scope = self.domain.bootstrap_binding(
            self.domain.base, trust_value, delegation, governance
        )
        approval = self.key_store.sign(
            trust,
            "technical",
            ApprovalPayload(
                package_hash=package_hash,
                effective_model_hash=model_hash,
                scope=scope,
                approval_type="technical",
            ),
        )
        bootstrapped = self.domain.bootstrap_root_owner(
            trust_value,
            delegation,
            approval.model_dump(mode="json"),
            f"intake-bootstrap-{actor_uid}",
            governance,
        )
        if not bootstrapped.ok:
            assert bootstrapped.error is not None
            raise RuntimeError(bootstrapped.error.message)

        configuration = ConfigurationSnapshot(
            base_commit=self.domain.base,
            revision_uids=(),
            relation_revision_uids=(),
            profile_revision_uids=(profile.profile_revision_uid,),
            effective_model_hash=model.model_hash,
            variant=f"zero-spec-intake:{selected_pack.pack_uid}",
            closure_status="complete",
        )
        configuration_value = configuration.model_dump(mode="json")
        package_hash, model_hash, scope = self.domain.initial_configuration_binding(
            self.domain.base, configuration_value
        )
        configuration_approval = self.key_store.sign(
            trust,
            "technical",
            ApprovalPayload(
                package_hash=package_hash,
                effective_model_hash=model_hash,
                scope=scope,
                approval_type="technical",
            ),
        )
        configured = self.domain.initialize_configuration(
            configuration_value,
            configuration_approval.model_dump(mode="json"),
            actor_uid,
            delegation_uid,
            f"intake-configuration-{actor_uid}",
        )
        if not configured.ok:
            assert configured.error is not None
            raise RuntimeError(configured.error.message)
        return {
            "actor_uid": actor_uid,
            "delegation_uid": delegation_uid,
            "configuration_uid": configuration.configuration_uid,
            "workspace_uid": workspace_uid,
            "created": True,
        }

    def presentation_mapping(
        self,
        selected_pack: TemplatePack,
    ) -> PresentationMappingRevision:
        """Bind the selected template to exact active Kind Revision UIDs."""

        plan = engineering_model_for(selected_pack)
        configurations = [
            item
            for item in self.domain.documents
            if item.get("resource_type") == "configuration_snapshot"
            and item.get("closure_status") == "complete"
        ]
        if not configurations:
            raise RuntimeError("工程配置尚未建立，无法创建工程视图")
        configuration = configurations[-1]
        profile_revision_uids = tuple(
            str(item) for item in configuration.get("profile_revision_uids", ())
        )
        profiles = tuple(
            NormativeProfileRevision.model_validate(item)
            for item in self.domain.documents
            if item.get("resource_type") == "normative_profile_revision"
            and item.get("profile_revision_uid") in profile_revision_uids
        )
        active_definition_uids = {
            contribution.definition_revision_uid
            for profile in profiles
            for contribution in profile.contributions
        }
        kind_definitions = tuple(
            KindDefinitionRevision.model_validate(item)
            for item in self.domain.documents
            if item.get("resource_type") == "kind_definition_revision"
            and item.get("revision_uid") in active_definition_uids
        )
        by_name = {item.name: item for item in kind_definitions}
        if len(by_name) != len(kind_definitions):
            raise RuntimeError("当前工程模型存在同名 Kind，无法生成工程视图")
        try:
            return build_presentation_mapping(
                plan,
                by_name,
                profile_revision_uids=profile_revision_uids,
            )
        except ValueError as error:
            raise RuntimeError(str(error)) from error

    def _complete_configuration(
        self,
        identity: dict[str, str],
        selected_pack: TemplatePack,
    ) -> dict[str, str]:
        profiles = tuple(
            NormativeProfileRevision.model_validate(item)
            for item in self.domain.documents
            if item.get("resource_type") == "normative_profile_revision"
        )
        definitions = tuple(
            self.domain._definition_revision(item)
            for item in self.domain.documents
            if item.get("resource_type")
            in {
                "facet_definition_revision",
                "kind_definition_revision",
                "relation_type_revision",
                "workflow_revision",
            }
        )
        if not profiles:
            raise RuntimeError("现有本机身份没有可用的工程 Profile，无法自动建立配置")
        model = EffectiveModelCompiler().compile(profiles, definitions)
        if model.conflicts:
            raise RuntimeError("现有工程 Profile 存在冲突，不能自动建立配置")
        configuration = ConfigurationSnapshot(
            base_commit=self.domain.base,
            revision_uids=(),
            relation_revision_uids=(),
            profile_revision_uids=tuple(item.profile_revision_uid for item in profiles),
            effective_model_hash=model.model_hash,
            variant=f"zero-spec-intake:{selected_pack.pack_uid}",
            closure_status="complete",
        )
        configuration_value = configuration.model_dump(mode="json")
        trust_value = next(
            item
            for item in self.domain.documents
            if item.get("resource_type") == "trusted_actor"
            and item.get("actor_uid") == identity["actor_uid"]
        )
        trust = TrustedActor.model_validate(trust_value)
        package_hash, model_hash, scope = self.domain.initial_configuration_binding(
            self.domain.base, configuration_value
        )
        approval = self.key_store.sign(
            trust,
            "technical",
            ApprovalPayload(
                package_hash=package_hash,
                effective_model_hash=model_hash,
                scope=scope,
                approval_type="technical",
            ),
        )
        result = self.domain.initialize_configuration(
            configuration_value,
            approval.model_dump(mode="json"),
            identity["actor_uid"],
            identity["delegation_uid"],
            f"intake-configuration-{identity['actor_uid']}",
        )
        if not result.ok:
            assert result.error is not None
            raise RuntimeError(result.error.message)
        return identity | {"configuration_uid": configuration.configuration_uid}

    def _current(self) -> dict[str, str] | None:
        actors = [
            item
            for item in self.domain.documents
            if item.get("resource_type") == "trusted_actor"
            and item.get("revoked_by_record_uid") is None
        ]
        configurations = [
            item
            for item in self.domain.documents
            if item.get("resource_type") == "configuration_snapshot"
            and item.get("closure_status") == "complete"
        ]
        delegations = [
            item
            for item in self.domain.documents
            if item.get("resource_type") == "delegation_grant"
        ]
        if not actors or not configurations or not delegations:
            return None
        actor = actors[0]
        delegation = next(
            (
                item
                for item in delegations
                if item.get("principal_uid") == actor.get("actor_uid")
            ),
            delegations[0],
        )
        configuration = configurations[-1]
        return {
            "actor_uid": str(actor["actor_uid"]),
            "delegation_uid": str(delegation["delegation_uid"]),
            "configuration_uid": str(configuration["configuration_uid"]),
            "workspace_uid": str(delegation["workspace_uid"]),
        }

    def _existing_identity(self) -> dict[str, str] | None:
        actors = [
            item
            for item in self.domain.documents
            if item.get("resource_type") == "trusted_actor"
            and item.get("revoked_by_record_uid") is None
        ]
        delegations = [
            item
            for item in self.domain.documents
            if item.get("resource_type") == "delegation_grant"
        ]
        if not actors or not delegations:
            return None
        actor = actors[0]
        delegation = next(
            (
                item
                for item in delegations
                if item.get("principal_uid") == actor.get("actor_uid")
            ),
            None,
        )
        if delegation is None:
            return None
        return {
            "actor_uid": str(actor["actor_uid"]),
            "delegation_uid": str(delegation["delegation_uid"]),
            "workspace_uid": str(delegation["workspace_uid"]),
        }
