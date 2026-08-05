from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from threading import Thread

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from lesr.adapters.git import GitCanonicalRepository
from lesr.adapters.web import LocalWebRuntime
from lesr.application.contracts import InMemoryDomainService


@pytest.mark.playwright
def test_local_ui_resolve_context_and_lock_flow(tmp_path: Path) -> None:
    GitCanonicalRepository(tmp_path).initialize()
    runtime = LocalWebRuntime(
        tmp_path, InMemoryDomainService(), launch_token="playwright-token"
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
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.goto(f"http://127.0.0.1:{port}/unlock?token=playwright-token")
            page.get_by_role("heading", name="Engineering state, made accountable.").wait_for()
            page.locator('button[data-panel="explore"]').click()
            page.get_by_label("Structured query").fill("reconnect")
            page.get_by_role("button", name="QUERY").click()
            page.get_by_text("REQ-SW-0001").wait_for()
            page.locator('button[data-panel="context"]').click()
            page.get_by_label("Configuration UID").fill("CONFIG-1")
            page.get_by_label("Target UID").fill(
                "018f0000-0000-7000-8000-000000000001"
            )
            page.get_by_role("button", name="BUILD MANIFEST").click()
            page.get_by_text("complete_under_model").wait_for()
            page.get_by_role("button", name="LOCK SESSION").click()
            page.get_by_role("heading", name="LESR is locked").wait_for()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
