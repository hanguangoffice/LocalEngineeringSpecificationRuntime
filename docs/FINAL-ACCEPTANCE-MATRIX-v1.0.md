# Design Baseline v1.0 acceptance evidence

Runtime maturity is `0.5.0a1`; this table tracks implementation evidence against
the design baseline and does not declare production certification.

| Area | Implemented evidence | Gate |
|---|---|---|
| A. Positioning | Git is authoritative; Profile/Rule decisions are deterministic; import/projection are non-authoritative. | E2E, import and projection tests |
| B. Identity | UUIDv7 Logical Object/Revision separation, Alias, Fragment, External Identity, lineage datasets. | `test_v1_semantic.py` |
| C. Relations | Independent Relation revisions, four bindings, formal trace-credit rules and referential closure. | semantic and Git tests |
| D. Rules/Profiles | Persistent Rule Definition → typed AST compiler, three-valued applicability, units, bounded paths, fixtures, authority partial order and effective-model hash. | `test_v1_rules.py`, `test_v1_profiles.py` |
| E. Configuration/Context | Explicit Evaluation Context, exact resolution, stale exclusion, mandatory recall, negative context and fail-closed completeness. | `test_v1_context.py`, repository context path |
| F. Change/Approval | Recoverable Workspace refs, immutable Review Package, canonical trust/delegation, DPAPI-protected signing key, multi-role scoped approvals and CAS Apply. | approval, Git and E2E tests |
| G. Canonical state | Full-tree candidate integrity, immutable paths, Applied Change, provenance, hash-chain audit anchors, atomic ref advance and disposable typed projection. | fault-injection Git tests |
| H. Security | AI self-approval, rogue request trust, expired/revoked/tampered signatures, scope escape, path escape and schema bypass fail closed. | approval, Git and E2E tests |
| I. Adapter gates | MCP domain isolation, real stdio initialization, structured errors and no arbitrary file/SQL/shell tool. | `test_v1_contracts.py` |

Manifest 81/81, frozen schema examples, deterministic serialization, pytest,
Ruff, strict mypy, source distribution and wheel content are mandatory CI gates.
Claude Code and P6 remain deferred; Codex/stdio probe status must be recorded in
the PR rather than represented as a third-party certification.
