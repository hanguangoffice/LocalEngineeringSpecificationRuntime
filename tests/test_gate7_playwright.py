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
            page.goto(f"http://127.0.0.1:{port}/unlock?token=playwright-token")
            page.get_by_role("heading", name="Engineering state, made accountable.").wait_for()
            assert page.evaluate("window.__LESR_MOTION__.engine") == "GSAP"
            assert page.evaluate("window.gsap.version") == "3.15.0"
            expect(page.locator(".flow-step").first).to_be_visible()
            page.locator('button[data-panel="explore"]').click()
            page.get_by_label("Structured query").fill("no-synthetic-result")
            page.get_by_role("button", name="QUERY").click()
            page.get_by_text("No exact matches.").wait_for()
            page.get_by_role("button", name="LOCK SESSION").click()
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
            expect(page.locator(".flow-step")).to_have_count(6)
            page.locator('button[data-panel="workspace"]').click()
            expect(page.locator("#workspace")).to_be_visible()
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
            open_form = page.locator("#workspace-open-form")
            open_form.get_by_label("Configuration UID").fill(product.configuration_uid)
            open_form.get_by_label("Actor UID").fill(product.actor_uid)
            open_form.get_by_label("Delegation UID").fill(product.delegation_uid)
            open_form.get_by_role("button", name="OPEN ISOLATED WORKSPACE").click()
            page.get_by_text("EDITABLE", exact=True).wait_for()

            edit_form = page.locator("#workspace-edit-form")
            edit_form.get_by_label("Human Key").fill("DES-WEB-1")
            edit_form.get_by_label("Kind").fill("software_design")
            edit_form.get_by_label("Statement / body").fill(
                "The controller shall publish a deterministic state frame."
            )
            edit_form.get_by_role("button", name="CREATE WORKING COPY").click()
            page.locator("#workspace-output").get_by_text("DES-WEB-1").wait_for()

            submit_form = page.locator("#workspace-submit-form")
            submit_form.get_by_label("Evaluation time").fill("2026-08-10T00:00:00Z")
            submit_form.get_by_role("button", name="FREEZE CANDIDATE").click()
            page.locator("#sign-form").wait_for()
            page.locator("#sign-package").get_by_text("sha256:").wait_for()
            candidate_package_hash = page.locator("#sign-package").text_content()

            sign_form = page.locator("#sign-form")
            sign_form.get_by_placeholder("Reviewer Actor UID").fill(product.actor_uid)
            sign_form.get_by_placeholder("Trusted Key UID").fill(product.trust.key_uid)
            sign_form.get_by_placeholder("Profile-required role").fill("technical")
            sign_form.get_by_role("checkbox").check()
            sign_form.get_by_role("button", name="SIGN THROUGH ONE-SHOT BROKER").click()
            page.locator("#sign-output").get_by_text('"broker": "terminated"').wait_for()
            page.get_by_role("button", name="ATOMIC APPLY CANDIDATE").click()
            expect(page.locator("#sign-output")).to_contain_text(
                "result_commit", timeout=60_000
            )

            baseline_prepare = page.locator("#baseline-prepare-form")
            result_configuration_uid = baseline_prepare.get_by_label(
                "Configuration UID"
            ).input_value()
            assert result_configuration_uid != product.configuration_uid
            baseline_prepare.get_by_label("Evaluation time").fill(
                datetime.now(UTC).isoformat()
            )
            baseline_prepare.get_by_role("button", name="VALIDATE FROZEN STATE").click()
            page.locator("#sign-form").wait_for()
            page.wait_for_function(
                "previous => document.querySelector('#sign-package').textContent !== previous",
                arg=candidate_package_hash,
            )
            baseline_package_hash = page.locator("#sign-package").text_content()
            sign_form.get_by_role("button", name="SIGN THROUGH ONE-SHOT BROKER").click()
            expect(page.locator("#sign-output")).to_contain_text(
                baseline_package_hash, timeout=60_000
            )
            page.locator('button[data-panel="baseline"]').click()
            baseline_apply = page.locator("#baseline-apply-form")
            baseline_apply.get_by_label("Evaluation time").fill(
                datetime.now(UTC).isoformat()
            )
            baseline_apply.get_by_role("button", name="ATOMIC BASELINE APPLY").click()
            expect(page.locator("#baseline-output")).to_contain_text(
                "result_commit", timeout=60_000
            )
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
