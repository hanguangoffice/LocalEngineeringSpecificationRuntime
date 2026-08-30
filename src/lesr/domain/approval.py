"""Ed25519-backed human approval bound to an immutable review package."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_der_private_key,
)
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

    def message(
        self,
        *,
        approval_uid: str,
        actor_uid: str,
        actor_role: str,
        issued_at: datetime,
        provenance_uid: str,
    ) -> bytes:
        expiry = (
            self.expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if self.expires_at
            else ""
        )
        conditions_hash = semantic_hash({"conditions": self.conditions})
        return (
            "LESR-APPROVAL-V1\n"
            f"{approval_uid}\n{actor_uid}\n{actor_role}\n"
            f"{issued_at.astimezone(UTC).isoformat().replace('+00:00', 'Z')}\n"
            f"{provenance_uid}\n{self.package_hash}\n{self.effective_model_hash}\n{self.scope_hash}\n"
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
    # Runtime 1.x persisted this derived value. Runtime 2 accepts and verifies it
    # when reading old Canonical State, but does not emit it for new approvals.
    scope_hash: str | None = Field(default=None, exclude=True, repr=False)
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
        if self.scope_hash is not None and self.scope_hash != semantic_hash(self.scope):
            raise ValueError("scope_hash is invalid")
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

    def signed_message(self) -> bytes:
        return self.signing_payload().message(
            approval_uid=self.approval_uid,
            actor_uid=self.actor_uid,
            actor_role=self.actor_role,
            issued_at=self.issued_at,
            provenance_uid=self.provenance_uid,
        )


class ApprovalKeyStore:
    """User-local private keys; only public trust records enter Canonical State."""

    def __init__(self, root: Path | None = None, password: str | None = None) -> None:
        self.root = root or user_config_path("lesr", appauthor=False) / "keys"
        configured = password or os.environ.get("LESR_KEY_PASSWORD")
        self._fallback_password = (
            configured.encode("utf-8")
            if configured is not None
            else secrets.token_bytes(32)
            if root is not None
            else None
        )

    def generate(self, actor_uid: str, display_name: str, roles: tuple[str, ...]) -> TrustedActor:
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
        private_der = private.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
        value: dict[str, str | int] = {
            "algorithm": "Ed25519",
            "actor_uid": actor_uid,
            "key_uid": trust.key_uid,
        }
        if os.name == "nt":
            value |= {
                "protection": "windows-dpapi-current-user",
                "protected_private_key": base64.b64encode(_protect_private_key(private_der)).decode(
                    "ascii"
                ),
            }
        elif _store_in_secret_service(trust.key_uid, private_der):
            value["protection"] = "secret-service"
        else:
            if self._fallback_password is None:
                raise PermissionError(
                    "Secret Service is unavailable; LESR_KEY_PASSWORD is required"
                )
            salt = secrets.token_bytes(16)
            nonce = secrets.token_bytes(12)
            key = _derive_scrypt(self._fallback_password, salt)
            value |= {
                "protection": "scrypt-aesgcm-pkcs8",
                "salt": base64.b64encode(salt).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "protected_private_key": base64.b64encode(
                    AESGCM(key).encrypt(nonce, private_der, trust.key_uid.encode("utf-8"))
                ).decode("ascii"),
                "scrypt_n": 1 << 15,
                "scrypt_r": 8,
                "scrypt_p": 1,
            }
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8", newline="\n")
        path.chmod(0o600)
        return trust

    def sign(self, trust: TrustedActor, role: str, payload: ApprovalPayload) -> SignedApproval:
        if role not in trust.roles:
            raise PermissionError(f"actor is not trusted for role: {role}")
        path = self.root / f"{trust.key_uid}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        private_der = self._unlock_private_key(value, trust.key_uid)
        loaded = load_der_private_key(private_der, password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise PermissionError("stored approval key is not Ed25519")
        private = loaded
        approval_uid = uuid7_candidate()
        provenance_uid = uuid7_candidate()
        issued_at = datetime.now(UTC)
        signature = private.sign(
            payload.message(
                approval_uid=approval_uid,
                actor_uid=trust.actor_uid,
                actor_role=role,
                issued_at=issued_at,
                provenance_uid=provenance_uid,
            )
        )
        return SignedApproval(
            approval_uid=approval_uid,
            package_hash=payload.package_hash,
            effective_model_hash=payload.effective_model_hash,
            scope=payload.scope,
            approval_type=payload.approval_type,
            actor_uid=trust.actor_uid,
            actor_role=role,
            issued_at=issued_at,
            expires_at=payload.expires_at,
            conditions=payload.conditions,
            key_uid=trust.key_uid,
            signature=base64.b64encode(signature).decode("ascii"),
            provenance_uid=provenance_uid,
        )

    def _unlock_private_key(self, value: dict[str, Any], key_uid: str) -> bytes:
        protection = str(value["protection"])
        if protection == "secret-service":
            private_der = _load_from_secret_service(key_uid)
            if private_der is None:
                raise PermissionError("Secret Service key is unavailable or locked")
            return private_der
        protected = base64.b64decode(value["protected_private_key"], validate=True)
        if protection == "windows-dpapi-current-user":
            return _unprotect_private_key(protected, protection)
        if protection == "scrypt-aesgcm-pkcs8":
            if self._fallback_password is None:
                raise PermissionError("password is required to unlock the private key")
            salt = base64.b64decode(value["salt"], validate=True)
            nonce = base64.b64decode(value["nonce"], validate=True)
            key = _derive_scrypt(self._fallback_password, salt)
            try:
                return AESGCM(key).decrypt(nonce, protected, key_uid.encode("utf-8"))
            except (InvalidTag, ValueError) as error:
                raise PermissionError("private key password is invalid") from error
        raise PermissionError("private key protection is unsupported")


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
    if (
        trust.revoked
        or instant < trust.valid_from
        or (trust.valid_to and instant >= trust.valid_to)
    ):
        raise PermissionError("approval key is not currently trusted")
    if approval.expires_at and instant >= approval.expires_at:
        raise PermissionError("approval has expired")
    if approval.issued_at > instant:
        raise PermissionError("approval was issued in the future")
    if approval.package_hash != package_hash:
        raise PermissionError("approval does not bind the review package")
    if approval.effective_model_hash != effective_model_hash:
        raise PermissionError("approval does not bind the effective model")
    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(trust.public_key, validate=True))
    try:
        public.verify(
            base64.b64decode(approval.signature, validate=True),
            approval.signed_message(),
        )
    except (InvalidSignature, ValueError) as error:
        raise PermissionError("approval signature is invalid") from error


def verify_bound_approval(
    approval: SignedApproval,
    trust: TrustedActor,
    *,
    package_hash: str,
    effective_model_hash: str,
    approval_type: str,
    scope: dict[str, object],
    allowed_roles: frozenset[str],
    revoked_approval_uids: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> None:
    """Verify signature, trust, time and the exact governed semantic subject."""

    if approval.approval_uid in revoked_approval_uids:
        raise PermissionError("approval has been revoked")
    verify_approval(
        approval,
        trust,
        package_hash=package_hash,
        effective_model_hash=effective_model_hash,
        now=now,
    )
    if approval.approval_type != approval_type:
        raise PermissionError("approval type does not match the governed action")
    if approval.actor_role not in allowed_roles:
        raise PermissionError("approval role is not authorized for the governed action")
    if approval.scope != scope:
        raise PermissionError("approval scope does not exactly bind the governed subject")


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
    crypt32 = _windows_library("crypt32")
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
        _windows_library("kernel32").LocalFree(output.pbData)
        del source_buffer


def _unprotect_private_key(value: bytes, protection: str) -> bytes:
    if protection != "windows-dpapi-current-user" or os.name != "nt":
        raise PermissionError("private key protection is unavailable for this user/platform")
    source, source_buffer = _blob(value)
    output = _DataBlob()
    crypt32 = _windows_library("crypt32")
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise PermissionError("Windows DPAPI could not unlock the LESR private key")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        _windows_library("kernel32").LocalFree(output.pbData)
        del source_buffer


def _windows_library(name: str) -> Any:
    loader = getattr(ctypes, "windll", None)
    if loader is None:
        raise OSError("Windows native library loader is unavailable")
    return getattr(loader, name)


def _derive_scrypt(password: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=1 << 15, r=8, p=1).derive(password)


def _store_in_secret_service(key_uid: str, private_der: bytes) -> bool:
    try:
        import keyring

        keyring.set_password(
            "lesr.approval", key_uid, base64.b64encode(private_der).decode("ascii")
        )
        return True
    except Exception:  # noqa: BLE001 - keyring backend exception types are not stable
        return False


def _load_from_secret_service(key_uid: str) -> bytes | None:
    try:
        import keyring

        value = keyring.get_password("lesr.approval", key_uid)
        return base64.b64decode(value, validate=True) if value else None
    except Exception:  # noqa: BLE001 - keyring backend exception types are not stable
        return None
