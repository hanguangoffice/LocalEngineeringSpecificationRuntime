"""LESR v1 capability-oriented command line interface."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import typer

from lesr.adapters.git import (
    CheckpointStrategy,
    GitCanonicalRepository,
)
from lesr.adapters.markdown import preview_markdown
from lesr.adapters.mcp import create_server
from lesr.adapters.operations import RepositoryMaintenance, TaskStore
from lesr.adapters.pdf_import import preview_pdf
from lesr.adapters.web import create_web_app
from lesr.application.contracts import RiskClass, WriteEnvelope
from lesr.application.runtime import LocalRuntimeService
from lesr.domain.approval import (
    ApprovalKeyStore,
    ApprovalPayload,
    TrustedActor,
)
from lesr.domain.catalog import CAPABILITIES, RUNTIME_CONTRACT_VERSION
from lesr.domain.semantic import uuid7_candidate

app = typer.Typer(no_args_is_help=True, help="Local Engineering Specification Runtime v1")
context_app = typer.Typer(no_args_is_help=True)
workspace_app = typer.Typer(no_args_is_help=True)
approval_app = typer.Typer(no_args_is_help=True)
baseline_app = typer.Typer(no_args_is_help=True)
review_app = typer.Typer(no_args_is_help=True)
projection_app = typer.Typer(no_args_is_help=True)
reconcile_app = typer.Typer(no_args_is_help=True)
mcp_app = typer.Typer(no_args_is_help=True)
task_app = typer.Typer(no_args_is_help=True)
app.add_typer(context_app, name="context")
app.add_typer(workspace_app, name="workspace")
app.add_typer(approval_app, name="approval")
app.add_typer(baseline_app, name="baseline")
app.add_typer(review_app, name="review")
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


@task_app.command("run-next")
def task_run_next(project: Path) -> None:
    emit(LocalRuntimeService(project).run_next_task().payload())


@task_app.command("result")
def task_result(project: Path, task_uid: str) -> None:
    emit(LocalRuntimeService(project).task_result(task_uid).payload())


@task_app.command("resume")
def task_resume(project: Path, task_uid: str) -> None:
    emit(TaskStore(project).resume(task_uid).model_dump(mode="json"))


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
    emit(RepositoryMaintenance(project).workspace_gc(dry_run=dry_run))


@app.command("init")
def initialize(project: Path) -> None:
    commit = GitCanonicalRepository(project).initialize()
    emit({"canonical_ref": GitCanonicalRepository.CANONICAL_REF, "commit": commit})


@app.command("bootstrap-root")
def bootstrap_root(
    project: Path,
    trust_record: Path,
    delegation_record: Path,
    approval_record: Path,
    idempotency_key: str,
    governance_operation: list[Path] | None = None,
) -> None:
    """Install the first human root key and exact bootstrap governance set."""

    operations = tuple(read_object(path) for path in (governance_operation or []))
    emit(
        LocalRuntimeService(project)
        .bootstrap_root_owner(
            read_object(trust_record),
            read_object(delegation_record),
            read_object(approval_record),
            idempotency_key,
            operations,
        )
        .payload()
    )


@app.command("bootstrap-plan")
def plan_bootstrap(
    project: Path,
    trust_record: Path,
    delegation_record: Path,
    governance_operation: list[Path] | None = None,
) -> None:
    """Build the immutable payload that the root owner must sign."""

    domain = LocalRuntimeService(project)
    package_hash, model_hash, scope = domain.bootstrap_binding(
        domain.base,
        read_object(trust_record),
        read_object(delegation_record),
        tuple(read_object(path) for path in (governance_operation or [])),
    )
    emit(
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope=scope,
            approval_type="technical",
        ).model_dump(mode="json")
    )


@app.command("configuration-init")
def initialize_configuration(
    project: Path,
    configuration_record: Path,
    approval_record: Path,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
) -> None:
    """Create the first complete Configuration through the production facade."""

    emit(
        LocalRuntimeService(project)
        .initialize_configuration(
            read_object(configuration_record),
            read_object(approval_record),
            actor_uid,
            delegation_uid,
            idempotency_key,
        )
        .payload()
    )


@app.command("configuration-plan")
def plan_initial_configuration(project: Path, configuration_record: Path) -> None:
    """Build the immutable payload for first Configuration approval."""

    domain = LocalRuntimeService(project)
    configuration = read_object(configuration_record)
    package_hash, model_hash, scope = domain.initial_configuration_binding(
        domain.base, configuration
    )
    emit(
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope=scope,
            approval_type="technical",
        ).model_dump(mode="json")
    )


@app.command("configuration-create")
def create_configuration(
    project: Path,
    configuration_record: Path,
    approval_record: Path,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
    supporting_approval: list[Path] | None = None,
) -> None:
    """Create an immutable successor Configuration with bound governance approvals."""

    emit(
        LocalRuntimeService(project)
        .create_configuration(
            read_object(configuration_record),
            read_object(approval_record),
            actor_uid,
            delegation_uid,
            idempotency_key,
            tuple(read_object(path) for path in (supporting_approval or [])),
        )
        .payload()
    )


@app.command("configuration-create-plan")
def plan_configuration(
    project: Path,
    configuration_record: Path,
    supporting_approval: list[Path] | None = None,
) -> None:
    """Build the exact approval payload for a successor Configuration."""

    domain = LocalRuntimeService(project)
    planned = domain.plan_configuration(read_object(configuration_record))
    if not planned.ok:
        emit(planned.payload())
        return
    configuration = planned.value
    assert configuration is not None
    approvals = tuple(read_object(path) for path in (supporting_approval or []))
    package_hash, model_hash, scope = domain.configuration_binding(
        domain.base, configuration, approvals
    )
    emit(
        {
            "configuration": configuration,
            "approval_payload": ApprovalPayload(
                package_hash=package_hash,
                effective_model_hash=model_hash,
                scope=scope,
                approval_type="technical",
            ).model_dump(mode="json"),
        }
    )


@app.command("governance-approval-record")
def record_governance_approval(
    project: Path,
    approval_record: Path,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
) -> None:
    """Persist a signed Deviation, Exception or Rule-conflict approval."""

    emit(
        LocalRuntimeService(project)
        .record_governance_approval(
            read_object(approval_record),
            actor_uid,
            delegation_uid,
            idempotency_key,
        )
        .payload()
    )


@app.command()
def resolve(project: Path, identifier: str) -> None:
    emit(LocalRuntimeService(project).resolve(identifier).payload())


@app.command()
def inspect(project: Path, uid: str) -> None:
    emit(LocalRuntimeService(project).inspect(uid).payload())


@app.command()
def query(
    project: Path,
    kind: str | None = None,
    cursor: str | None = None,
    page_size: int = 50,
    text: str | None = None,
) -> None:
    emit(LocalRuntimeService(project).query(kind, cursor, page_size, text).payload())


@app.command("trace")
def trace(
    project: Path,
    start_uid: str,
    configuration_uid: str,
    evaluation_time: str,
    predicate: str | None = None,
    max_depth: int = 4,
) -> None:
    emit(
        LocalRuntimeService(project)
        .traverse(start_uid, predicate, max_depth, configuration_uid, evaluation_time)
        .payload()
    )


@app.command("impact")
def impact(
    project: Path,
    start_uid: str,
    configuration_uid: str,
    evaluation_time: str,
    max_depth: int = 4,
) -> None:
    emit(
        LocalRuntimeService(project)
        .impact(start_uid, max_depth, configuration_uid, evaluation_time)
        .payload()
    )


@context_app.command("build")
def build_context(
    project: Path,
    task_type: str,
    target: list[str],
    configuration_uid: str,
    actor_uid: str,
    evaluation_time: str,
    token_budget: int = 4096,
) -> None:
    emit(
        LocalRuntimeService(project)
        .build_context(
            task_type,
            tuple(target),
            token_budget,
            configuration_uid,
            actor_uid,
            evaluation_time,
        )
        .payload()
    )


@context_app.command("read")
def read_context(
    project: Path,
    bundle_hash: str,
    resource_uid: list[str] | None = None,
    maximum_resources: int = 100,
    maximum_bytes: int = 2 * 1024 * 1024,
) -> None:
    emit(
        LocalRuntimeService(project)
        .read_context(
            bundle_hash,
            tuple(resource_uid or ()),
            maximum_resources,
            maximum_bytes,
        )
        .payload()
    )


@context_app.command("trace")
def start_context_trace(
    project: Path, bundle_hash: str, start_uid: str, max_depth: int = 16
) -> None:
    emit(
        LocalRuntimeService(project)
        .start_deep_trace(bundle_hash, start_uid, max_depth)
        .payload()
    )


@workspace_app.command("open")
def open_workspace(
    project: Path,
    configuration_uid: str,
    delegation_uid: str,
    actor_uid: str,
    idempotency_key: str,
    workspace_uid: str = "",
    dry_run: bool = False,
) -> None:
    domain = LocalRuntimeService(project)
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
            {"type": "open_workspace", "configuration_uid": configuration_uid},
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
        LocalRuntimeService(project)
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


def invoke_runtime_write(
    method_name: str,
    project: Path,
    workspace_uid: str,
    expected_base: str,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
    operation_file: Path,
    dry_run: bool,
) -> None:
    domain = LocalRuntimeService(project)
    method = getattr(domain, method_name)
    emit(
        method(
            WriteEnvelope(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor_uid,
                delegation_uid,
                dry_run,
                RiskClass.HIGH,
                read_object(operation_file),
            )
        ).payload()
    )


@workspace_app.command("rebase")
def rebase_workspace(
    project: Path, workspace_uid: str, expected_base: str, actor_uid: str,
    delegation_uid: str, idempotency_key: str, operation_file: Path,
    dry_run: bool = False,
) -> None:
    invoke_runtime_write(
        "rebase_workspace", project, workspace_uid, expected_base, actor_uid,
        delegation_uid, idempotency_key, operation_file, dry_run
    )


@workspace_app.command("merge")
def merge_workspace(
    project: Path, workspace_uid: str, expected_base: str, actor_uid: str,
    delegation_uid: str, idempotency_key: str, operation_file: Path,
    dry_run: bool = False,
) -> None:
    invoke_runtime_write(
        "merge_workspace", project, workspace_uid, expected_base, actor_uid,
        delegation_uid, idempotency_key, operation_file, dry_run
    )


@workspace_app.command("resolve")
def resolve_workspace_conflict(
    project: Path, workspace_uid: str, expected_base: str, actor_uid: str,
    delegation_uid: str, idempotency_key: str, operation_file: Path,
    dry_run: bool = False,
) -> None:
    invoke_runtime_write(
        "resolve_merge_conflict", project, workspace_uid, expected_base, actor_uid,
        delegation_uid, idempotency_key, operation_file, dry_run
    )


@review_app.command("comment")
def review_comment(
    project: Path, workspace_uid: str, expected_base: str, actor_uid: str,
    delegation_uid: str, idempotency_key: str, operation_file: Path,
    dry_run: bool = False,
) -> None:
    invoke_runtime_write(
        "add_review_comment", project, workspace_uid, expected_base, actor_uid,
        delegation_uid, idempotency_key, operation_file, dry_run
    )


@review_app.command("record")
def review_record(
    record_type: str, project: Path, workspace_uid: str, expected_base: str,
    actor_uid: str, delegation_uid: str, idempotency_key: str,
    operation_file: Path, dry_run: bool = False,
) -> None:
    methods = {
        "resolution": "resolve_review_comment",
        "condition": "satisfy_review_condition",
        "revocation": "revoke_approval",
    }
    if record_type not in methods:
        raise typer.BadParameter("record_type must be resolution, condition, or revocation")
    invoke_runtime_write(
        methods[record_type], project, workspace_uid, expected_base, actor_uid,
        delegation_uid, idempotency_key, operation_file, dry_run
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
    evaluation_time: str,
    dry_run: bool = False,
) -> None:
    emit(
        LocalRuntimeService(project)
        .prepare_review(
            WriteEnvelope(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor_uid,
                delegation_uid,
                dry_run,
                RiskClass.HIGH,
                {
                    "configuration_uid": configuration_uid,
                    "evaluation_time": evaluation_time,
                },
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
    evaluation_time: str,
    transaction_uid: str = "",
    dry_run: bool = False,
) -> None:
    approval_values = [read_object(path) for path in approval_file]
    domain = LocalRuntimeService(project)
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
                "evaluation_time": evaluation_time,
            },
        )
    )
    emit(result.payload())


@baseline_app.command("prepare")
def prepare_baseline(
    project: Path,
    workspace_uid: str,
    expected_base: str,
    configuration_uid: str,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
    evaluation_time: str,
    dry_run: bool = False,
) -> None:
    emit(
        LocalRuntimeService(project)
        .prepare_baseline(
            WriteEnvelope(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor_uid,
                delegation_uid,
                dry_run,
                RiskClass.HIGH,
                {
                    "configuration_uid": configuration_uid,
                    "evaluation_time": evaluation_time,
                },
            )
        )
        .payload()
    )


@baseline_app.command("apply")
def apply_baseline(
    project: Path,
    workspace_uid: str,
    expected_base: str,
    review_package_uid: str,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
    evaluation_time: str,
    approval_file: list[Path],
    tag_name: str = "",
    dry_run: bool = False,
) -> None:
    emit(
        LocalRuntimeService(project)
        .apply_baseline(
            WriteEnvelope(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor_uid,
                delegation_uid,
                dry_run,
                RiskClass.HIGH,
                {
                    "review_package_uid": review_package_uid,
                    "signed_approvals": [read_object(path) for path in approval_file],
                    "evaluation_time": evaluation_time,
                    "tag_name": tag_name or None,
                },
            )
        )
        .payload()
    )


@baseline_app.command("tag-rebuild")
def rebuild_baseline_tag(project: Path, baseline_uid: str, tag_name: str) -> None:
    emit(LocalRuntimeService(project).rebuild_baseline_tag(baseline_uid, tag_name).payload())


@projection_app.command("rebuild")
def rebuild_projection(project: Path) -> None:
    repository = GitCanonicalRepository(project)
    repository.initialize()
    database = project / ".lesr" / "projection.sqlite3"
    emit({"source_commit": repository.rebuild_projection(database), "database": str(database)})


@reconcile_app.command("check")
def check_reconciliation(path: list[str]) -> None:
    emit({"required": GitCanonicalRepository.requires_reconciliation(tuple(path)), "paths": path})


@reconcile_app.command("open")
def open_reconciliation(
    project: Path,
    expected_base: str,
    actor_uid: str,
    delegation_uid: str,
    idempotency_key: str,
    operation_file: Path,
    dry_run: bool = False,
) -> None:
    invoke_runtime_write(
        "begin_reconciliation",
        project,
        uuid7_candidate(),
        expected_base,
        actor_uid,
        delegation_uid,
        idempotency_key,
        operation_file,
        dry_run,
    )


@mcp_app.command("serve")
def serve_mcp(project: Path) -> None:
    create_server(LocalRuntimeService(project)).run()


@app.command("web")
def serve_web(project: Path, port: int = 8765) -> None:
    """Launch the loopback-only product UI with a one-time unlock URL."""

    import uvicorn

    web_app, token = create_web_app(project)
    typer.echo(f"Open http://127.0.0.1:{port}/unlock?token={token}")
    uvicorn.run(web_app, host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    app()
