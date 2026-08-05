"""Ed25519-backed human approval bound to an immutable review package."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from platformdirs import user_config_path
from pydantic import Field, model_validator

from lesr.domain.semantic import FrozenModel, semantic_hash, uuid7_candidate


class ApprovalPayload(FrozenModel):
    package_hash: str
    effective_model_hash: str
    scope: dict[str, object]
    approval_type: str
    expires_at: datetime | None = None
    conditions: tuple[object, ...] = ()

    @property
    def scope_hash(self) -> str:
        return semantic_hash(self.scope)

    def message(self) -> bytes:
        expiry = (
            self.expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if self.expires_at
            else ""
        )
        conditions_hash = semantic_hash({"conditions": self.conditions})
        return (
            "LESR-APPROVAL-V1\n"
            f"{self.package_hash}\n{self.effective_model_hash}\n{self.scope_hash}\n"
            f"{self.approval_type}\n{conditions_hash}\n{expiry}"
        ).encode()


class TrustedActor(FrozenModel):
    schema_version: str = "1.0"
    resource_type: str = "trusted_actor"
    actor_uid: str
    actor_type: str = "human"
    display_name: str
    roles: tuple[str, ...]
    key_uid: str = Field(default_factory=uuid7_candidate)
    algorithm: str = "Ed25519"
    public_key: str
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None
    revoked_by_record_uid: str | None = None

    @property
    def revoked(self) -> bool:
        return self.revoked_by_record_uid is not None


class SignedApproval(FrozenModel):
    schema_version: str = "1.0"
    resource_type: str = "approval_attestation"
    approval_uid: str = Field(default_factory=uuid7_candidate)
    package_hash: str
    effective_model_hash: str
    scope: dict[str, object]
    scope_hash: str
    approval_type: str
    actor_uid: str
    actor_role: str
    actor_type: str = "human"
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    conditions: tuple[object, ...] = ()
    signature_algorithm: str = "Ed25519"
    key_uid: str
    signature: str
    provenance_uid: str = Field(default_factory=uuid7_candidate)

    @model_validator(mode="after")
    def human_only(self) -> SignedApproval:
        if self.actor_type != "human":
            raise ValueError("only a human actor can issue a formal approval")
        return self

    def signing_payload(self) -> ApprovalPayload:
        return ApprovalPayload(
            package_hash=self.package_hash,
            effective_model_hash=self.effective_model_hash,
            scope=self.scope,
            approval_type=self.approval_type,
            expires_at=self.expires_at,
            conditions=self.conditions,
        )


class ApprovalKeyStore:
    """User-local private keys; only public trust records enter Canonical State."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or user_config_path("lesr", appauthor=False) / "keys"

    def generate(
        self, actor_uid: str, display_name: str, roles: tuple[str, ...]
    ) -> TrustedActor:
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        trust = TrustedActor(
            actor_uid=actor_uid,
            display_name=display_name,
            roles=roles,
            public_key=base64.b64encode(public).decode("ascii"),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{trust.key_uid}.json"
        value = {
            "algorithm": "Ed25519",
            "actor_uid": actor_uid,
            "key_uid": trust.key_uid,
            "protection": "windows-dpapi-current-user" if os.name == "nt" else "filesystem-user-only",
            "protected_private_key": base64.b64encode(
                _protect_private_key(private.private_bytes_raw())
            ).decode("ascii"),
        }
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8", newline="\n")
        path.chmod(0o600)
        return trust

    def sign(
        self, trust: TrustedActor, role: str, payload: ApprovalPayload
    ) -> SignedApproval:
        if role not in trust.roles:
            raise PermissionError(f"actor is not trusted for role: {role}")
        path = self.root / f"{trust.key_uid}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        private = Ed25519PrivateKey.from_private_bytes(
            _unprotect_private_key(
                base64.b64decode(value["protected_private_key"], validate=True),
                str(value["protection"]),
            )
        )
        signature = private.sign(payload.message())
        return SignedApproval(
            package_hash=payload.package_hash,
            effective_model_hash=payload.effective_model_hash,
            scope=payload.scope,
            scope_hash=payload.scope_hash,
            approval_type=payload.approval_type,
            actor_uid=trust.actor_uid,
            actor_role=role,
            expires_at=payload.expires_at,
            conditions=payload.conditions,
            key_uid=trust.key_uid,
            signature=base64.b64encode(signature).decode("ascii"),
        )


def verify_approval(
    approval: SignedApproval,
    trust: TrustedActor,
    *,
    package_hash: str,
    effective_model_hash: str,
    now: datetime | None = None,
) -> None:
    instant = now or datetime.now(UTC)
    if approval.actor_uid != trust.actor_uid or approval.key_uid != trust.key_uid:
        raise PermissionError("approval actor/key does not match the trust record")
    if approval.actor_role not in trust.roles:
        raise PermissionError("approval role is not trusted")
    if trust.revoked or instant < trust.valid_from or (trust.valid_to and instant >= trust.valid_to):
        raise PermissionError("approval key is not currently trusted")
    if approval.expires_at and instant >= approval.expires_at:
        raise PermissionError("approval has expired")
    if approval.package_hash != package_hash:
        raise PermissionError("approval does not bind the review package")
    if approval.effective_model_hash != effective_model_hash:
        raise PermissionError("approval does not bind the effective model")
    if approval.scope_hash != semantic_hash(approval.scope):
        raise PermissionError("approval scope hash is invalid")
    public = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(trust.public_key, validate=True)
    )
    try:
        public.verify(
            base64.b64decode(approval.signature, validate=True),
            approval.signing_payload().message(),
        )
    except (InvalidSignature, ValueError) as error:
        raise PermissionError("approval signature is invalid") from error


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(value)
    return (
        _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))),
        buffer,
    )


def _protect_private_key(value: bytes) -> bytes:
    if os.name != "nt":
        return value
    source, source_buffer = _blob(value)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "LESR Ed25519 private key",
        None,
        None,
        None,
        0,
        ctypes.byref(output),
    ):
        raise OSError("Windows DPAPI could not protect the LESR private key")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer


def _unprotect_private_key(value: bytes, protection: str) -> bytes:
    if protection == "filesystem-user-only":
        if os.name == "nt":
            raise PermissionError("unprotected private key is forbidden on Windows")
        return value
    if protection != "windows-dpapi-current-user" or os.name != "nt":
        raise PermissionError("private key protection is unavailable for this user/platform")
    source, source_buffer = _blob(value)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise PermissionError("Windows DPAPI could not unlock the LESR private key")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer
