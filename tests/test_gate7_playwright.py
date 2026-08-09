from __future__ import annotations

import os
import socket
import time
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
            baseline_prepare.get_by_label("Configuration UID").fill(product.configuration_uid)
            baseline_prepare.get_by_label("Evaluation time").fill("2026-08-10T00:01:00Z")
            baseline_prepare.get_by_role("button", name="VALIDATE FROZEN STATE").click()
            page.locator("#sign-form").wait_for()
            sign_form.get_by_role("button", name="SIGN THROUGH ONE-SHOT BROKER").click()
            page.locator("#sign-output").get_by_text('"broker": "terminated"').wait_for()
            page.locator('button[data-panel="baseline"]').click()
            baseline_apply = page.locator("#baseline-apply-form")
            baseline_apply.get_by_label("Evaluation time").fill("2026-08-10T00:02:00Z")
            baseline_apply.get_by_role("button", name="ATOMIC BASELINE APPLY").click()
            expect(page.locator("#baseline-output")).to_contain_text(
                "baseline_uid", timeout=60_000
            )
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
