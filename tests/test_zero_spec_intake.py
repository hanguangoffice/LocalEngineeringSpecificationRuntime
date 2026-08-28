from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from lesr.adapters.git import GitCanonicalRepository
from lesr.adapters.web import LocalWebRuntime
from lesr.application.contracts import RiskClass, WriteEnvelope
from lesr.domain.semantic import uuid7_candidate
from lesr.intake import IntakeCatalog, IntakeRequest, IntakeService

GPU_REQUEST = """
在本地创建一个名为 gpu-lab-manager 的 Git 仓库。（D:\\Proj\\gpu-lab-manager）

目标是构建一个面向 Windows 11 和 NVIDIA 消费级显卡的本地 AI 项目管理器。
当前主要目标硬件是 RTX 3050 Ti Laptop，优先兼容 4GB 显存场景。

第一阶段先实现：
1. 系统检测
   - Windows 版本；
   - NVIDIA GPU 型号；
2. 进程管理
   - 启动、停止、重启；
3. 测试要求
   - 使用模拟 nvidia-smi 输出测试无 GPU 和驱动异常；

安全约束：
- 未经确认不得全局安装软件；
- 未经确认不得修改系统 PATH；

以后接入公开训练素材和本地模型项目。
"""


def unlocked_runtime(
    tmp_path: Path,
) -> tuple[LocalWebRuntime, TestClient, str]:
    project = tmp_path / "project"
    GitCanonicalRepository(project).initialize()
    runtime = LocalWebRuntime(
        project,
        launch_token="intake-token",
        signer_key_root=tmp_path / "keys",
        signer_password="intake-test-password",
    )
    client = TestClient(runtime.app)
    response = client.get("/unlock?token=intake-token", follow_redirects=False)
    assert response.status_code == 303
    page = client.get("/")
    match = re.search(r'name="csrf-token" content="([^"]+)"', page.text)
    assert match is not None
    return runtime, client, match.group(1)


def test_upstream_templates_are_exact_verified_snapshots() -> None:
    catalog = IntakeCatalog()
    verified = catalog.verify_vendored_sources()
    assert len(verified) == 20
    assert {item["source_uid"] for item in verified} == {
        "github-spec-kit-2026-08-28",
        "arc42-zh-2026-07-07",
    }
    assert "## User Scenarios & Testing *(mandatory)*" in catalog.read_vendored(
        "spec-kit/templates/spec-template.md"
    )


def test_gpu_request_selects_source_backed_pack_and_preserves_statements() -> None:
    analysis = IntakeService().analyze(
        IntakeRequest(description=GPU_REQUEST, project_name="gpu-lab-manager")
    )
    assert analysis.selected_pack.pack_uid == "local-ai-runtime"
    assert analysis.source_fidelity == "verified_upstream_snapshot"
    assert any(item.statement == "NVIDIA GPU 型号；" for item in analysis.requirements)
    assert any(item.category.value == "safety" for item in analysis.requirements)
    assert "## User Scenarios & Testing *(mandatory)*" in analysis.starter_document
    assert "### arc42 Architecture Views" in analysis.starter_document
    assert "运行时视图" in analysis.starter_document
    assert analysis.next_question is None
    assert not any(
        item.disposition.value in {"blocking", "needs_decision"}
        for item in analysis.gaps
    )


def test_operational_boundaries_are_resolved_without_user_questions() -> None:
    analysis = IntakeService().analyze(
        IntakeRequest(
            description=(
                "制作一个 Windows 工具，自动安装依赖并下载第三方模型，"
                "完成后提供源代码和运行说明。"
            )
        )
    )
    assert analysis.next_question is None
    assert all(
        item.disposition.value not in {"blocking", "needs_decision"}
        for item in analysis.gaps
    )
    operation_boundary = next(
        item for item in analysis.gaps if item.topic == "高影响操作边界"
    )
    assert operation_boundary.disposition.value == "defaulted"


def test_small_script_uses_exact_spec_kit_lean_source() -> None:
    analysis = IntakeService().analyze(
        IntakeRequest(description="创建一个一次性 Python 脚本工具，读取本地 CSV 并输出统计报告。")
    )
    assert analysis.selected_pack.pack_uid == "small-delivery-lean"
    assert analysis.source_template.endswith("speckit.specify.md")


def test_web_intake_analyzes_without_exposing_internal_ids(tmp_path: Path) -> None:
    _, client, csrf = unlocked_runtime(tmp_path)
    page = client.get("/").text
    assert 'id="intake"' in page
    ordinary = page.split('<section class="panel audit-panel"', maxsplit=1)[0]
    assert "SHA256" not in ordinary
    response = client.post(
        "/api/intake/analyze",
        headers={"X-LESR-CSRF": csrf},
        json={"description": GPU_REQUEST, "project_name": "gpu-lab-manager"},
    )
    assert response.status_code == 200
    assert response.json()["selected_pack"]["pack_uid"] == "local-ai-runtime"


def test_accept_intake_bootstraps_local_identity_configuration_and_workspace(
    tmp_path: Path,
) -> None:
    runtime, client, csrf = unlocked_runtime(tmp_path)
    response = client.post(
        "/api/intake/accept",
        headers={"X-LESR-CSRF": csrf},
        json={
            "description": GPU_REQUEST,
            "project_name": "gpu-lab-manager",
            "display_name": "Local owner",
        },
    )
    assert response.status_code == 200, response.text
    value = response.json()
    workspace = runtime.domain.workspaces[value["workspace_uid"]]
    assert value["identity_created"] is True
    assert len(workspace.working_copies) == value["requirement_count"]
    assert {item.human_key for item in workspace.working_copies} == set(value["human_keys"])
    canonical_types = {item.get("resource_type") for item in runtime.domain.documents}
    assert "trusted_actor" in canonical_types
    assert "configuration_snapshot" in canonical_types
    assert not any(item.get("resource_type") == "revision" for item in runtime.domain.documents)
    assert all(item.state.value == "editable" for item in workspace.working_copies)
    review = runtime.domain.prepare_review(
        WriteEnvelope(
            workspace_uid=value["workspace_uid"],
            expected_base=value["base_commit"],
            idempotency_key=uuid7_candidate(),
            actor=value["actor_uid"],
            delegation_uid=value["delegation_uid"],
            dry_run=False,
            risk_class=RiskClass.HIGH,
            operation={
                "configuration_uid": value["configuration_uid"],
                "evaluation_time": datetime.now(UTC).isoformat(),
                "maximum_depth": 3,
            },
        )
    )
    assert review.ok, review.payload()
    assert review.value["validation"]["operation_decision"]["disposition"] == "allow"


def test_accept_intake_does_not_require_internal_authorization_input(tmp_path: Path) -> None:
    runtime, client, csrf = unlocked_runtime(tmp_path)
    response = client.post(
        "/api/intake/accept",
        headers={"X-LESR-CSRF": csrf},
        json={
            "description": "建立一个本地软件工程并提供可运行代码、测试和使用说明。",
        },
    )
    assert response.status_code == 200
    assert response.json()["workspace_uid"] in runtime.domain.workspaces


def test_web_intake_imports_a_custom_markdown_specification(tmp_path: Path) -> None:
    _, client, csrf = unlocked_runtime(tmp_path)
    source = """# GPU 检测\n\n- 读取 NVIDIA GPU 型号与显存。\n\n# 自动测试\n\n- 使用模拟输出覆盖无 GPU 场景。\n"""
    response = client.post(
        "/api/intake/import-preview",
        headers={"X-LESR-CSRF": csrf},
        json={
            "filename": "gpu-manager.md",
            "content_base64": base64.b64encode(source.encode("utf-8")).decode("ascii"),
            "project_name": "gpu-lab-manager",
        },
    )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["source"] == {"filename": "gpu-manager.md", "section_count": 2}
    assert value["analysis"]["selected_pack"]["pack_uid"] == "local-ai-runtime"
    statements = {item["statement"] for item in value["analysis"]["requirements"]}
    assert "读取 NVIDIA GPU 型号与显存。" in statements
    assert "使用模拟输出覆盖无 GPU 场景。" in statements
