# Design Baseline v1.0 acceptance evidence

Runtime integration candidate `1.0.0rc3` implements the local, single-repository, single-user
scope. This matrix records internal evidence for external review; it is not a claim of
independent certification or final `runtime-v1.0.0` release qualification.

| Area | Implemented evidence | Gate |
|---|---|---|
| A. Positioning | Git authority, Repository Manifest, explicit Capability Descriptor, non-authoritative imports/tasks/projection. | Gate 0, 6 |
| B. Identity | UUIDv7 Logical Object/Revision separation, Alias, Fragment, External Identity, split/merge/promotion lineage. | Gate 1–3 |
| C. Relations | Exact Relation Type revisions, four bindings, immutable assertions, formal-credit attack matrix, deterministic offline external endpoints. | Gate 1, 3 |
| D. Rules/Profiles | Normative stack separate from Mapping/Tailoring, typed compiler, three-valued applicability, units, aggregate/path constraints, all eight fixture classes, deterministic Effective Model. | Gate 1, 3 |
| E. Configuration/Context | Immutable Graph Snapshot identity/hash, Candidate Overlay, Manifest/Focused Read/Deep Trace separation, mandatory-edge failure, explicit completeness and Impact status. | Gate 2, 3 |
| F. Change/Approval | Per-object Working Copy, Candidate Revision, semantic diff, public three-way Rebase/Merge/Resolution/Reconciliation, stable review subject, comments/resolutions/conditions/revocations and scoped/quorum Ed25519 approval. | Gate 2, 4, 5 |
| G. Canonical state | Expected-old-value atomic ref advance, boundary governance and rule re-evaluation, idempotency, audit anchors, stale projection recovery, baseline state/tag separation. | Gate 5 |
| H. Operations/Security | Persistent local tasks, bundle backup/empty restore, dry-run migration/GC, encrypted private keys, one-shot broker, loopback token/cookie/CSRF/Origin/Host controls. | Gate 6, 7 |
| I. Adapters/Release | Capability-filtered MCP/CLI, real LocalRuntime Web adapter, full mutation UX, security tests, and a real Edit-to-Baseline Playwright flow. External re-review remains the RC-to-final release boundary. | Gate 6, 7 |

Mandatory internal gates are: baseline Manifest 81/81, 49 construction schemas and
examples, deterministic serialization, pytest, Ruff, strict mypy, HTTP/Playwright,
fixed small performance data, and exact wheel/sdist verification. Medium and large
performance measurements follow `docs/performance/README.md`. Claude Code and P3
interoperability remain deferred and are not represented as passing evidence.
