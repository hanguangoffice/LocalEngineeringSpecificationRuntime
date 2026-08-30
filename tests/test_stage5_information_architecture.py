from __future__ import annotations

import json
import os
import re
import socket
import time
from pathlib import Path
from threading import Thread

import pytest
import uvicorn
from playwright.sync_api import Request, Route, expect, sync_playwright

from lesr.adapters.git import GitCanonicalRepository
from lesr.adapters.web import LocalWebRuntime

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "lesr" / "web" / "templates" / "index.html"
STYLES = ROOT / "src" / "lesr" / "web" / "static" / "lesr.css"
SCRIPT = ROOT / "src" / "lesr" / "web" / "static" / "lesr.js"


def test_primary_navigation_follows_the_engineering_workflow() -> None:
    page = TEMPLATE.read_text(encoding="utf-8")
    navigation = page.split('<nav class="rail"', maxsplit=1)[1].split("</nav>", maxsplit=1)[0]
    primary = (
        ("overview", "工程地图"),
        ("missions", "任务"),
        ("decisions", "决策"),
        ("explore", "工程内容"),
        ("versions", "版本"),
        ("intake", "从需求开始"),
    )

    positions = [
        navigation.index(f'data-panel="{panel}"')
        for panel, _ in primary
    ]
    assert positions == sorted(positions)
    for panel, label in primary:
        assert re.search(
            rf'data-panel="{panel}"[^>]*>.*?<b>{label}</b>',
            navigation,
        )

    assert navigation.index('data-panel="audit"') > navigation.index(
        'data-panel="maintenance"'
    )


def test_engineering_map_tasks_and_decisions_have_reading_oriented_contracts() -> None:
    page = TEMPLATE.read_text(encoding="utf-8")
    required_ids = {
        "engineering-map",
        "engineering-area-tree",
        "engineering-document-list",
        "engineering-item-detail",
        "engineering-trace-summary",
        "engineering-context-summary",
        "mission-list",
        "mission-dag",
        "mission-agent",
        "mission-next-step",
        "decision-list",
        "decision-request",
        "version-list",
    }
    for element_id in required_ids:
        assert f'id="{element_id}"' in page

    for compatibility_id in (
        "context-form",
        "workspace-compose-form",
        "workspace-output",
        "sign-form",
        "approve-and-apply",
        "baseline-form",
        "task-results",
        "gc-plan",
        "audit-output",
    ):
        assert f'id="{compatibility_id}"' in page

    ordinary_page = page.split('<section class="panel audit-panel"', maxsplit=1)[0]
    for technical_label in (
        "Configuration UID",
        "Delegation UID",
        "Canonical Commit",
        "package_hash",
        "Human Key",
    ):
        assert technical_label not in ordinary_page
    for defensive_phrase in (
        "不影响工程状态",
        "无需进入",
        "不会出现在",
        "系统负责",
    ):
        assert defensive_phrase not in ordinary_page


def test_progressive_views_and_gsap_choreography_stay_local() -> None:
    page = TEMPLATE.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert 'src="/static/vendor/gsap.min.js"' in page
    assert 'src="http' not in page.casefold()
    assert 'href="http' not in page.casefold()
    for endpoint in ("/api/engineering/map", "/api/missions", "/api/decisions"):
        assert endpoint in script

    assert "gsap.matchMedia()" in script
    assert "(prefers-reduced-motion: reduce)" in script
    assert ".addLabel('area')" in script
    assert ".addLabel('documents', 'area+=.07')" in script
    assert ".addLabel('context', 'documents+=.1')" in script
    assert ".addLabel('question')" in script
    assert ".addLabel('evidence', 'question+=.1')" in script
    assert ".addLabel('choice', 'evidence+=.1')" in script
    assert "willChange: 'transform,opacity'" in script
    assert "clearAnimatedState" in script
    assert "backgroundColor" not in script

    root_size = re.search(r"html\s*\{[^}]*font-size:\s*(\d+)px", styles)
    input_size = re.search(
        r"input, select, textarea\s*\{[^}]*font-size:\s*(\d+)px",
        styles,
    )
    assert root_size is not None and int(root_size.group(1)) >= 16
    assert input_size is not None and int(input_size.group(1)) >= 16
    assert re.search(
        r"\.engineering-atlas\s*\{[^}]*grid-template-columns:\s*"
        r"245px\s+minmax\(360px,\s*1\.12fr\)\s+minmax\(330px,\s*\.88fr\)",
        styles,
    )


def test_human_decisions_render_real_contract_and_resume_the_mission() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    decision_renderer = script.split(
        "const renderDecision =", maxsplit=1
    )[1].split("const renderDecisions =", maxsplit=1)[0]

    for contract_field in (
        "decision.target",
        "decision.change_summary",
        "decision.impact",
        "decision.validation",
        "decision.triggered_policies",
        "decision.recommendation",
        "decision.alternatives",
        "decision.action",
    ):
        assert contract_field in decision_renderer

    assert "decision-resolution-form" in decision_renderer
    assert "你的判断依据" in decision_renderer
    assert "actor?.display_name" in decision_renderer
    assert "selected_action" in decision_renderer
    assert "selected_alternative" in decision_renderer
    assert (
        "/api/decisions/${encodeURIComponent(decision.decision_request_uid)}/resolve"
        in decision_renderer
    )
    assert "Promise.all([loadDecisions(), loadMissions()])" in decision_renderer

    # Machine-only targets and policy codes do not enter the normal decision view.
    assert "affected_targets" not in decision_renderer
    assert "policy.policy_code" not in decision_renderer


@pytest.mark.playwright
def test_primary_views_remain_readable_at_laptop_and_narrow_widths(
    tmp_path: Path,
) -> None:
    repository = GitCanonicalRepository(tmp_path)
    repository.initialize()
    runtime = LocalWebRuntime(tmp_path, launch_token="stage5-interface-token")
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
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page_errors: list[str] = []
            resolution_requests: list[dict[str, object]] = []
            decision_open = [True]
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            session_context = {
                "project_name": "边缘遥测工程",
                "audit": {"canonical_commit": "internal-commit-not-for-daily-view"},
                "configurations": [],
                "actors": [
                    {
                        "actor_uid": "internal-actor-not-for-daily-view",
                        "display_name": "本机工程负责人",
                        "roles": ["technical"],
                        "key_uid": None,
                    }
                ],
                "content_types": [],
                "task_types": [],
                "key_suggestions": {},
            }
            decision = {
                "decision_request_uid": "internal-decision-not-for-daily-view",
                "mission_uid": "internal-mission-not-for-daily-view",
                "work_package_uid": "internal-work-not-for-daily-view",
                "mandate_uid": "internal-mandate-not-for-daily-view",
                "disposition": "HUMAN_DECISION_NOW",
                "decision_type": "低显存部署策略",
                "engineering_area": "software_runtime",
                "target": {
                    "label": "推理服务启动参数",
                    "content_type": "software_requirement",
                    "engineering_key": "REQ-RUNTIME-0042",
                },
                "change_summary": "需要在吞吐量与 4GB 显存稳定运行之间确定优先方向。",
                "impact": {
                    "completeness": "complete",
                    "summary": "选择会影响启动配置、性能目标和验证场景。",
                    "affected_areas": ["software_runtime"],
                    "affected_targets": ["internal-object-not-for-daily-view"],
                },
                "validation": {
                    "conclusion": "passed",
                    "summary": "两个方向都满足当前硬性要求。",
                    "evidence": ["internal-evidence-not-for-daily-view"],
                },
                "recommendation": "优先采用低显存配置，把吞吐量优化留到后续任务。",
                "alternatives": [
                    {
                        "title": "优先吞吐量",
                        "summary": "保留较大批次以提高单位时间处理量。",
                        "trade_off": "4GB 显存设备上的可用余量更小。",
                    }
                ],
                "triggered_policies": [
                    {
                        "policy_code": "OPERATION_OUTSIDE_MANDATE",
                        "title": "部署方向发生分叉",
                        "explanation": "两个可行方向会形成不同的后续验证范围。",
                    }
                ],
                "action": {
                    "operation": "workspace.select-low-memory",
                    "label": "采用低显存配置",
                    "result": "后续任务以 4GB 显存稳定运行作为首要目标。",
                },
            }

            page.route(
                "**/api/session-context",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(session_context, ensure_ascii=False),
                ),
            )

            def decisions_route(route: Route) -> None:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([decision] if decision_open[0] else [], ensure_ascii=False),
                )

            def resolve_route(route: Route, request: Request) -> None:
                resolution_requests.append(json.loads(request.post_data or "{}"))
                decision_open[0] = False
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"state": "recorded"}),
                )

            page.route("**/api/decisions", decisions_route)
            page.route("**/api/decisions/*/resolve", resolve_route)
            page.goto(
                f"http://127.0.0.1:{port}/unlock?token=stage5-interface-token"
            )
            page.wait_for_load_state("networkidle")

            expect(page.locator("#engineering-map [data-map-column]")).to_have_count(3)
            page.locator('button[data-panel="decisions"]').click()
            expect(page.locator("#decision-request")).to_contain_text(
                "推理服务启动参数"
            )
            expect(page.locator("#decision-request")).to_contain_text(
                "本机工程负责人"
            )
            expect(page.locator("#decision-request")).not_to_contain_text(
                "internal-object-not-for-daily-view"
            )
            expect(page.locator("#decision-request")).not_to_contain_text(
                "OPERATION_OUTSIDE_MANDATE"
            )
            page.get_by_label("采用低显存配置").check()
            page.get_by_label("你的判断依据").fill("4GB 显存兼容是本阶段的首要目标。")
            page.get_by_role("button", name="记录选择并继续任务").click()
            expect(page.locator("#decision-request")).to_contain_text(
                "当前没有待定的工程取舍"
            )
            assert resolution_requests == [
                {
                    "actor_uid": "internal-actor-not-for-daily-view",
                    "reason": "4GB 显存兼容是本阶段的首要目标。",
                    "selected_action": "workspace.select-low-memory",
                    "selected_alternative": None,
                }
            ]

            for panel_name in ("missions", "decisions", "versions", "overview"):
                page.locator(f'button[data-panel="{panel_name}"]').click()
                expect(page.locator(f"#{panel_name}")).to_be_visible()

            page.set_viewport_size({"width": 390, "height": 844})
            for panel_name in ("overview", "missions", "decisions", "versions"):
                page.locator(f'button[data-panel="{panel_name}"]').click()
                expect(page.locator(f"#{panel_name}")).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth + 1"
                )
            assert not page_errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
