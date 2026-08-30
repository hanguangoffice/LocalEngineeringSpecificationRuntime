from __future__ import annotations

import os
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from lesr.adapters.git import GitCanonicalRepository
from lesr.adapters.web import LocalWebRuntime
from tests.support.public_product import bootstrap_public_product


@pytest.mark.playwright
def test_local_ui_uses_real_repository_query_and_lock_flow(tmp_path: Path) -> None:
    repository = GitCanonicalRepository(tmp_path)
    repository.initialize()
    repository.rebuild_projection(tmp_path / ".lesr" / "projection.sqlite3")
    runtime = LocalWebRuntime(tmp_path, launch_token="playwright-token")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(runtime.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="msedge" if os.name == "nt" else None
            )
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/unlock?token=playwright-token")
            expect(page.locator("#overview h1")).to_be_visible()
            assert page.evaluate("window.__LESR_MOTION__.engine") == "GSAP"
            assert page.evaluate("window.gsap.version") == "3.15.0"
            assert page.evaluate(
                "parseFloat(getComputedStyle(document.documentElement).fontSize)"
            ) >= 16
            assert page.evaluate(
                "parseFloat(getComputedStyle(document.querySelector('input')).fontSize)"
            ) >= 16
            expect(page.locator(".priority-work")).to_be_visible()
            expect(page.locator("#overview")).not_to_contain_text("sha256:")
            expect(page.locator("#overview")).not_to_contain_text(
                repository.current_commit()
            )
            page.get_by_role("button", name="导入现有规范").click()
            expect(page.locator("#intake-import-form")).to_be_visible()
            page.get_by_role("tab", name="描述需求").click()
            intake = page.locator("#intake-form")
            intake.get_by_label("工程名称（可选）").fill("temporary-ai-console")
            intake.get_by_label("你的需求").fill(
                "创建一个 Windows 11 本地 AI 工具，检测 NVIDIA GPU 和显存，"
                "提供 PyTorch 模拟测试。未经确认不得全局安装软件。"
            )
            intake.get_by_role("button", name="整理工程内容").click()
            expect(page.locator("#intake-pack")).to_have_text("本地 AI、GPU 与模型应用")
            expect(page.locator("#intake-requirements .intake-requirement")).to_have_count(1)
            expect(page.locator("#intake")).not_to_contain_text("sha256:")
            expect(page.locator("#intake")).not_to_contain_text("59dc772b")
            expect(page.locator("#intake")).not_to_contain_text("系统负责")
            expect(page.locator("#intake")).not_to_contain_text("高影响操作边界")
            page.get_by_role("tab", name="导入规范文件").click()
            imported = page.locator("#intake-import-form")
            imported.get_by_label("规范文件").set_input_files(
                {
                    "name": "custom-spec.md",
                    "mimeType": "text/markdown",
                    "buffer": (
                        "# GPU 检测\n\n- 读取 NVIDIA GPU 型号和显存。\n\n"
                        "# 测试\n\n- 模拟无 GPU 场景。\n"
                    ).encode(),
                }
            )
            imported.get_by_role("button", name="读取规范文件").click()
            expect(page.locator("#intake-count")).to_have_text("2 项")
            page.locator('button[data-panel="explore"]').click()
            page.get_by_label("工程编号或关键词").fill("no-synthetic-result")
            page.get_by_role("button", name="搜索").click()
            page.get_by_text("没有找到“no-synthetic-result”").wait_for()
            expect(page.locator("#query-result-count")).to_have_text("没有匹配内容")
            page.wait_for_timeout(650)
            page.screenshot(path=str(tmp_path / "explore-empty.png"), full_page=True)
            for panel_name in ("context", "tasks", "maintenance"):
                page.locator(f'button[data-panel="{panel_name}"]').click()
                expect(page.locator(f"#{panel_name}")).to_be_visible()
                page.wait_for_timeout(650)
                page.screenshot(
                    path=str(tmp_path / f"{panel_name}-empty.png"), full_page=True
                )
            page.locator('button[data-panel="audit"]').click()
            expect(page.locator("#audit-commit")).to_have_text(
                repository.current_commit()
            )
            page.wait_for_timeout(650)
            page.screenshot(path=str(tmp_path / "audit-collapsed.png"), full_page=True)
            assert not page_errors
            page.get_by_role("button", name="锁定会话").click()
            page.get_by_role("heading", name="LESR is locked").wait_for()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


@pytest.mark.playwright
def test_local_ui_honors_reduced_motion_without_hiding_state(tmp_path: Path) -> None:
    repository = GitCanonicalRepository(tmp_path)
    repository.initialize()
    runtime = LocalWebRuntime(tmp_path, launch_token="reduced-motion-token")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(runtime.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="msedge" if os.name == "nt" else None
            )
            page = browser.new_page(viewport={"width": 820, "height": 1100})
            page.emulate_media(reduced_motion="reduce")
            page.goto(
                f"http://127.0.0.1:{port}/unlock?token=reduced-motion-token"
            )
            page.wait_for_load_state("networkidle")
            assert page.evaluate("window.gsap.version") == "3.15.0"
            expect(page.locator("#overview h1")).to_be_visible()
            expect(page.locator(".overview-actions button")).to_have_count(3)
            page.screenshot(path=str(tmp_path / "narrow-overview.png"), full_page=True)
            page.locator('button[data-panel="workspace"]').click()
            expect(page.locator("#workspace")).to_be_visible()
            for panel_name in (
                "explore",
                "context",
                "review",
                "baseline",
                "tasks",
                "maintenance",
                "audit",
            ):
                page.locator(f'button[data-panel="{panel_name}"]').click()
                expect(page.locator(f"#{panel_name}")).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth + 1"
                )
            page.set_viewport_size({"width": 390, "height": 844})
            for panel_name in ("explore", "context", "review", "baseline"):
                page.locator(f'button[data-panel="{panel_name}"]').click()
                expect(page.locator(f"#{panel_name}")).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth + 1"
                )
            page.screenshot(path=str(tmp_path / "narrow-task-page.png"), full_page=True)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


@pytest.mark.playwright
def test_local_ui_turns_a_raw_request_into_an_agent_mission(tmp_path: Path) -> None:
    project = tmp_path / "edge-telemetry-observatory"
    GitCanonicalRepository(project).initialize()
    runtime = LocalWebRuntime(
        project,
        launch_token="zero-spec-token",
        signer_key_root=tmp_path / "keys",
        signer_password="zero-spec-test-password",
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(runtime.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="msedge" if os.name == "nt" else None
            )
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(f"http://127.0.0.1:{port}/unlock?token=zero-spec-token")
            page.wait_for_load_state("networkidle")
            page.locator('button[data-panel="intake"]').click()
            form = page.locator("#intake-form")
            form.get_by_label("工程名称（可选）").fill(
                "edge-telemetry-observatory"
            )
            form.get_by_label("你的需求").fill(
                "创建一个本地事件遥测工程。\n"
                "- 通过 MQTT 接收边缘设备状态；\n"
                "- 使用 AsyncAPI 描述消息契约；\n"
                "- 模拟断线、重连和重复消息；\n"
                "- 提供可重复运行的自动测试。"
            )
            form.get_by_role("button", name="整理工程内容").click()
            expect(page.locator("#intake-pack")).to_have_text(
                "事件驱动、消息与 IoT 集成"
            )
            expect(page.locator("#intake-count")).to_have_text("4 项")
            page.screenshot(path=str(tmp_path / "zero-spec-intake.png"), full_page=True)
            accept = page.locator("#intake-accept-form")
            expect(accept.get_by_role("checkbox")).to_have_count(0)
            with page.expect_response("**/api/intake/accept") as response_info:
                accept.get_by_role("button", name="建立工程草案").click()
            accepted = response_info.value.json()
            expect(page.locator("#missions")).to_be_visible()
            expect(page.locator("#mission-title")).to_contain_text(
                "edge-telemetry-observatory"
            )
            expect(page.locator("#mission-dag .mission-node")).to_have_count(4)
            mission_uid = accepted["mission"]["mission_uid"]
            ready = runtime.domain.ready_mission_work(mission_uid)
            assert ready.ok, ready.payload()
            assignment = ready.value[0]
            claimed = runtime.domain.claim_mission_work(
                mission_uid,
                assignment["work_package_uid"],
                "agent:requirements",
                "codex",
                "configured-model",
                "mcp",
            )
            assert claimed.ok, claimed.payload()
            evaluation = runtime.domain.evaluate_mission_work(
                mission_uid,
                assignment["work_package_uid"],
                accepted["workspace_uid"],
                datetime.now(UTC).isoformat(),
                "workspace.validate",
            )
            assert evaluation.ok, evaluation.payload()
            assert evaluation.value["policy"]["disposition"] == "AUTO_EXECUTE"
            finished = runtime.domain.report_mission_work(
                {
                    "mission_uid": mission_uid,
                    "work_package_uid": assignment["work_package_uid"],
                    "agent_run_uid": claimed.value["agent_run"]["agent_run_uid"],
                    "state": "completed",
                    "result_summary": "需求结构已经整理并完成工作区检查。",
                    "reported_at": datetime.now(UTC).isoformat(),
                }
            )
            assert finished.ok, finished.payload()
            page.locator('button[data-panel="overview"]').click()
            page.locator('button[data-panel="missions"]').click()
            expect(page.locator('.mission-node[data-state="completed"]')).to_have_count(1)
            expect(page.locator('.mission-node[data-state="ready"]')).to_have_count(1)
            expect(page.locator("#decision-nav-count")).to_be_hidden()
            page.screenshot(path=str(tmp_path / "agent-mission-1920x1080.png"), full_page=True)
            canonical = tuple(item for _, item in runtime.domain.repository.documents())
            assert not [item for item in canonical if item.get("resource_type") == "revision"]
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


@pytest.mark.playwright
def test_local_ui_completes_edit_review_sign_apply_and_baseline(tmp_path: Path) -> None:
    product = bootstrap_public_product(tmp_path)
    runtime = LocalWebRuntime(
        product.domain.project,
        launch_token="product-flow-token",
        signer_key_root=tmp_path / "keys",
        signer_password=product.signer_password,
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(runtime.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="msedge" if os.name == "nt" else None
            )
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"http://127.0.0.1:{port}/unlock?token=product-flow-token")
            page.wait_for_load_state("networkidle")
            page.locator('button[data-panel="workspace"]').click()
            change_form = page.locator("#workspace-compose-form")
            expect(change_form.get_by_label("工程配置")).to_have_value(
                product.configuration_uid
            )
            expect(change_form.get_by_label("操作人")).to_have_value(
                product.actor_uid
            )
            change_form.get_by_label("工程编号").fill("DES-WEB-1")
            change_form.get_by_label("内容类型").select_option("software_design")
            change_form.get_by_label("正文或说明").fill(
                "The controller shall publish a deterministic state frame."
            )
            change_form.get_by_label("变更理由").fill("补充控制器状态发布设计。")
            page.screenshot(path=str(tmp_path / "change-composer.png"), full_page=True)
            change_form.get_by_role("button", name="保存并检查").click()
            expect(page.locator("#workspace-output")).to_contain_text("已完成检查")
            page.get_by_role("button", name="送交正式审阅").click()
            page.locator("#sign-form").wait_for()
            expect(page.locator("#review-reason")).to_contain_text(
                "补充控制器状态发布设计"
            )
            expect(page.locator("#sign-scope")).to_contain_text("DES-WEB-1")
            expect(page.locator("#review")).not_to_contain_text("sha256:")
            page.wait_for_timeout(650)
            page.screenshot(path=str(tmp_path / "review-populated.png"), full_page=True)
            candidate_package_uid = page.locator(
                '#sign-form [name="package_uid"]'
            ).input_value()

            sign_form = page.locator("#sign-form")
            expect(sign_form.get_by_label("批准人")).to_have_value(product.actor_uid)
            expect(sign_form.locator('[name="role"]')).to_have_value("technical")
            sign_form.get_by_role("checkbox").check()
            sign_form.get_by_role("button", name="批准并写入工程").click()
            expect(page.locator("#sign-output")).to_contain_text("已写入工程", timeout=60_000)

            page.locator('button[data-panel="explore"]').click()
            search = page.get_by_label("工程编号或关键词")
            search.fill("DES-WEB")
            expect(page.locator("#query-results")).to_contain_text("DES-WEB-1")
            expect(page.locator("#query-results")).to_contain_text(
                "deterministic state frame"
            )
            expect(page.locator("#query-results")).not_to_contain_text("编辑中")
            page.wait_for_timeout(650)
            page.screenshot(path=str(tmp_path / "explore-populated.png"), full_page=True)

            page.locator('button[data-panel="baseline"]').click()
            baseline_form = page.locator("#baseline-form")
            result_configuration_uid = baseline_form.get_by_label("工程配置").input_value()
            assert result_configuration_uid != product.configuration_uid
            baseline_form.get_by_label("版本名称（可选）").fill("设计冻结 1.0")
            baseline_form.get_by_role("button", name="检查并进入批准").click()
            page.locator("#sign-form").wait_for()
            page.wait_for_function(
                "previous => document.querySelector('#sign-form [name=package_uid]').value !== previous",
                arg=candidate_package_uid,
            )
            sign_form.get_by_role("checkbox").check()
            sign_form.get_by_role("button", name="批准并发布基线").click()
            expect(page.locator("#baseline-output")).to_contain_text("已发布", timeout=60_000)
            page.wait_for_timeout(650)
            page.screenshot(path=str(tmp_path / "baseline-published.png"), full_page=True)
            canonical_documents = tuple(
                item for _, item in runtime.domain.repository.documents()
            )
            configuration = next(
                item
                for item in canonical_documents
                if item.get("resource_type") == "configuration_snapshot"
                and item.get("configuration_uid") == result_configuration_uid
            )
            manifest = next(
                item
                for item in canonical_documents
                if item.get("resource_type") == "baseline_manifest"
                and item.get("configuration_uid") == result_configuration_uid
            )
            assert configuration["revision_uids"]
            assert manifest["exact_revision_uids"] == configuration["revision_uids"]
            assert manifest["exact_relation_revision_uids"] == configuration[
                "relation_revision_uids"
            ]
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
