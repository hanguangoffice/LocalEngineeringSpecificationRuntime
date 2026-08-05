# Design Baseline v1.0 acceptance evidence

Runtime maturity is `0.5.0a2`; this table tracks implementation evidence against
the design baseline and does not declare production certification.

| Area | Implemented evidence | Gate |
|---|---|---|
| A. Positioning | Git is authoritative; Profile/Rule decisions are deterministic; import/projection are non-authoritative. | E2E, import and projection tests |
| B. Identity | UUIDv7 Logical Object/Revision separation, Alias, Fragment, External Identity and lineage datasets. | `test_v1_semantic.py` |
| C. Relations | Independent Relation revisions, four bindings, formal trace-credit rules, lineage and referential closure. | semantic and Git tests |
| D. Rules/Profiles | Persistent Rule Definition to typed AST compiler, three-valued applicability, units, aggregates, bounded paths, all fixture classes, preserved evaluator kind, authority ordering and Effective Model hash. | `test_v1_rules.py`, `test_v1_profiles.py` |
| E. Configuration/Context | Explicit Configuration UID/actor, exact resolution, configured-relation filtering, Profile Context Policy, stale exclusion, negative context and fail-closed completeness. | `test_v1_context.py`, repository context path |
| F. Change/Approval | Recoverable Workspace refs, candidate Validation/Finding gates, system-derived canonical Review Package, canonical trust/delegation, complete Ed25519 binding, scoped approvals and CAS Apply. | approval, bootstrap, Git and governed E2E tests |
| G. Canonical state | Full-tree lineage and reference integrity, immutable paths, Applied Change, used/generated provenance, hash-chain audit anchors, atomic ref advance and disposable typed projection. | fault-injection Git tests |
| H. Security | AI self-approval, rogue trust, expired/revoked/tampered signatures, scope/path escape, adapter bypass and schema bypass fail closed. | approval, bootstrap, Git and E2E tests |
| I. Adapter gates | MCP domain isolation, real stdio initialization, explicit context, FTS/graph query, structured errors and no arbitrary file/SQL/shell/private-key tool. | `test_v1_contracts.py` |

Manifest 81/81, frozen schema examples, deterministic serialization, pytest,
Ruff, strict mypy, exact source/wheel parity and installed-wheel import are
mandatory CI gates. Claude Code and P6 remain deferred; Codex/stdio probe status
must be recorded in the PR rather than represented as third-party certification.
