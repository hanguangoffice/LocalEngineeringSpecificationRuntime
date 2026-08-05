# LESR runtime 1.0.0 (reconstruction in progress)

Local Engineering Specification Runtime is a Git-backed local semantic runtime
for engineering specifications. `LESR_Solution_Design_Baseline_v1.0/` is the
requirements authority and `docs/LESR_Codex_Construction_Spec_v1.0.md` is the
frozen implementation contract. Runtime maturity and design-baseline version are
deliberately separate. The 0.5 recovery point is `runtime-0.5.0a2`; this branch
implements the Gate 0–7 product contract and does not claim release qualification
until every versioned Gate report is `PASS`.

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
lesr query PROJECT --kind software_requirement --text reconnect
lesr trace PROJECT UID --max-depth 4
lesr context build PROJECT coding CONFIGURATION_UID ACTOR_UID --target UID
lesr workspace open PROJECT DELEGATION_UID ACTOR_UID IDEMPOTENCY_KEY
lesr workspace propose PROJECT WORKSPACE_UID BASE ACTOR_UID DELEGATION_UID KEY operation.json
lesr review-package PROJECT WORKSPACE_UID BASE CONFIGURATION_UID ACTOR_UID DELEGATION_UID KEY
lesr approval keygen ACTOR_UID "Reviewer" --role technical
lesr projection rebuild PROJECT
lesr mcp serve PROJECT
```

Human approval signing remains interactive and unavailable to MCP/AI. Trusted public keys and scoped
Delegation Grants are established through the one-time `bootstrap` command; an
optional signed governance bundle installs the initial Rule/Profile model, followed
by the separately signed `init-configuration` command. Request-supplied trust records
cannot authorize an Apply. MCP exposes versioned Resolve,
Inspect, Query, Context, Workspace, Governance and Compliance capabilities but
never arbitrary file, SQL, shell or private-key operations.

`review-package` is not a JSON hashing helper. It evaluates the exact checkpointed
Workspace using a Canonical Configuration and Profile policy. `apply` accepts the
resulting Package UID and human approval files; it does not accept caller-authored
operations, roles, findings or model hashes.

## Compatibility and recovery

v1 does not preserve the old YAML, CLI or MCP contract and does not ship a legacy
migration tool. The untouched MVP is recoverable at Git tag
`legacy-mvp-v0.1.0`. P1-P5 decision reports remain in `docs/prototype-results`;
the disposable prototype package has been removed after its invariant tests were
moved into the production suite.

P3 interoperability, multi-user service operation, Chinese-specific tokenization,
general plugin sandbox, and SHACL/Rego execution remain explicit deferred work.

Local rights-cleared PDF/Markdown import only creates reviewable Workspace
candidates with page/section provenance. Encrypted or restricted PDFs are
refused; source documents and extracted standard text are not committed.
