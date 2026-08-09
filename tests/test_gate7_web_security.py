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
        "explore",
        "context",
        "workspace",
        "review",
        "baseline",
        "tasks",
        "maintenance",
    ):
        assert f'id="{panel}"' in page
    assert 'src="http' not in page.casefold()
    assert 'href="http' not in page.casefold()
    assert client.get("/static/lesr.css").status_code == 200
    assert client.get("/static/lesr.js").status_code == 200


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
