# LESR 1.0.0rc2 unified-runtime re-audit matrix

This matrix responds to `LESR_Runtime_1.0.0rc1_Independent_Reaudit_2026-08-05.md`.
The external report and restricted local evaluation corpus are not committed. Design
authority remains `LESR_Solution_Design_Baseline_v1.0/`; the historical
`runtime-v1.0.0` tag is immutable and is not treated as this build's version.

| Re-audit finding | Remediation in 1.0.0rc2 | Executable evidence |
|---|---|---|
| Two competing production services | `RepositoryDomainService` and its legacy E2E were removed. CLI, MCP and Web use `LocalRuntimeService`; an architecture test enforces the single facade. | `test_runtime_architecture.py` |
| Empty repository could not bootstrap | Public plan/sign/apply commands install the first human trust root, exact governance resources and initial Configuration with proof of possession. | `test_v1_bootstrap.py` |
| CLI lost Workspace and Review state between invocations | Open, edit, submission, Candidate, diff, graph, context, impact, validation and Review Package are checkpointed on Workspace refs and recovered strictly across service processes. | cross-process flow in `test_v1_bootstrap.py` |
| Product path did not use the new Profile kernel | Configurations select exact `NormativeProfileRevision` records. `EffectiveModelCompiler` fixes definition, Rule, workflow, context and review-policy revisions and rejects stale hashes/conflicts at the Git boundary. | Gate 1 tests and public bootstrap flow |
| Formal Trace was isolated from Apply | The integrated evaluator maps typed `RelationMinimum` to graph-native cardinality or Formal Trace credit, including direction, Binding, lifecycle and category; inapplicable rules remain inapplicable. | Formal Trace attack tests and integrated inferred-relation test |
| Lifecycle transition vanished at Apply | Candidate lifecycle records are typed `ImmutableRecord` values and are atomically written with candidate Revisions and Relations. Workflow revision, role, guard and evidence checks run before submit. | `test_runtime_integrated_apply.py` |
| Review evidence hashes had no recoverable documents | Semantic Diff, Graph Snapshot, Context Bundle, Impact Report and schema-valid Validation Run are persisted as immutable canonical resources. Approval provenance is persisted and the post-commit candidate is revalidated before ref advance. | public Apply/Baseline flow and candidate-integrity tests |
| Review policy was caller-authored | Apply and Baseline policies are selected only from the Configuration's Effective Model. Caller operation fields cannot weaken stage, role, quorum or independence. | `test_v1_bootstrap.py`, Gate 5 tests |
| Web signing deadlocked before Apply | Review Packages are resolved from verified Workspace checkpoints as well as Canonical State. The Web endpoint derives the signature stage from the package policy and rejects ambiguous/caller-authored roles. | Web security tests and cross-process package recovery |
| Traverse/Impact were placeholders | Both require Configuration UID and explicit Evaluation Time and consume a hashed Graph Snapshot. Incomplete Impact states remain explicit. | MCP contract and Gate 3 tests |
| Public Query bypassed projection | Query uses the rebuildable SQLite/FTS5 projection and rejects a stale source commit. | projection and architecture tests |
| Context ignored policy and had no Focused Read/Deep Trace | Effective Model Context Policy supplies invariants and mandatory predicates; manifests and snapshots are persisted, Focused Read enforces 100-resource/2 MiB limits, and Deep Trace is a persistent task. | Gate 3/6 and MCP contract tests |
| Task Store had no worker | `TaskWorker` claims, checkpoints, checks cooperative cancellation, persists results/failures, and resumes Deep Trace and large Impact work. | `test_gate6_operations.py` |
| Baseline command only calculated a hash | Prepare verifies complete Configuration, graph, validation, impact, context and Profile-derived governance; Apply revalidates at the Git boundary, atomically writes Manifest/evidence, and treats the optional tag as rebuildable. | cross-process Baseline flow in `test_v1_bootstrap.py` |
| Capability Descriptor overclaimed | CLI/MCP flags default to false and the catalog contains only callable public capabilities. Rebase/Merge/Resolution/Reconciliation and Review records now traverse the same production facade and are advertised only where callable. | capability/MCP and public merge tests |
| Resolve treated references as identities | Identity lookup now indexes only the primary identity fields for each resource type plus Human Key/Alias, never arbitrary referenced `*_uid` fields. | runtime identity implementation and Gate 1 identity tests |
| Playwright used an in-memory fake | Web security and Playwright instantiate the production runtime and a real Git/SQLite repository; the browser completes Edit, Review, one-shot Sign, atomic Apply and Baseline. | `test_gate7_playwright.py`, `test_gate7_web_security.py` |

## RC2 handoff boundary

This build is `1.0.0rc2`, not the final historical `runtime-v1.0.0` release tag.
All internal Gate 0-7 contracts are implemented and executable. RC2 is handed to the
two external reviewers for independent Baseline v1.0 reassessment; only confirmed
review corrections, release metadata and notes may change before final publication.

The local rights-cleared corpus remains ignored. No extracted standards text, PDF,
private key, projection database or local test document is committed.
