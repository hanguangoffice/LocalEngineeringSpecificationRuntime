# LESR v1

Local Engineering Specification Runtime is a Git-backed local semantic runtime
for engineering specifications. `LESR_Solution_Design_Baseline_v1.0/` is the
requirements authority and `docs/LESR_Codex_Construction_Spec_v1.0.md` is the
frozen implementation contract.

The v1 runtime separates Logical Objects, immutable Revisions and Records,
versioned Relation Assertions, typed rules, explicit Evaluation Context,
reviewed semantic transactions and Baselines. Git commit trees are authoritative;
SQLite/FTS5 is a disposable query projection.

## Development

```powershell
py -m uv sync --all-extras
py -m uv run python scripts/verify_baseline_manifest.py
py -m uv run python scripts/verify_construction_schemas.py
py -m uv run pytest
py -m uv run ruff check .
py -m uv run mypy src
```

CI runs the same gates on Python 3.12 for Ubuntu and Windows. The design baseline
is protected from line-ending conversion and verified byte-for-byte against its
81-entry Manifest.

## Capability CLI

```powershell
lesr init PROJECT
lesr resolve PROJECT IDENTIFIER
lesr inspect PROJECT UID
lesr query PROJECT --kind software_requirement
lesr context build PROJECT coding --target UID
lesr workspace open PROJECT DELEGATION_UID
lesr approval keygen ACTOR_UID "Reviewer" --role technical
lesr projection rebuild PROJECT
lesr mcp serve PROJECT
```

Human approval signing is deliberately CLI-only. MCP exposes versioned Resolve,
Inspect, Query, Context, Workspace, Governance and Compliance capabilities but
never arbitrary file, SQL, shell or private-key operations.

## Compatibility and recovery

v1 does not preserve the old YAML, CLI or MCP contract and does not ship a legacy
migration tool. The untouched MVP is recoverable at Git tag
`legacy-mvp-v0.1.0`. P1-P5 decision reports remain in `docs/prototype-results`;
the disposable prototype package has been removed after its invariant tests were
moved into the production suite.

P6 interoperability, UI, Chinese-specific tokenization, general plugin sandbox,
SHACL/Rego execution and Claude Code re-validation remain explicit deferred work.
