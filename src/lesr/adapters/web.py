"""Loopback-only FastAPI adapter for the LESR local product."""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.base import RequestResponseEndpoint

from lesr.adapters.git import GitCanonicalRepository, IntegrityError
from lesr.adapters.markdown import preview_markdown
from lesr.adapters.operations import RepositoryMaintenance, TaskStore
from lesr.adapters.pdf_import import preview_pdf
from lesr.adapters.signer import sign_once
from lesr.application.contracts import LESRDomainPort, RiskClass, WriteEnvelope
from lesr.application.runtime import LocalRuntimeService
from lesr.domain.approval import ApprovalPayload, TrustedActor
from lesr.domain.catalog import CAPABILITIES, RUNTIME_CONTRACT_VERSION
from lesr.domain.semantic import SemanticField, uuid7_candidate
from lesr.domain.workspace import WorkingCopy
from lesr.intake.bootstrap import IntakeBootstrapper
from lesr.intake.models import IntakeRequest
from lesr.intake.service import IntakeService

SESSION_COOKIE = "lesr_session"
SESSION_IDLE = timedelta(minutes=15)


@dataclass(slots=True)
class WebSession:
    csrf_token: str
    last_seen: datetime


class ContextRequest(BaseModel):
    configuration_uid: str = Field(min_length=1)
    target_uid: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    evaluation_time: str = Field(min_length=1)


class SignRequest(BaseModel):
    package_uid: str = Field(min_length=1)
    actor_uid: str = Field(min_length=1)
    key_uid: str = Field(min_length=1)
    role: str = Field(min_length=1)
    human_confirm: bool


class IntakeAcceptRequest(IntakeRequest):
    display_name: str = Field(default="本机工程所有者", min_length=1, max_length=120)


class IntakeFileRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_base64: str = Field(min_length=1, max_length=14_000_000)
    project_name: str | None = Field(default=None, max_length=120)
    known_repository: str | None = Field(default=None, max_length=1024)


class WebWriteRequest(BaseModel):
    workspace_uid: str = Field(min_length=1)
    expected_base: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    delegation_uid: str = Field(min_length=1)
    dry_run: bool = False
    risk_class: RiskClass
    operation: dict[str, Any]

    def envelope(self) -> WriteEnvelope:
        return WriteEnvelope(
            self.workspace_uid,
            self.expected_base,
            self.idempotency_key,
            self.actor,
            self.delegation_uid,
            self.dry_run,
            self.risk_class,
            self.operation,
        )


class LocalWebRuntime:
    def __init__(
        self,
        project: Path,
        domain: LESRDomainPort | None = None,
        *,
        launch_token: str | None = None,
        signer_key_root: Path | None = None,
        signer_password: str | None = None,
    ) -> None:
        self.project = project.resolve()
        self.domain = domain or LocalRuntimeService(self.project)
        self.launch_token = launch_token or secrets.token_urlsafe(32)
        self.launch_token_available = True
        self.signer_key_root = signer_key_root
        self.signer_password = signer_password
        self.sessions: dict[str, WebSession] = {}
        self.app = FastAPI(
            title="LESR Local Runtime",
            version=RUNTIME_CONTRACT_VERSION,
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )
        web_root = Path(str(files("lesr.web")))
        self.templates = Jinja2Templates(directory=web_root / "templates")
        self.app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")
        self._routes()

    def _routes(self) -> None:
        app = self.app

        @app.middleware("http")
        async def security_boundary(
            request: Request, call_next: RequestResponseEndpoint
        ) -> Response:
            host = request.headers.get("host", "").split(":", 1)[0].casefold()
            if host not in {"127.0.0.1", "localhost", "testserver"}:
                return Response("Host rejected", status_code=400)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if origin is not None:
                    parsed_origin = urlsplit(origin)
                    if parsed_origin.scheme != "http" or parsed_origin.hostname not in {
                        "127.0.0.1",
                        "localhost",
                        "testserver",
                    }:
                        return Response("Origin rejected", status_code=403)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            return response

        @app.get("/unlock", response_class=RedirectResponse)
        async def unlock(token: str) -> RedirectResponse:
            if not self.launch_token_available or not secrets.compare_digest(
                token, self.launch_token
            ):
                raise HTTPException(status_code=403, detail="launch token is invalid or spent")
            self.launch_token_available = False
            session_uid = secrets.token_urlsafe(32)
            self.sessions[session_uid] = WebSession(
                csrf_token=secrets.token_urlsafe(24), last_seen=datetime.now(UTC)
            )
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(
                SESSION_COOKIE,
                session_uid,
                httponly=True,
                samesite="strict",
                secure=False,
                max_age=900,
                path="/",
            )
            return response

        @app.get("/locked", response_class=HTMLResponse)
        async def locked() -> HTMLResponse:
            return HTMLResponse(
                "<main><h1>LESR is locked</h1><p>Restart the local UI to obtain a new "
                "one-time launch token.</p></main>",
                status_code=401,
            )

        @app.get("/", response_class=HTMLResponse)
        async def index(request: Request) -> HTMLResponse:
            session = self._session(request)
            commit = self._canonical_commit()
            return self.templates.TemplateResponse(
                request=request,
                name="index.html",
                context={
                    "csrf_token": session.csrf_token,
                    "short_commit": commit[:12],
                    "canonical_commit": commit,
                },
            )

        @app.get("/api/health")
        async def health(request: Request) -> dict[str, Any]:
            self._session(request)
            repository = GitCanonicalRepository(self.project)
            try:
                commit = repository.current_commit()
                repository.require_v1_manifest(commit)
                authority = "healthy"
                canonical = "VERIFIED"
                manifest = "1.0 / VALID"
            except (IntegrityError, RuntimeError):
                authority = "degraded"
                canonical = "FAILED"
                manifest = "INVALID"
            database = self.project / ".lesr" / "projection.sqlite3"
            return {
                "authority": authority,
                "canonical": canonical,
                "manifest": manifest,
                "projection": "READY" if database.exists() else "REBUILDABLE",
                "open_workspaces": len(getattr(self.domain, "workspaces", {})),
            }

        @app.get("/api/capabilities")
        async def capabilities(request: Request) -> dict[str, Any]:
            self._session(request)
            return {
                "contract_version": RUNTIME_CONTRACT_VERSION,
                "capabilities": [item.model_dump(mode="json") for item in CAPABILITIES],
            }

        @app.get("/api/session-context")
        async def session_context(request: Request) -> dict[str, Any]:
            self._session(request)
            return self._session_context()

        @app.get("/api/intake/templates")
        async def intake_templates(request: Request) -> dict[str, Any]:
            self._session(request)
            service = IntakeService()
            return {"templates": service.templates()}

        @app.post("/api/intake/analyze")
        async def intake_analyze(request: Request, value: IntakeRequest) -> dict[str, Any]:
            self._mutation_session(request)
            return IntakeService().analyze(value).model_dump(mode="json")

        @app.post("/api/intake/import-preview")
        async def intake_import_preview(
            request: Request, value: IntakeFileRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._preview_intake_file(value)

        @app.post("/api/intake/accept")
        async def intake_accept(
            request: Request, value: IntakeAcceptRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._accept_intake(value)

        @app.get("/api/query")
        async def query(
            request: Request, text: str = "", kind: str = ""
        ) -> dict[str, Any]:
            self._session(request)
            canonical_items, canonical_total = GitCanonicalRepository(
                self.project
            ).query_projection(
                self.project / ".lesr" / "projection.sqlite3",
                kind=kind or None,
                text=text or None,
                offset=0,
                page_size=50,
                resource_type="revision",
            )
            draft_items = self._matching_working_copies(text=text, kind=kind)
            items: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in (*draft_items, *canonical_items):
                identity = str(
                    item.get("object_uid")
                    or item.get("revision_uid")
                    or item.get("uid")
                    or item.get("human_key")
                    or ""
                )
                if identity and identity in seen:
                    continue
                if identity:
                    seen.add(identity)
                items.append(item)
                if len(items) >= 50:
                    break
            return {
                "items": items,
                "total": canonical_total + len(draft_items),
                "draft_count": len(draft_items),
                "next_cursor": None,
            }

        @app.get("/api/review-package/{package_uid}")
        async def review_package(request: Request, package_uid: str) -> dict[str, Any]:
            self._session(request)
            package = self._review_package(package_uid)
            if package is None:
                raise HTTPException(status_code=404, detail="Canonical Review Package not found")
            scope_items = self._human_scope(
                tuple(package.get("candidate_scope", ())),
                workspace_uid=str(package.get("workspace_uid", "")),
            )
            evidence = getattr(self.domain, "review_evidence", {}).get(package_uid, {})
            validation = evidence.get("validation", {}) if isinstance(evidence, dict) else {}
            decision = (
                validation.get("operation_decision", {})
                if isinstance(validation, dict)
                else {}
            )
            finding_count = len(validation.get("findings", ())) if isinstance(validation, dict) else 0
            blocking_count = (
                len(decision.get("blocking_finding_uids", ()))
                if isinstance(decision, dict)
                else 0
            )
            return {
                "package_uid": package_uid,
                "package_hash": package.get("package_hash"),
                "effective_model_hash": package.get("effective_model_hash"),
                "candidate_scope": package.get("candidate_scope", []),
                "scope_items": scope_items,
                "change_count": len(scope_items),
                "finding_count": finding_count,
                "blocking_count": blocking_count,
                "approval_reason": (
                    f"批准 {len(scope_items)} 项工程变更；"
                    f"校验发现 {finding_count} 项，阻断项 {blocking_count} 项。"
                ),
                "stages": package.get("review_policy", {}).get("stages", []),
                "conditions": package.get("approval_conditions", []),
                "signature_expiry_minutes": 15,
            }

        @app.post("/api/context/plan")
        async def context_plan(request: Request, value: ContextRequest) -> dict[str, Any]:
            self._mutation_session(request)
            result = self.domain.build_context(
                value.task_type,
                (value.target_uid,),
                4096,
                value.configuration_uid,
                "local-web-user",
                value.evaluation_time,
            ).payload()
            context = self._value_or_error(result)
            context["mandatory_items"] = self._human_scope(
                tuple(context.get("mandatory", ())), workspace_uid=""
            )
            context["supporting_items"] = self._human_scope(
                tuple(context.get("supporting", ())), workspace_uid=""
            )
            return context

        @app.post("/api/workspace/open")
        async def workspace_open(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._value_or_error(self.domain.open_workspace(value.envelope()).payload())

        @app.post("/api/workspace/edit")
        async def workspace_edit(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._value_or_error(
                self.domain.propose_operation(value.envelope()).payload()
            )

        @app.post("/api/workspace/submit")
        async def workspace_submit(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._value_or_error(self.domain.prepare_review(value.envelope()).payload())

        @app.post("/api/workspace/rebase")
        async def workspace_rebase(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._runtime_write("rebase_workspace", value, "workspace.rebase")

        @app.post("/api/workspace/merge")
        async def workspace_merge(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._runtime_write("merge_workspace", value, "workspace.merge")

        @app.post("/api/workspace/resolve")
        async def workspace_resolve(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._runtime_write(
                "resolve_merge_conflict", value, "workspace.resolve"
            )

        @app.post("/api/review/comment")
        async def review_comment(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._runtime_write("add_review_comment", value, "review.comment")

        @app.post("/api/review/record/{record_type}")
        async def review_record(
            request: Request, record_type: str, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            methods = {
                "resolution": ("resolve_review_comment", "review.resolve"),
                "condition": ("satisfy_review_condition", "review.condition"),
                "revocation": ("revoke_approval", "review.revoke"),
            }
            selected = methods.get(record_type)
            if selected is None:
                raise HTTPException(status_code=404, detail="review record type unavailable")
            return self._runtime_write(selected[0], value, selected[1])

        @app.post("/api/reconciliation/open")
        async def reconciliation_open(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            return self._runtime_write(
                "begin_reconciliation", value, "reconciliation.open"
            )

        @app.post("/api/apply")
        async def apply(request: Request, value: WebWriteRequest) -> dict[str, Any]:
            self._mutation_session(request)
            return self._value_or_error(
                self.domain.apply_transaction(value.envelope()).payload()
            )

        @app.post("/api/baseline/prepare")
        async def baseline_prepare(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            capability = getattr(self.domain, "prepare_baseline", None)
            if not callable(capability):
                raise HTTPException(status_code=404, detail="baseline.prepare unavailable")
            return self._value_or_error(capability(value.envelope()).payload())

        @app.post("/api/baseline/apply")
        async def baseline_apply(
            request: Request, value: WebWriteRequest
        ) -> dict[str, Any]:
            self._mutation_session(request)
            capability = getattr(self.domain, "apply_baseline", None)
            if not callable(capability):
                raise HTTPException(status_code=404, detail="baseline.apply unavailable")
            return self._value_or_error(capability(value.envelope()).payload())

        @app.get("/api/tasks")
        async def tasks(request: Request) -> list[dict[str, Any]]:
            self._session(request)
            return [item.model_dump(mode="json") for item in TaskStore(self.project).list()]

        @app.post("/api/maintenance/gc")
        async def gc_plan(request: Request) -> dict[str, Any]:
            self._mutation_session(request)
            return RepositoryMaintenance(self.project).workspace_gc(dry_run=True)

        @app.post("/api/sign")
        async def sign(request: Request, value: SignRequest) -> dict[str, Any]:
            self._mutation_session(request)
            if not value.human_confirm:
                raise HTTPException(status_code=403, detail="explicit human confirmation required")
            package, trust = self._signing_resources(
                value.package_uid, value.actor_uid, value.key_uid
            )
            matching_stages = [
                stage
                for stage in package.get("review_policy", {}).get("stages", ())
                if isinstance(stage, dict) and stage.get("role") == value.role
            ]
            if len(matching_stages) != 1:
                raise HTTPException(
                    status_code=409,
                    detail="requested role does not identify exactly one review stage",
                )
            payload = ApprovalPayload(
                package_hash=str(package["package_hash"]),
                effective_model_hash=str(package["effective_model_hash"]),
                scope={"resource_uids": list(package["candidate_scope"])},
                approval_type=str(matching_stages[0]["stage"]),
                expires_at=(datetime.now(UTC) + timedelta(minutes=15)),
                conditions=tuple(package.get("approval_conditions", ())),
            )
            approval = sign_once(
                self.project,
                trust,
                value.role,
                payload,
                key_root=self.signer_key_root,
                password=self.signer_password,
            )
            return {
                "approval": approval,
                "broker": "terminated",
                "human_confirmation": True,
            }

        @app.post("/api/lock")
        async def lock(request: Request) -> dict[str, bool]:
            session_uid = request.cookies.get(SESSION_COOKIE)
            self._mutation_session(request)
            if session_uid:
                self.sessions.pop(session_uid, None)
            return {"locked": True}

    def _session(self, request: Request) -> WebSession:
        session_uid = request.cookies.get(SESSION_COOKIE)
        session = self.sessions.get(session_uid or "")
        now = datetime.now(UTC)
        if session is None or now - session.last_seen >= SESSION_IDLE:
            if session_uid:
                self.sessions.pop(session_uid, None)
            raise HTTPException(status_code=401, detail="session is locked")
        session.last_seen = now
        return session

    def _runtime_write(
        self, method_name: str, value: WebWriteRequest, capability: str
    ) -> dict[str, Any]:
        method = getattr(self.domain, method_name, None)
        if not callable(method):
            raise HTTPException(status_code=404, detail=f"{capability} unavailable")
        return self._value_or_error(method(value.envelope()).payload())

    def _mutation_session(self, request: Request) -> WebSession:
        session = self._session(request)
        supplied = request.headers.get("x-lesr-csrf", "")
        if not secrets.compare_digest(supplied, session.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF token is invalid")
        return session

    def _canonical_commit(self) -> str:
        try:
            return GitCanonicalRepository(self.project).current_commit()
        except RuntimeError:
            return "uninitialized"

    @staticmethod
    def _kind_label(kind: str) -> str:
        labels = {
            "software_requirement": "软件需求",
            "software_design": "软件设计",
            "test_case": "测试用例",
            "test_procedure": "测试规程",
            "test_result": "测试结果",
            "interface_definition": "接口定义",
            "architecture_decision": "架构决策",
            "risk": "工程风险",
            "evidence": "工程证据",
        }
        return labels.get(kind, kind.replace("_", " ").strip().title())

    @staticmethod
    def _kind_prefix(kind: str) -> str:
        known = {
            "software_requirement": "REQ-SW",
            "software_design": "DES-SW",
            "test_case": "TEST",
            "test_procedure": "TEST-PROC",
            "test_result": "TEST-RESULT",
            "interface_definition": "IF",
            "architecture_decision": "ADR",
            "risk": "RISK",
            "evidence": "EVID",
        }
        if kind in known:
            return known[kind]
        parts = tuple(part for part in kind.split("_") if part)
        return "-".join(part[:4].upper() for part in parts[:2]) or "ITEM"

    def _matching_working_copies(
        self, *, text: str, kind: str
    ) -> tuple[dict[str, Any], ...]:
        workspaces = getattr(self.domain, "workspaces", {})
        if not isinstance(workspaces, dict):
            return ()
        terms = tuple(
            item.casefold()
            for item in re.split(r"[^\w.-]+", text, flags=re.UNICODE)
            if item
        )
        matches: list[dict[str, Any]] = []
        for workspace in workspaces.values():
            workspace_state = getattr(getattr(workspace, "state", None), "value", None)
            if workspace_state != "editable":
                continue
            copies = getattr(workspace, "working_copies", ())
            for working_copy in copies:
                item = working_copy.model_dump(mode="json")
                if kind and item.get("kind") != kind:
                    continue
                searchable = json.dumps(item, ensure_ascii=False).casefold()
                if terms and not all(term in searchable for term in terms):
                    continue
                item["fields"] = item.get("draft_fields", [])
                item["workspace_draft"] = True
                matches.append(item)
        return tuple(
            sorted(
                matches,
                key=lambda item: str(item.get("human_key", "")).casefold(),
            )
        )

    def _session_context(self) -> dict[str, Any]:
        repository = GitCanonicalRepository(self.project)
        commit = repository.current_commit()
        documents = tuple(value for _, value in repository.documents(commit))
        configurations = sorted(
            (
                value
                for value in documents
                if value.get("resource_type") == "configuration_snapshot"
            ),
            key=lambda value: (
                str(value.get("created_at", "")),
                str(value.get("configuration_uid", "")),
            ),
            reverse=True,
        )
        delegations = tuple(
            value
            for value in documents
            if value.get("resource_type") == "delegation_grant"
            and not value.get("stop_conditions")
        )
        actors: list[dict[str, Any]] = []
        for value in documents:
            if value.get("resource_type") != "trusted_actor" or value.get(
                "revoked_by_record_uid"
            ):
                continue
            actor_uid = str(value.get("actor_uid", ""))
            delegation = next(
                (
                    item
                    for item in delegations
                    if item.get("principal_uid") == actor_uid
                ),
                None,
            )
            actors.append(
                {
                    "display_name": value.get("display_name") or "本机用户",
                    "roles": value.get("roles", []),
                    "actor_uid": actor_uid,
                    "key_uid": value.get("key_uid"),
                    "delegation_uid": (
                        delegation.get("delegation_uid") if delegation is not None else None
                    ),
                }
            )
        kinds_by_name: dict[str, dict[str, str]] = {}
        for value in documents:
            if value.get("resource_type") != "kind_definition_revision":
                continue
            name = str(value.get("name", "")).strip()
            if not name:
                continue
            kinds_by_name[name] = {
                "value": name,
                "name": self._kind_label(name),
            }
        human_keys = {
            str(value.get("human_key"))
            for value in documents
            if value.get("human_key")
        }
        for item in self._matching_working_copies(text="", kind=""):
            if item.get("human_key"):
                human_keys.add(str(item["human_key"]))
        key_suggestions: dict[str, str] = {}
        for name in kinds_by_name:
            prefix = self._kind_prefix(name)
            pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
            numbers = [
                int(match.group(1))
                for key in human_keys
                if (match := pattern.fullmatch(key)) is not None
            ]
            key_suggestions[name] = f"{prefix}-{max(numbers, default=0) + 1:04d}"
        return {
            "project_name": self.project.name,
            "configurations": [
                {
                    "name": self._configuration_name(value, index),
                    "configuration_uid": value.get("configuration_uid"),
                    "closure_status": value.get("closure_status", "unknown"),
                    "change_count": len(value.get("revision_uids", ())),
                    "variant": value.get("variant"),
                }
                for index, value in enumerate(configurations, 1)
            ],
            "actors": sorted(actors, key=lambda item: str(item["display_name"]).casefold()),
            "content_types": sorted(
                kinds_by_name.values(), key=lambda item: item["name"].casefold()
            ),
            "key_suggestions": key_suggestions,
            "task_types": [
                {"value": "requirement_change", "name": "修改或补充工程内容"},
                {"value": "test_design", "name": "设计验证"},
                {"value": "deviation_review", "name": "评审变更或偏离"},
            ],
            "audit": {
                "canonical_commit": commit,
                "repository_format": "1.0",
                "runtime_contract": RUNTIME_CONTRACT_VERSION,
                "capability_count": len(CAPABILITIES),
            },
        }

    def _accept_intake(self, value: IntakeAcceptRequest) -> dict[str, Any]:
        if not isinstance(self.domain, LocalRuntimeService):
            raise HTTPException(status_code=404, detail="zero-spec intake is unavailable")
        analysis = IntakeService().analyze(
            IntakeRequest(
                description=value.description,
                project_name=value.project_name,
                known_repository=value.known_repository,
            )
        )
        runtime = self.domain
        try:
            identity = IntakeBootstrapper(
                runtime,
                key_root=self.signer_key_root,
                key_password=self.signer_password,
            ).ensure(value.display_name)
            workspace_uid = uuid7_candidate()
            actor_uid = str(identity["actor_uid"])
            delegation_uid = str(identity["delegation_uid"])
            configuration_uid = str(identity["configuration_uid"])
            opened = runtime.open_workspace(
                WriteEnvelope(
                    workspace_uid=workspace_uid,
                    expected_base=runtime.base,
                    idempotency_key=uuid7_candidate(),
                    actor=actor_uid,
                    delegation_uid=delegation_uid,
                    dry_run=False,
                    risk_class=RiskClass.MEDIUM,
                    operation={
                        "type": "open_workspace",
                        "configuration_uid": configuration_uid,
                    },
                )
            )
            if not opened.ok:
                assert opened.error is not None
                raise RuntimeError(opened.error.message)
            for requirement in analysis.requirements[:100]:
                object_uid = uuid7_candidate()
                working_copy = WorkingCopy(
                    workspace_uid=workspace_uid,
                    object_uid=object_uid,
                    base_revision_uid=None,
                    human_key=requirement.human_key,
                    kind="software_requirement",
                    effective_model_hash=runtime.workspaces[workspace_uid].effective_model_hash,
                    delegation_uid=delegation_uid,
                    draft_fields=(
                        SemanticField(path="/statement", value=requirement.statement),
                    ),
                )
                proposed = runtime.propose_operation(
                    WriteEnvelope(
                        workspace_uid=workspace_uid,
                        expected_base=runtime.base,
                        idempotency_key=uuid7_candidate(),
                        actor=actor_uid,
                        delegation_uid=delegation_uid,
                        dry_run=False,
                        risk_class=RiskClass.MEDIUM,
                        operation={
                            "operation_type": "create_object",
                            "working_copy": working_copy.model_dump(mode="json"),
                        },
                    )
                )
                if not proposed.ok:
                    assert proposed.error is not None
                    raise RuntimeError(proposed.error.message)
            return {
                "workspace_uid": workspace_uid,
                "base_commit": runtime.base,
                "actor_uid": actor_uid,
                "delegation_uid": delegation_uid,
                "configuration_uid": configuration_uid,
                "identity_created": bool(identity["created"]),
                "selected_template": analysis.selected_pack.display_name,
                "requirement_count": len(analysis.requirements),
                "human_keys": [item.human_key for item in analysis.requirements],
                "next_step": "review_draft",
            }
        except (KeyError, OSError, PermissionError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def _preview_intake_file(self, value: IntakeFileRequest) -> dict[str, Any]:
        filename = Path(value.filename).name
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".md", ".markdown", ".pdf"}:
            raise HTTPException(status_code=415, detail="支持 Markdown 和 PDF 规范文件")
        try:
            raw = base64.b64decode(value.content_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(status_code=400, detail="文件内容无法读取") from error
        if not raw or len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="规范文件需小于 10 MiB")
        try:
            with tempfile.TemporaryDirectory(prefix="lesr-intake-") as temporary:
                source = Path(temporary) / filename
                source.write_bytes(raw)
                if suffix == ".pdf":
                    pdf_candidates = preview_pdf(
                        source,
                        namespace="imported",
                        kind="software_requirement",
                        rights_basis="user_provided",
                        license_id="source_managed",
                    )
                    sections = tuple(
                        (candidate.heading, self._candidate_statement(candidate.operations))
                        for candidate in pdf_candidates
                    )
                else:
                    markdown_candidates = preview_markdown(
                        source,
                        namespace="imported",
                        kind="software_requirement",
                        rights_basis="user_provided",
                        license_id="source_managed",
                    )
                    sections = tuple(
                        (candidate.heading, candidate.body)
                        for candidate in markdown_candidates
                    )
                    if not sections:
                        text = raw.decode("utf-8")
                        sections = ((Path(filename).stem, text),)
        except (UnicodeDecodeError, ValueError, PermissionError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        description = "\n\n".join(
            f"# {heading}\n{body.strip()}" for heading, body in sections if body.strip()
        )
        if len(description.strip()) < 20:
            raise HTTPException(status_code=422, detail="文件中没有足够的可读规范内容")
        analysis = IntakeService().analyze(
            IntakeRequest(
                description=description,
                project_name=value.project_name,
                known_repository=value.known_repository,
            )
        )
        return {
            "analysis": analysis.model_dump(mode="json"),
            "description": description,
            "source": {"filename": filename, "section_count": len(sections)},
        }

    @staticmethod
    def _candidate_statement(operations: tuple[dict[str, object], ...]) -> str:
        for operation in operations:
            resource = operation.get("resource")
            if not isinstance(resource, dict):
                continue
            fields = resource.get("fields")
            if not isinstance(fields, list):
                continue
            for field in fields:
                if isinstance(field, dict) and field.get("path") == "/statement":
                    return str(field.get("value", ""))
        return ""

    @staticmethod
    def _configuration_name(value: dict[str, Any], index: int) -> str:
        variant = value.get("variant")
        if isinstance(variant, str) and variant.strip():
            normalized = variant.strip()
            if normalized == "zero-spec-intake":
                return "主工程配置"
            return normalized
        created = str(value.get("created_at", ""))[:10]
        if created:
            return f"工程配置 · {created}"
        return f"工程配置 {index}"

    def _human_scope(
        self, scope: tuple[object, ...], *, workspace_uid: str
    ) -> list[dict[str, str]]:
        documents = tuple(
            value for _, value in GitCanonicalRepository(self.project).documents()
        )
        canonical_revisions = tuple(
            value for value in documents if value.get("resource_type") == "revision"
        )
        submission = getattr(self.domain, "submissions", {}).get(workspace_uid)
        candidate_revisions = (
            tuple(
                revision.model_dump(mode="json")
                for revision in submission.candidate.revisions
            )
            if submission is not None
            else ()
        )
        revisions = sorted(
            (*candidate_revisions, *canonical_revisions),
            key=lambda value: int(value.get("revision_number", 0)),
            reverse=True,
        )
        configurations = tuple(
            value
            for value in documents
            if value.get("resource_type") == "configuration_snapshot"
        )
        result: list[dict[str, str]] = []
        for raw_uid in scope:
            uid = str(raw_uid)
            revision = next(
                (
                    value
                    for value in revisions
                    if value.get("object_uid") == uid or value.get("revision_uid") == uid
                ),
                None,
            )
            configuration = next(
                (
                    value
                    for value in configurations
                    if value.get("configuration_uid") == uid
                ),
                None,
            )
            result.append(
                {
                    "human_key": (
                        str(revision.get("human_key"))
                        if revision is not None
                        else self._configuration_name(configuration, 1)
                        if configuration is not None
                        else "工程内容"
                    ),
                    "kind": (
                        str(revision.get("kind", "工程对象"))
                        if revision is not None
                        else "configuration_snapshot"
                        if configuration is not None
                        else "工程对象"
                    ),
                }
            )
        return result

    def _signing_resources(
        self, package_uid: str, actor_uid: str, key_uid: str
    ) -> tuple[dict[str, Any], TrustedActor]:
        documents = GitCanonicalRepository(self.project).documents()
        package = self._review_package(package_uid)
        trust_value = next(
            (
                value
                for _, value in documents
                if value.get("resource_type") == "trusted_actor"
                and value.get("actor_uid") == actor_uid
                and value.get("key_uid") == key_uid
            ),
            None,
        )
        if package is None or trust_value is None:
            raise HTTPException(
                status_code=404, detail="Canonical Review Package or trusted key not found"
            )
        return package, TrustedActor.model_validate(trust_value)

    def _review_package(self, package_uid: str) -> dict[str, Any] | None:
        resolver = getattr(self.domain, "review_package", None)
        if callable(resolver):
            result = resolver(package_uid).payload()
            value = result.get("value") if result.get("ok") is True else None
            if isinstance(value, dict):
                return value
        return next(
            (
                value
                for _, value in GitCanonicalRepository(self.project).documents()
                if value.get("resource_type") == "review_package"
                and value.get("package_uid") == package_uid
            ),
            None,
        )

    @staticmethod
    def _value_or_error(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("ok") is not True:
            error = payload.get("error", {})
            raise HTTPException(status_code=409, detail=error)
        value = payload.get("value")
        return value if isinstance(value, dict) else {"items": value}


def create_web_app(
    project: Path,
    domain: LESRDomainPort | None = None,
    *,
    launch_token: str | None = None,
) -> tuple[FastAPI, str]:
    runtime = LocalWebRuntime(project, domain, launch_token=launch_token)
    return runtime.app, runtime.launch_token
