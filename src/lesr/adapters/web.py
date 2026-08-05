"""Loopback-only FastAPI adapter for the LESR local product."""

from __future__ import annotations

import secrets
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
from lesr.adapters.operations import TaskStore, plan_workspace_gc
from lesr.adapters.signer import sign_once
from lesr.application.contracts import LESRDomainPort
from lesr.application.runtime import LocalRuntimeService
from lesr.domain.approval import ApprovalPayload, TrustedActor
from lesr.domain.catalog import CAPABILITIES, RUNTIME_CONTRACT_VERSION

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


class SignRequest(BaseModel):
    package_uid: str = Field(min_length=1)
    actor_uid: str = Field(min_length=1)
    key_uid: str = Field(min_length=1)
    role: str = Field(min_length=1)
    human_confirm: bool


class LocalWebRuntime:
    def __init__(
        self,
        project: Path,
        domain: LESRDomainPort | None = None,
        *,
        launch_token: str | None = None,
    ) -> None:
        self.project = project.resolve()
        self.domain = domain or LocalRuntimeService(self.project)
        self.launch_token = launch_token or secrets.token_urlsafe(32)
        self.launch_token_available = True
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

        @app.get("/api/query")
        async def query(request: Request, text: str = "") -> dict[str, Any]:
            self._session(request)
            result = self.domain.query(None, None, 50, text or None).payload()
            return self._value_or_error(result)

        @app.get("/api/review-package/{package_uid}")
        async def review_package(request: Request, package_uid: str) -> dict[str, Any]:
            self._session(request)
            package = next(
                (
                    value
                    for _, value in GitCanonicalRepository(self.project).documents()
                    if value.get("resource_type") == "review_package"
                    and value.get("package_uid") == package_uid
                ),
                None,
            )
            if package is None:
                raise HTTPException(status_code=404, detail="Canonical Review Package not found")
            return {
                "package_uid": package_uid,
                "package_hash": package.get("package_hash"),
                "effective_model_hash": package.get("effective_model_hash"),
                "candidate_scope": package.get("candidate_scope", []),
                "role": package.get("review_stage", "review"),
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
            ).payload()
            return self._value_or_error(result)

        @app.get("/api/tasks")
        async def tasks(request: Request) -> list[dict[str, Any]]:
            self._session(request)
            return [item.model_dump(mode="json") for item in TaskStore(self.project).list()]

        @app.post("/api/maintenance/gc")
        async def gc_plan(request: Request) -> dict[str, Any]:
            self._mutation_session(request)
            return plan_workspace_gc((), (), now=datetime.now(UTC), dry_run=True).model_dump(
                mode="json"
            )

        @app.post("/api/sign")
        async def sign(request: Request, value: SignRequest) -> dict[str, Any]:
            self._mutation_session(request)
            if not value.human_confirm:
                raise HTTPException(status_code=403, detail="explicit human confirmation required")
            package, trust = self._signing_resources(
                value.package_uid, value.actor_uid, value.key_uid
            )
            payload = ApprovalPayload(
                package_hash=str(package["package_hash"]),
                effective_model_hash=str(package["effective_model_hash"]),
                scope={"resource_uids": list(package["candidate_scope"])},
                approval_type=str(package.get("review_stage", "review")),
                expires_at=(datetime.now(UTC) + timedelta(minutes=15)),
                conditions=tuple(package.get("approval_conditions", ())),
            )
            approval = sign_once(self.project, trust, value.role, payload)
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

    def _signing_resources(
        self, package_uid: str, actor_uid: str, key_uid: str
    ) -> tuple[dict[str, Any], TrustedActor]:
        documents = GitCanonicalRepository(self.project).documents()
        package = next(
            (
                value
                for _, value in documents
                if value.get("resource_type") == "review_package"
                and value.get("package_uid") == package_uid
            ),
            None,
        )
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
