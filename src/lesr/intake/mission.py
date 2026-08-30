"""Build an executable Mission from a verified intake template selection.

The engineering areas, labels and source identities come from the selected
``TemplatePack``.  This module adds only runtime coordination: which specialist
handles an area and which source-backed area must finish first.
"""

from __future__ import annotations

from collections.abc import Mapping

from lesr.application.mission_runtime import (
    MissionPackagePlan,
    MissionPlan,
)
from lesr.intake.engineering_model import TemplateEngineeringModel
from lesr.intake.models import IntakeAnalysis, TemplateArtifact

_SOURCE_ROLES: Mapping[str, str] = {
    "github-spec-kit-2026-08-28": "requirements",
    "arc42-zh-2026-07-07": "architecture",
    "madr-4.0.0": "architecture_decisions",
    "swagger-petstore-v31-1.0.10": "api_contract",
    "asyncapi-3.1.0": "event_contract",
    "cookiecutter-data-science-2.3.0": "data_and_ml",
    "model-card-toolkit-2.0.0": "model_assurance",
    "owasp-threat-model-library-1.0.2": "threat_modeling",
    "nasa-fret-3.1.0": "formal_requirements",
}

_ALLOWED_OPERATIONS: tuple[str, ...] = (
    "context.plan",
    "workspace.edit",
    "workspace.validate",
    "workspace.checkpoint",
    "workspace.submit",
    "workspace.rebase",
    "impact.analyze",
)


def mission_plan_for_intake(
    analysis: IntakeAnalysis,
    engineering_model: TemplateEngineeringModel,
    *,
    workspace_uid: str,
    actor_uid: str,
    configuration_uid: str,
    project_name: str | None,
) -> MissionPlan:
    """Create one WorkPackage per exact presentation area in dependency order."""

    pack = analysis.selected_pack
    artifacts = {item.artifact_uid: item for item in pack.artifacts}
    area_keys = tuple(item.area_key for item in engineering_model.areas)
    if set(area_keys) != set(artifacts):
        raise ValueError("Mission areas do not match the selected template artifacts")

    primary = next(item for item in pack.artifacts if item.role == "primary")
    source_to_key = {item.source_uid: item.artifact_uid for item in pack.artifacts}
    packages = tuple(
        _package_for(
            artifact,
            primary_key=primary.artifact_uid,
            source_to_key=source_to_key,
            workspace_uid=workspace_uid,
        )
        for artifact in pack.artifacts
    )
    project_label = (project_name or "新工程").strip() or "新工程"
    objective = _objective_summary(analysis)
    return MissionPlan(
        title=f"{project_label} · 工程任务",
        objective=objective,
        initiated_by_actor_uid=actor_uid,
        configuration_uid=configuration_uid,
        engineering_areas=area_keys,
        allowed_operations=_ALLOWED_OPERATIONS,
        packages=packages,
    )


def _package_for(
    artifact: TemplateArtifact,
    *,
    primary_key: str,
    source_to_key: Mapping[str, str],
    workspace_uid: str,
) -> MissionPackagePlan:
    try:
        role = _SOURCE_ROLES[artifact.source_uid]
    except KeyError as error:
        raise ValueError(
            f"Template source has no Mission role: {artifact.source_uid}"
        ) from error

    dependencies: list[str] = []
    if artifact.artifact_uid != primary_key:
        dependencies.append(primary_key)
    architecture_key = source_to_key.get("arc42-zh-2026-07-07")
    if (
        architecture_key is not None
        and artifact.artifact_uid not in {primary_key, architecture_key}
    ):
        dependencies.append(architecture_key)
    data_key = source_to_key.get("cookiecutter-data-science-2.3.0")
    if artifact.source_uid == "model-card-toolkit-2.0.0" and data_key is not None:
        dependencies.append(data_key)

    return MissionPackagePlan(
        key=artifact.artifact_uid,
        title=artifact.display_name,
        objective=artifact.purpose,
        role=role,
        engineering_area=artifact.artifact_uid,
        depends_on=tuple(dict.fromkeys(dependencies)),
        workspace_uid=workspace_uid,
    )


def _objective_summary(analysis: IntakeAnalysis) -> str:
    statements = [item.statement.strip() for item in analysis.requirements if item.statement]
    if not statements:
        return f"按照{analysis.selected_pack.display_name}整理并交付工程内容"
    summary = "；".join(statements[:3])
    return summary if len(summary) <= 500 else summary[:497].rstrip() + "…"
