"""LESR v1 capability-oriented command line interface."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from lesr.adapters.git import (
    CheckpointStrategy,
    GitCanonicalRepository,
)
from lesr.adapters.markdown import preview_markdown
from lesr.adapters.mcp import create_server
from lesr.adapters.operations import RepositoryMaintenance, TaskStore, plan_workspace_gc
from lesr.adapters.pdf_import import preview_pdf
from lesr.application.contracts import RiskClass, WriteEnvelope
from lesr.application.service import RepositoryDomainService
from lesr.domain.approval import (
    ApprovalKeyStore,
    ApprovalPayload,
    TrustedActor,
)
from lesr.domain.catalog import CAPABILITIES, RUNTIME_CONTRACT_VERSION
from lesr.domain.semantic import document_hash, uuid7_candidate

app = typer.Typer(no_args_is_help=True, help="Local Engineering Specification Runtime v1")
context_app = typer.Typer(no_args_is_help=True)
workspace_app = typer.Typer(no_args_is_help=True)
approval_app = typer.Typer(no_args_is_help=True)
baseline_app = typer.Typer(no_args_is_help=True)
projection_app = typer.Typer(no_args_is_help=True)
reconcile_app = typer.Typer(no_args_is_help=True)
mcp_app = typer.Typer(no_args_is_help=True)
task_app = typer.Typer(no_args_is_help=True)
app.add_typer(context_app, name="context")
app.add_typer(workspace_app, name="workspace")
app.add_typer(approval_app, name="approval")
app.add_typer(baseline_app, name="baseline")
app.add_typer(projection_app, name="projection")
app.add_typer(reconcile_app, name="reconcile")
app.add_typer(mcp_app, name="mcp")
app.add_typer(task_app, name="task")


def emit(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str))


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise typer.BadParameter(f"expected a JSON object: {path}")
    return value


@app.command("capabilities")
def show_capabilities() -> None:
    emit(
        {
            "contract_version": RUNTIME_CONTRACT_VERSION,
            "capabilities": [item.model_dump(mode="json") for item in CAPABILITIES],
        }
    )


@task_app.command("enqueue")
def enqueue_task(project: Path, task_type: str, request: Path) -> None:
    emit(TaskStore(project).enqueue(task_type, read_object(request)).model_dump(mode="json"))


@task_app.command("status")
def task_status(project: Path, task_uid: str) -> None:
    emit(TaskStore(project).get(task_uid).model_dump(mode="json"))


@task_app.command("cancel")
def task_cancel(project: Path, task_uid: str) -> None:
    emit(TaskStore(project).request_cancel(task_uid).model_dump(mode="json"))


@app.command("backup")
def backup_repository(project: Path, destination: Path) -> None:
    result = RepositoryMaintenance(project).backup(destination)
    emit(
        {
            "bundle": str(result.bundle),
            "manifest": str(result.manifest),
            "bundle_sha256": result.bundle_sha256,
        }
    )


@app.command("restore")
def restore_repository(source: Path, destination: Path) -> None:
    emit({"canonical_commit": RepositoryMaintenance.restore(source, destination)})


@app.command("migrate")
def migrate_repository(project: Path, target_version: str, dry_run: bool = True) -> None:
    emit(RepositoryMaintenance(project).migration_plan(target_version, dry_run=dry_run))


@app.command("gc")
def garbage_collect_workspaces(project: Path, dry_run: bool = True) -> None:
    del project
    emit(plan_workspace_gc((), (), now=datetime.now(UTC), dry_run=dry_run).model_dump(mode="json"))


@app.command("init")
def initialize(project: Path) -> None:
    commit = GitCanonicalRepository(project).initialize()
    emit({"canonical_ref": GitCanonicalRepository.CANONICAL_REF, "commit": commit})


@app.command("bootstrap")
def bootstrap_root_owner(
    project: Path,
    trust_record: Path,
    delegation_record: Path,
    role: str,
    idempotency_key: str,
    governance_bundle: Path | None = None,
    key_root: Path | None = None,
) -> None:
    """Establish the first root trust with local proof of private-key possession."""
    domain = RepositoryDomainService(project)
    trust_value = read_object(trust_record)
    delegation_value = read_object(delegation_record)
    trust = TrustedActor.model_validate(trust_value)
    governance_values: tuple[dict[str, Any], ...] = ()
    if governance_bundle is not None:
        bundle = read_object(governance_bundle)
        raw_operations = bundle.get("operations")
        if not isinstance(raw_operations, list) or not all(
            isinstance(item, dict) for item in raw_operations
        ):
            raise typer.BadParameter("governance bundle must contain an operations array")
        governance_values = tuple(raw_operations)
    package_hash, model_hash, scope = domain.bootstrap_binding(
        domain.base, trust_value, delegation_value, governance_values
    )
    approval = ApprovalKeyStore(key_root).sign(
        trust,
        role,
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope=scope,
            approval_type="technical",
        ),
    )
    emit(
        domain.bootstrap_root_owner(
            trust_value,
            delegation_value,
            approval.model_dump(mode="json"),
            idempotency_key,
            governance_values,
        ).payload()
    )


@app.command("init-configuration")
def initialize_configuration(
    project: Path,
    configuration_file: Path,
    trust_record: Path,
    actor_uid: str,
    delegation_uid: str,
    role: str,
    idempotency_key: str,
    key_root: Path | None = None,
) -> None:
    domain = RepositoryDomainService(project)
    configuration = read_object(configuration_file)
    trust = TrustedActor.model_validate(read_object(trust_record))
    package_hash, model_hash, scope = domain.initial_configuration_binding(
        domain.base, configuration
    )
    approval = ApprovalKeyStore(key_root).sign(
        trust,
        role,
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope=scope,
            approval_type="technical",
        ),
    )
    emit(
        domain.initialize_configuration(
            configuration,
            approval.model_dump(mode="json"),
            actor_uid,
            delegation_uid,
            idempotency_key,
        ).payload()
    )


@app.command()
def resolve(project: Path, identifier: str) -> None:
    emit(RepositoryDomainService(project).resolve(identifier).payload())


@app.command()
def inspect(project: Path, uid: str) -> None:
    emit(RepositoryDomainService(project).inspect(uid).payload())


@app.command()
def query(
    project: Path,
    kind: str | None = None,
    cursor: str | None = None,
    page_size: int = 50,
    text: str | None = None,
) -> None:
    emit(RepositoryDomainService(project).query(kind, cursor, page_size, text).payload())


@app.command("trace")
def trace(
    project: Path,
    start_uid: str,
    predicate: str | None = None,
    max_depth: int = 4,
) -> None:
    emit(RepositoryDomainService(project).traverse(start_uid, predicate, max_depth).payload())


@app.command("impact")
def impact(project: Path, start_uid: str, max_depth: int = 4) -> None:
    emit(RepositoryDomainService(project).impact(start_uid, max_depth).payload())


@context_app.command("build")
def build_context(
    project: Path,
    task_type: str,
    target: list[str],
    configuration_uid: str,
    actor_uid: str,
    token_budget: int = 4096,
) -> None:
    emit(
        RepositoryDomainService(project)
        .build_context(task_type, tuple(target), token_budget, configuration_uid, actor_uid)
        .payload()
    )


@workspace_app.command("open")
def open_workspace(
    project: Path,
    delegation_uid: str,
    actor_uid: str,
    idempotency_key: str,
    workspace_uid: str = "",
    dry_run: bool = False,
) -> None:
    domain = RepositoryDomainService(project)
    uid = workspace_uid or uuid7_candidate()
    result = domain.open_workspace(
        WriteEnvelope(
            uid,
            domain.base,
            idempotency_key,
            actor_uid,
            delegation_uid,
            dry_run,
            RiskClass.MEDIUM,
            {"type": "open_workspace"},
        )
    )
    emit(result.payload())


@workspace_app.command("checkpoint")
def checkpoint_workspace(project: Path, workspace_uid: str, state: Path) -> None:
    repository = GitCanonicalRepository(project)
    result = repository.create_checkpoint(
        workspace_uid, read_object(state), CheckpointStrategy.WORKSPACE_REF
    )
    emit(
        {
            "checkpoint_uid": result.checkpoint_uid,
            "commit": result.commit,
            "git_reference": result.git_reference,
        }
    )


@workspace_app.command("propose")
def propose_workspace_operation(
    project: Path,
    workspace_uid: str,
    expected_base: str,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
    operation_file: Path,
    dry_run: bool = False,
) -> None:
    emit(
        RepositoryDomainService(project)
        .propose_operation(
            WriteEnvelope(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor_uid,
                delegation_uid,
                dry_run,
                RiskClass.MEDIUM,
                read_object(operation_file),
            )
        )
        .payload()
    )


@app.command("review-package")
def build_review_package(
    project: Path,
    workspace_uid: str,
    expected_base: str,
    configuration_uid: str,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
    dry_run: bool = False,
) -> None:
    emit(
        RepositoryDomainService(project)
        .prepare_review(
            WriteEnvelope(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor_uid,
                delegation_uid,
                dry_run,
                RiskClass.HIGH,
                {"configuration_uid": configuration_uid},
            )
        )
        .payload()
    )


@app.command("import-preview")
def import_preview(
    project: Path,
    source: Path,
    namespace: str,
    kind: str,
    rights_basis: str,
    license_id: str,
) -> None:
    root = project.resolve()
    selected = source.resolve()
    try:
        selected.relative_to(root)
    except ValueError as error:
        raise typer.BadParameter("source must be inside the project") from error
    candidates: tuple[Any, ...]
    if selected.suffix.casefold() == ".pdf":
        candidates = preview_pdf(
            selected,
            namespace=namespace,
            kind=kind,
            rights_basis=rights_basis,
            license_id=license_id,
        )
    elif selected.suffix.casefold() in {".md", ".markdown"}:
        candidates = preview_markdown(
            selected,
            namespace=namespace,
            kind=kind,
            rights_basis=rights_basis,
            license_id=license_id,
        )
    else:
        raise typer.BadParameter("supported preview formats are UTF-8 Markdown and text PDF")
    emit([asdict(item) for item in candidates])


@approval_app.command("keygen")
def approval_keygen(
    actor_uid: str,
    display_name: str,
    role: list[str],
    key_root: Path | None = None,
) -> None:
    emit(
        ApprovalKeyStore(key_root)
        .generate(actor_uid, display_name, tuple(role))
        .model_dump(mode="json")
    )


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
    workspace_uid: str,
    expected_base: str,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
    review_package_uid: str,
    approval_file: list[Path],
    transaction_uid: str = "",
    dry_run: bool = False,
) -> None:
    approval_values = [read_object(path) for path in approval_file]
    domain = RepositoryDomainService(project)
    result = domain.apply_transaction(
        WriteEnvelope(
            workspace_uid,
            expected_base,
            idempotency_key,
            actor_uid,
            delegation_uid,
            dry_run,
            RiskClass.HIGH,
            {
                "transaction_uid": transaction_uid or uuid7_candidate(),
                "review_package_uid": review_package_uid,
                "signed_approvals": approval_values,
            },
        )
    )
    emit(result.payload())


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
