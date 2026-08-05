"""Short-lived human-only Signer Broker over a local named endpoint."""

from __future__ import annotations

import multiprocessing
import os
import secrets
import tempfile
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any

from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload, TrustedActor
from lesr.domain.semantic import uuid7_candidate


def sign_once(
    project: Path,
    trust: TrustedActor,
    role: str,
    payload: ApprovalPayload,
    *,
    key_root: Path | None = None,
    password: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Spawn, challenge, use and destroy a broker for exactly one signature."""

    challenge = secrets.token_bytes(32)
    uid = uuid7_candidate().replace("-", "")
    family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
    address = (
        rf"\\.\pipe\lesr-signer-{uid}"
        if os.name == "nt"
        else str(Path(tempfile.gettempdir()) / f"lesr-{uid}.sock")
    )
    if os.name != "nt":
        Path(address).parent.mkdir(parents=True, exist_ok=True)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(
        target=_broker,
        args=(
            address,
            family,
            challenge,
            ready,
            str(key_root) if key_root else None,
            password,
        ),
        daemon=True,
    )
    process.start()
    if not ready.wait(timeout_seconds):
        process.terminate()
        raise TimeoutError("Signer Broker did not become ready")
    connection = Client(address, family=family, authkey=challenge)
    try:
        connection.send(
            {
                "challenge": challenge.hex(),
                "trust": trust.model_dump(mode="json"),
                "role": role,
                "payload": payload.model_dump(mode="json"),
            }
        )
        response = connection.recv()
    finally:
        connection.close()
        process.join(timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(2)
        if os.name != "nt":
            Path(address).unlink(missing_ok=True)
    if not isinstance(response, dict):
        raise TypeError("Signer Broker returned an invalid response")
    if response.get("ok") is not True:
        raise PermissionError(str(response.get("error", "Signer Broker refused request")))
    value = response.get("approval")
    if not isinstance(value, dict):
        raise TypeError("Signer Broker omitted approval")
    return value


def _broker(
    address: str,
    family: str,
    challenge: bytes,
    ready: Any,
    key_root: str | None,
    password: str | None,
) -> None:
    listener = Listener(address, family=family, authkey=challenge)
    if family == "AF_UNIX":
        os.chmod(address, 0o600)
    ready.set()
    connection = listener.accept()
    try:
        request = connection.recv()
        if not isinstance(request, dict) or request.get("challenge") != challenge.hex():
            connection.send({"ok": False, "error": "challenge mismatch"})
            return
        trust = TrustedActor.model_validate(request["trust"])
        payload = ApprovalPayload.model_validate(request["payload"])
        approval = ApprovalKeyStore(Path(key_root) if key_root else None, password=password).sign(
            trust, str(request["role"]), payload
        )
        connection.send({"ok": True, "approval": approval.model_dump(mode="json")})
    except (KeyError, PermissionError, ValueError) as error:
        connection.send({"ok": False, "error": str(error)})
    finally:
        connection.close()
        listener.close()
        time.sleep(0.01)
