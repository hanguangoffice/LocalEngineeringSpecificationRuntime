"""Initial CLI commands. Business operations delegate to repositories/services."""

from pathlib import Path

import typer

from lesr.domain.models import Artifact
from lesr.errors import LESRError
from lesr.mcp.server import create_server
from lesr.retrieval.sqlite_index import SQLiteIndex
from lesr.storage.yaml_repository import YamlRepository

app = typer.Typer(no_args_is_help=True, help="Local Engineering Specification Runtime")


@app.command("init")
def initialize(project: Path, project_id: str = typer.Option(None, help="Stable project identifier")) -> None:
    repo = YamlRepository(project)
    repo.initialize(project_id or project.name)
    typer.echo(f"Initialized LESR project: {project.resolve()}")


@app.command("artifact-create")
def artifact_create(project: Path, artifact_id: str, artifact_type: str, title: str, statement: str | None = None, actor: str = "user") -> None:
    repo = YamlRepository(project)
    artifact = Artifact(id=artifact_id, artifact_type=artifact_type, title=title, statement=statement)
    try:
        saved = repo.create_artifact(artifact, actor=actor)
    except LESRError as error:
        raise typer.Exit(code=_print_error(error)) from error
    typer.echo(saved.model_dump_json(indent=2))


@app.command("artifact-get")
def artifact_get(project: Path, artifact_id: str) -> None:
    try:
        artifact = YamlRepository(project).get_artifact(artifact_id)
    except LESRError as error:
        raise typer.Exit(code=_print_error(error)) from error
    typer.echo(artifact.model_dump_json(indent=2))


@app.command("index")
def rebuild_index(project: Path) -> None:
    repository = YamlRepository(project)
    SQLiteIndex(project).rebuild(repository.list_artifacts(), repository.list_relations())
    typer.echo("LESR index rebuilt")


@app.command("serve-mcp")
def serve_mcp(project: Path) -> None:
    create_server(project).run()


def _print_error(error: LESRError) -> int:
    typer.echo(str(error), err=True)
    return 2


if __name__ == "__main__":
    app()
