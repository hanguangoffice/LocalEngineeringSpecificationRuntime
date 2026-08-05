# LESR Runtime 1.0.0rc1

Local Engineering Specification Runtime (LESR) is a local, single-user semantic
runtime for governed engineering specifications. Git commit trees are the authority;
SQLite/FTS5 is a disposable projection. The requirements authority is
`LESR_Solution_Design_Baseline_v1.0/`, while
`docs/LESR_Codex_Construction_Spec_v1.0.md` freezes the implementation contract.

This branch is the external-review candidate. Architecture validation, feature
implementation, integration, and release qualification are reported separately in
`docs/gates/`. The recovery point for the previous runtime is `runtime-0.5.0a2`.

## Runtime model

The 1.0 runtime separates Logical Objects, immutable Revisions and Records,
versioned Relation Assertions, exact Profile/Workflow/Relation Type revisions,
configuration-bound Graph Snapshots, typed rules, Working Copies, reviewed Candidate
Revisions, signed approvals, atomic semantic transactions, and Baselines.

There is no implicit `current`: evaluation requires an exact Configuration, Effective
Model, Canonical Commit, and Evaluation Time. External endpoints are never resolved
over the network during evaluation. Candidate Apply recomputes governance and rule
validation at the Git transaction boundary before an expected-old-value ref update.

## Development and release gates

```powershell
py -m uv sync --all-extras
py -m uv run python scripts/verify_baseline_manifest.py
py -m uv run python scripts/verify_construction_schemas.py
py -m uv run pytest
py -m uv run ruff check .
py -m uv run mypy src
py -m uv build --wheel --sdist --out-dir release-dist
py -m uv run python scripts/verify_distribution.py release-dist
```

CI runs on Python 3.12 for Windows and Ubuntu. It verifies the 81-entry baseline
Manifest, all construction schemas, deterministic serialization, the fixed small
performance dataset, HTTP/Playwright UI flow, and isolated wheel/sdist installation.
The medium and large performance protocols are fixed in `docs/performance/README.md`.

## Product entry points

```powershell
lesr init PROJECT
lesr capabilities
lesr resolve PROJECT IDENTIFIER
lesr inspect PROJECT UID
lesr query PROJECT --kind software_requirement --text reconnect
lesr context build PROJECT TASK CONFIGURATION_UID ACTOR_UID --target UID
lesr workspace open PROJECT DELEGATION_UID ACTOR_UID IDEMPOTENCY_KEY
lesr workspace propose PROJECT WORKSPACE_UID BASE ACTOR_UID DELEGATION_UID KEY operation.json
lesr review-package PROJECT WORKSPACE_UID BASE CONFIGURATION_UID ACTOR_UID DELEGATION_UID KEY
lesr approval keygen ACTOR_UID "Reviewer" --role technical
lesr approval sign TRUST.json PACKAGE.json technical
lesr apply PROJECT WORKSPACE_UID BASE ACTOR_UID DELEGATION_UID KEY operation.json
lesr projection rebuild PROJECT
lesr mcp serve PROJECT
lesr web PROJECT
```

`lesr init` creates only a format-1.0 repository Manifest. Governed resources,
Configuration, trust records, and delegations must be supplied through reviewed
Canonical State; a missing 1.0 Manifest is rejected rather than treated as a legacy
repository. Private-key signing is never available through MCP. The MCP adapter
advertises only tools it actually exposes; admin maintenance remains CLI/local UI only.

The Web UI binds to `127.0.0.1`, has no CDN or Node build, and uses a one-time launch
token, idle locking, Host/Origin/CSRF checks, and a short-lived signer broker. Windows
keys use DPAPI; Linux prefers Secret Service; the fallback is an scrypt/AES-GCM
encrypted PKCS#8 file and never plaintext.

## Compatibility and deferred scope

This is a breaking upgrade. It does not migrate the 0.5 Canonical State, Workspace,
YAML, CLI, or MCP contracts. ReqIF, SARIF, Excel, Codebeamer, OSLC, OCR,
Chinese-specific tokenization, a general plugin sandbox, SHACL/Rego execution,
multi-repository operation, and multi-user service deployment remain deferred.

Local rights-cleared Markdown/PDF import produces reviewable Workspace candidates with
provenance. Restricted source documents and extracted standards text are not committed.
