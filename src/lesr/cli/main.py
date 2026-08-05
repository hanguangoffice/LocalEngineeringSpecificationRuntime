"""LESR v1 capability-oriented command line interface."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import typer

from lesr.adapters.git import (
    ApprovalAttestation,
    CheckpointStrategy,
    GitCanonicalRepository,
    OperationType,
    SemanticOperation,
    SemanticTransaction,
)
from lesr.adapters.markdown import preview_markdown
from lesr.adapters.mcp import create_server
from lesr.adapters.schemas import SchemaCatalog
from lesr.application.service import RepositoryDomainService
from lesr.domain.approval import (
    ApprovalKeyStore,
    ApprovalPayload,
    SignedApproval,
    TrustedActor,
    verify_approval,
)
from lesr.domain.semantic import document_hash, semantic_hash, uuid7_candidate

app = typer.Typer(no_args_is_help=True, help="Local Engineering Specification Runtime v1")
context_app = typer.Typer(no_args_is_help=True)
workspace_app = typer.Typer(no_args_is_help=True)
approval_app = typer.Typer(no_args_is_help=True)
baseline_app = typer.Typer(no_args_is_help=True)
projection_app = typer.Typer(no_args_is_help=True)
reconcile_app = typer.Typer(no_args_is_help=True)
mcp_app = typer.Typer(no_args_is_help=True)
app.add_typer(context_app, name="context")
app.add_typer(workspace_app, name="workspace")
app.add_typer(approval_app, name="approval")
app.add_typer(baseline_app, name="baseline")
app.add_typer(projection_app, name="projection")
app.add_typer(reconcile_app, name="reconcile")
app.add_typer(mcp_app, name="mcp")


def emit(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str))


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise typer.BadParameter(f"expected a JSON object: {path}")
    return value


@app.command("init")
def initialize(project: Path) -> None:
    commit = GitCanonicalRepository(project).initialize()
    emit({"canonical_ref": GitCanonicalRepository.CANONICAL_REF, "commit": commit})


@app.command()
def resolve(project: Path, identifier: str) -> None:
    emit(RepositoryDomainService(project).resolve(identifier).payload())


@app.command()
def inspect(project: Path, uid: str) -> None:
    emit(RepositoryDomainService(project).inspect(uid).payload())


@app.command()
def query(project: Path, kind: str | None = None, cursor: str | None = None, page_size: int = 50) -> None:
    emit(RepositoryDomainService(project).query(kind, cursor, page_size).payload())


@context_app.command("build")
def build_context(project: Path, task_type: str, target: list[str], token_budget: int = 4096) -> None:
    emit(RepositoryDomainService(project).build_context(task_type, tuple(target), token_budget).payload())


@workspace_app.command("open")
def open_workspace(project: Path, delegation_uid: str, workspace_uid: str = "") -> None:
    repository = GitCanonicalRepository(project)
    repository.initialize()
    uid = workspace_uid or uuid7_candidate()
    checkpoint = repository.create_checkpoint(
        uid,
        {"workspace_uid": uid, "delegation_uid": delegation_uid, "state": "open"},
        CheckpointStrategy.WORKSPACE_REF,
    )
    emit(repository.checkpoint_payload(checkpoint) | {"git_reference": checkpoint.git_reference})


@workspace_app.command("checkpoint")
def checkpoint_workspace(project: Path, workspace_uid: str, state: Path) -> None:
    repository = GitCanonicalRepository(project)
    result = repository.create_checkpoint(
        workspace_uid, read_object(state), CheckpointStrategy.WORKSPACE_REF
    )
    emit({"checkpoint_uid": result.checkpoint_uid, "commit": result.commit, "git_reference": result.git_reference})


@app.command("review-package")
def build_review_package(candidate: Path) -> None:
    value = read_object(candidate)
    emit(value | {"package_hash": document_hash(value, "package_hash")})


@app.command("import-preview")
def import_preview(project: Path, source: Path, namespace: str, kind: str) -> None:
    root = project.resolve()
    selected = source.resolve()
    try:
        selected.relative_to(root)
    except ValueError as error:
        raise typer.BadParameter("source must be inside the project") from error
    emit([asdict(item) for item in preview_markdown(selected, namespace=namespace, kind=kind)])


@approval_app.command("keygen")
def approval_keygen(
    actor_uid: str,
    display_name: str,
    role: list[str],
    key_root: Path | None = None,
) -> None:
    emit(ApprovalKeyStore(key_root).generate(actor_uid, display_name, tuple(role)).model_dump(mode="json"))


@approval_app.command("sign")
def approval_sign(
    trust_record: Path,
    payload_file: Path,
    role: str,
    key_root: Path | None = None,
) -> None:
    trust = TrustedActor.model_validate(read_object(trust_record))
    payload = ApprovalPayload.model_validate(read_object(payload_file))
    emit(ApprovalKeyStore(key_root).sign(trust, role, payload).model_dump(mode="json"))


@app.command("apply")
def apply_transaction(
    project: Path,
    transaction_file: Path,
    review_package_file: Path,
    approval_file: Path,
    trust_record: Path,
) -> None:
    raw = read_object(transaction_file)
    review_package = read_object(review_package_file)
    approval_value = read_object(approval_file)
    trust_value = read_object(trust_record)
    schemas = SchemaCatalog()
    schemas.validate("semantic-transaction.schema.json", raw)
    schemas.validate("review-package.schema.json", review_package)
    schemas.validate("approval-attestation.schema.json", approval_value)
    schemas.validate("trusted-actor.schema.json", trust_value)
    signed = SignedApproval.model_validate(approval_value)
    trust = TrustedActor.model_validate(trust_value)
    package_hash = str(review_package["package_hash"])
    if document_hash(review_package, "package_hash") != package_hash:
        raise typer.BadParameter("review package content hash is invalid")
    if raw["review_package_hash"] != package_hash:
        raise typer.BadParameter("transaction review package hash does not match")
    if review_package["base_commit"] != raw["base_commit"]:
        raise typer.BadParameter("review package base does not match the transaction")
    if review_package["workspace_uid"] != raw["workspace_uid"]:
        raise typer.BadParameter("review package workspace does not match the transaction")
    if review_package["effective_model_hash"] != raw["effective_model_hash"]:
        raise typer.BadParameter("review package effective model does not match")
    semantic_diff = review_package["semantic_diff"]
    operation_hashes = [
        semantic_hash(
            {
                "operation_type": item["operation_type"],
                "target": item["target"],
                "payload": item["payload"],
            }
        )
        for item in raw["operations"]
    ]
    if not isinstance(semantic_diff, dict) or semantic_diff.get(
        "operation_hashes"
    ) != operation_hashes:
        raise typer.BadParameter("review package does not bind the semantic operations")
    verify_approval(
        signed,
        trust,
        package_hash=package_hash,
        effective_model_hash=str(raw["effective_model_hash"]),
    )
    repository = GitCanonicalRepository(project)
    repository.initialize()
    operations = tuple(
        SemanticOperation(
            OperationType(item["operation_type"]),
            str(item["target"]),
            dict(item["payload"]),
        )
        for item in raw["operations"]
    )
    transaction = SemanticTransaction(
        transaction_uid=str(raw["transaction_uid"]),
        base_commit=str(raw["base_commit"]),
        expected_revisions=tuple(
            (str(item["revision_uid"]), str(item["content_hash"]))
            for item in raw.get("expected_revisions", [])
        ),
        effective_model_hash=str(raw["effective_model_hash"]),
        review_package_hash=package_hash,
        operations=operations,
        approvals=(
            ApprovalAttestation(
                signed.approval_uid,
                signed.package_hash,
                signed.actor_uid,
                "human",
                signed.approval_type,
            ),
        ),
        actor=str(raw["actor_uid"]),
        delegation_uid=str(raw["delegation_uid"]),
        idempotency_key=str(raw["idempotency_key"]),
    )
    emit(asdict(repository.apply(transaction)))


@baseline_app.command("create")
def create_baseline(manifest: Path) -> None:
    value = read_object(manifest)
    emit(value | {"manifest_hash": document_hash(value, "manifest_hash")})


@projection_app.command("rebuild")
def rebuild_projection(project: Path) -> None:
    repository = GitCanonicalRepository(project)
    repository.initialize()
    database = project / ".lesr" / "projection.sqlite3"
    emit({"source_commit": repository.rebuild_projection(database), "database": str(database)})


@reconcile_app.command("check")
def check_reconciliation(path: list[str]) -> None:
    emit({"required": GitCanonicalRepository.requires_reconciliation(tuple(path)), "paths": path})


@mcp_app.command("serve")
def serve_mcp(project: Path) -> None:
    create_server(RepositoryDomainService(project)).run()


if __name__ == "__main__":
    app()
