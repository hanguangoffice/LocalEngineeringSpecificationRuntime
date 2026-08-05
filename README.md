# LESR

> **Development status:** `LESR_Solution_Design_Baseline_v1.0/` is the current
> design authority. The implementation under `src/lesr` is the superseded
> v0.1 YAML MVP and is retained only as a runnable reference while the P1-P5
> prototype gates are evaluated.

Local Engineering Specification Runtime (LESR) turns Git-managed engineering
specifications into structured, auditable local objects.

## Legacy implementation

The legacy MVP provides structured YAML facts, Profile validation,
SQLite/FTS5 retrieval, controlled change and baselines, context construction,
MCP query tools, and the `examples/home-control` project.

```powershell
python -m lesr.cli.main init demo
python -m lesr.cli.main artifact-create demo REQ-SW-0001 software_requirement "Reconnect MQTT" --statement "The client shall reconnect after an unexpected disconnect."
python -m lesr.cli.main artifact-get demo REQ-SW-0001
```

YAML files are the source of truth. The `.lesr/` directory contains rebuildable
runtime state, snapshots, and audit records.

## Specification import preview

UTF-8 Markdown specifications can be converted into review candidates without
writing formal project data:

```powershell
lesr import-preview demo specifications/demo-standard.md --artifact-type coding_rule
```

Every candidate includes source provenance and remains in `candidate` review
status. See [the import-preview documentation](docs/specification-import.md).

After human review, one exact candidate can be accepted as a formal draft:

```powershell
lesr import-accept demo specifications/demo-standard.md CAND-... `
  --expected-source-hash "sha256:..." `
  --actor reviewer `
  --artifact-type coding_rule
```

Acceptance binds the reviewed source and candidate identity, then writes the
draft Artifact, its first version snapshot, and an attributed audit event.

## v1.0 prototype gates

The new semantic model is developed in `prototypes/lesr_v1` and does not import
the legacy domain model. Gate reports live in `docs/prototype-results`. Run the
quality suite with Python 3.12 through uv:

```powershell
uv sync --all-extras
uv run python scripts/verify_baseline_manifest.py
uv run pytest
uv run ruff check .
uv run mypy src prototypes
```
