from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lesr.adapters.git import GitCanonicalRepository
from lesr.adapters.signer import sign_once
from lesr.adapters.web import LocalWebRuntime
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload
from lesr.domain.semantic import semantic_hash
from tests.support.public_product import bootstrap_public_product


def unlocked(tmp_path: Path) -> tuple[LocalWebRuntime, TestClient, str]:
    GitCanonicalRepository(tmp_path).initialize()
    runtime = LocalWebRuntime(tmp_path, launch_token="one-time-launch-token")
    client = TestClient(runtime.app)
    response = client.get("/unlock?token=one-time-launch-token", follow_redirects=False)
    assert response.status_code == 303
    page = client.get("/")
    assert page.status_code == 200
    match = re.search(r'name="csrf-token" content="([^"]+)"', page.text)
    assert match is not None
    return runtime, client, match.group(1)


def test_one_time_unlock_cookie_and_loopback_host_boundary(tmp_path: Path) -> None:
    runtime, client, _ = unlocked(tmp_path)
    assert not runtime.launch_token_available
    replay = TestClient(runtime.app).get(
        "/unlock?token=one-time-launch-token", follow_redirects=False
    )
    assert replay.status_code == 403
    rejected = client.get("/api/health", headers={"Host": "evil.example"})
    assert rejected.status_code == 400
    cookie = client.cookies.get("lesr_session")
    assert cookie is not None


def test_csrf_origin_lock_and_capability_contract(tmp_path: Path) -> None:
    _, client, csrf = unlocked(tmp_path)
    missing = client.post("/api/maintenance/gc", json={})
    assert missing.status_code == 403
    foreign = client.post(
        "/api/maintenance/gc",
        json={},
        headers={"X-LESR-CSRF": csrf, "Origin": "https://evil.example"},
    )
    assert foreign.status_code == 403
    accepted = client.post("/api/maintenance/gc", json={}, headers={"X-LESR-CSRF": csrf})
    assert accepted.status_code == 200
    assert accepted.json()["dry_run"] is True
    capabilities = client.get("/api/capabilities").json()["capabilities"]
    assert all(not (item["mcp"] and item["access"] == "admin") for item in capabilities)


def test_ui_covers_product_workflow_and_uses_no_remote_assets(tmp_path: Path) -> None:
    _, client, _ = unlocked(tmp_path)
    page = client.get("/").text
    for panel in (
        "overview",
        "intake",
        "explore",
        "context",
        "workspace",
        "review",
        "baseline",
        "tasks",
        "maintenance",
        "audit",
    ):
        assert f'id="{panel}"' in page
    ordinary_page = page.split('<section class="panel audit-panel"', maxsplit=1)[0]
    assert "Configuration UID" not in ordinary_page
    assert "Delegation UID" not in ordinary_page
    assert "Canonical Commit" not in ordinary_page
    assert "package_hash" not in ordinary_page
    assert "Human Key" not in ordinary_page
    assert "不影响工程状态" not in ordinary_page
    assert "无需进入" not in ordinary_page
    assert "不会出现在" not in ordinary_page
    assert 'src="http' not in page.casefold()
    assert 'href="http' not in page.casefold()
    assert client.get("/static/lesr.css").status_code == 200
    assert client.get("/static/lesr.js").status_code == 200


def test_session_context_resolves_human_names_from_internal_identity(
    tmp_path: Path,
) -> None:
    product = bootstrap_public_product(tmp_path)
    runtime = LocalWebRuntime(
        product.domain.project,
        launch_token="session-context-token",
        signer_key_root=tmp_path / "keys",
        signer_password=product.signer_password,
    )
    client = TestClient(runtime.app)
    unlocked_response = client.get(
        "/unlock?token=session-context-token", follow_redirects=False
    )
    assert unlocked_response.status_code == 303
    context = client.get("/api/session-context").json()
    assert context["configurations"][0]["name"] == "public-product"
    assert context["actors"][0]["display_name"] == "Root owner"
    assert context["actors"][0]["delegation_uid"] == product.delegation_uid
    assert {item["value"] for item in context["content_types"]} == {
        "software_requirement",
        "software_design",
    }
    assert {item["value"] for item in context["task_types"]} == {
        "requirement_change",
        "test_design",
        "deviation_review",
    }
    assert "can_analysis" not in str(context)
    assert "mqtt_change" not in str(context)
    assert context["audit"]["canonical_commit"] == product.domain.base


def test_engineering_search_finds_working_drafts_by_partial_text(
    tmp_path: Path,
) -> None:
    _, client, csrf = unlocked(tmp_path)
    accepted = client.post(
        "/api/intake/accept",
        headers={"X-LESR-CSRF": csrf},
        json={
            "description": (
                "建立本地 GPU 管理器，读取 NVIDIA 显存并提供低显存启动参数。"
            ),
            "project_name": "gpu-lab-manager",
        },
    )
    assert accepted.status_code == 200
    by_text = client.get("/api/query", params={"text": "NVIDIA 显存"}).json()
    assert by_text["items"]
    assert by_text["items"][0]["workspace_draft"] is True
    assert by_text["items"][0]["resource_type"] == "working_copy"
    number_fragment = accepted.json()["human_keys"][0][:5]
    by_number = client.get("/api/query", params={"text": number_fragment}).json()
    assert by_number["items"]
    assert all(
        item["resource_type"] in {"revision", "working_copy"}
        for item in by_number["items"]
    )


def test_web_signing_refuses_caller_authored_package(tmp_path: Path) -> None:
    _, client, csrf = unlocked(tmp_path)
    response = client.post(
        "/api/sign",
        headers={"X-LESR-CSRF": csrf},
        json={
            "package_uid": "caller-authored",
            "actor_uid": "human",
            "key_uid": "key",
            "role": "technical",
            "human_confirm": True,
        },
    )
    assert response.status_code == 404


def test_signer_broker_is_one_shot_and_returns_only_public_attestation(
    tmp_path: Path,
) -> None:
    key_root = tmp_path / "keys"
    password = "correct horse battery staple"
    store = ApprovalKeyStore(key_root, password=password)
    trust = store.generate("human-reviewer", "Reviewer", ("technical",))
    approval = sign_once(
        tmp_path,
        trust,
        "technical",
        ApprovalPayload(
            package_hash=semantic_hash({"package": 1}),
            effective_model_hash=semantic_hash({"model": 1}),
            scope={"resource_uids": ["REQ-1"]},
            approval_type="review",
        ),
        key_root=key_root,
        password=password,
    )
    assert approval["resource_type"] == "approval_attestation"
    assert "private_key" not in str(approval)
    key_file = next(key_root.glob("*.json")).read_text(encoding="utf-8")
    assert "filesystem-user-only" not in key_file


def test_encrypted_fallback_rejects_wrong_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if __import__("os").name == "nt":
        pytest.skip("Windows uses DPAPI")
    monkeypatch.setattr("lesr.domain.approval._store_in_secret_service", lambda *_: False)
    root = tmp_path / "keys"
    store = ApprovalKeyStore(root, password="right-password")
    trust = store.generate("human", "Human", ("technical",))
    with pytest.raises(PermissionError, match="password"):
        ApprovalKeyStore(root, password="wrong-password").sign(
            trust,
            "technical",
            ApprovalPayload(
                package_hash=semantic_hash({"package": 1}),
                effective_model_hash=semantic_hash({"model": 1}),
                scope={"resource_uids": ["REQ-1"]},
                approval_type="review",
            ),
        )
