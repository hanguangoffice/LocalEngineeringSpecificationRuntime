from __future__ import annotations

from lesr.intake.catalog import IntakeCatalog
from lesr.intake.engineering_model import engineering_model_for
from lesr.intake.mission import mission_plan_for_intake
from lesr.intake.models import IntakeAnalysis, IntakeRequest
from lesr.intake.service import IntakeService


def _analysis_for(pack_uid: str) -> IntakeAnalysis:
    catalog = IntakeCatalog()
    pack = catalog.pack(pack_uid)
    analyzed = IntakeService(catalog).analyze(
        IntakeRequest(
            description=(
                "建立一个本地工程，整理需求、架构、实现、测试和发布内容，"
                f"并采用 {pack.display_name} 的工程结构。"
            ),
            project_name=f"fixture-{pack_uid}",
        )
    )
    return analyzed.model_copy(update={"selected_pack": pack})


def test_every_verified_template_pack_builds_an_exact_mission_area_dag() -> None:
    catalog = IntakeCatalog()

    for pack in catalog.packs:
        analysis = _analysis_for(pack.pack_uid)
        engineering_model = engineering_model_for(pack)
        plan = mission_plan_for_intake(
            analysis,
            engineering_model,
            workspace_uid="workspace-1",
            actor_uid="actor-1",
            configuration_uid="configuration-1",
            project_name=f"fixture-{pack.pack_uid}",
        )

        assert plan.engineering_areas == tuple(
            artifact.artifact_uid for artifact in pack.artifacts
        )
        assert tuple(item.key for item in plan.packages) == plan.engineering_areas
        assert all(item.workspace_uid == "workspace-1" for item in plan.packages)
        assert all(item.engineering_area == item.key for item in plan.packages)
        primary = next(
            item.artifact_uid for item in pack.artifacts if item.role == "primary"
        )
        assert next(item for item in plan.packages if item.key == primary).depends_on == ()
        assert all(
            primary in item.depends_on
            for item in plan.packages
            if item.key != primary
        )


def test_model_assurance_waits_for_the_data_and_architecture_areas() -> None:
    pack = IntakeCatalog().pack("local-ai-runtime")
    plan = mission_plan_for_intake(
        _analysis_for(pack.pack_uid),
        engineering_model_for(pack),
        workspace_uid="workspace-1",
        actor_uid="actor-1",
        configuration_uid="configuration-1",
        project_name="temporary-ai-lab",
    )

    model_card = next(item for item in plan.packages if item.key == "model-card")
    assert set(model_card.depends_on) == {
        "spec-kit-standard",
        "arc42-architecture",
        "ccds-project",
    }
