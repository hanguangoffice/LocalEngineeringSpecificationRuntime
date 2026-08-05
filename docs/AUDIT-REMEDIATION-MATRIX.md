# LESR 0.5.0a2 audit remediation matrix

This matrix responds to `LESR_1.0.0_Audit_Report.md` without copying the external
report or licensed test documents into the repository. Design authority remains
`LESR_Solution_Design_Baseline_v1.0/`. The historical `v1.0.0` tag is not
rewritten; runtime maturity is now versioned independently.

| Audit finding | Remediation | Executable evidence |
|---|---|---|
| Pydantic models and JSON Schemas described different documents | Canonical DTO fields now map one-to-one to v1 schemas; model dumps are validated by the frozen schema catalog. | `test_canonical_models_round_trip_through_frozen_schemas` |
| Rule storage model and runtime AST were incompatible | `RuleDefinition` is the persistent DTO; `RuleCompiler` explicitly produces a typed `RuleAST`, runs all eight fixture classes and rejects unknown paths, invalid units and executable AI semantics. | `test_v1_rules.py` |
| Canonical JSON admitted float, NaN and Infinity | Recursive validation rejects every floating-point value; quantities use decimal strings and units. | `test_canonical_json_rejects_all_floating_point_values` |
| Profile/effective model was not integrated | `ProfileCompiler` resolves exact rule revisions, verifies authority as a partial order, compiles fixtures, detects direct conflicts and emits a deterministic effective-model hash. Configured repository contexts compile the selected profiles and reject stale hashes. | `test_v1_profiles.py` |
| Profile symbols, units and policies were inert | Structured resource fields and unit declarations now form the compiler symbol table; Context and Review policies are compiled into the Effective Model and enforced by repository capabilities. | `test_profile_supplies_field_symbols_for_common_field_rules`, governed E2E test |
| Aggregate schema and runtime diverged | The typed AST now implements bounded count/sum/minimum/maximum aggregate constraints and validates quantity dimensions. | `test_v1_rules.py` aggregate fixture |
| Evaluation kind was discarded | `RuleAST` preserves the evaluation specification. External, registered, human and AI evaluation fail closed as `not_evaluated` unless exact external evidence is supplied; advisory AI cannot become formal compliance evidence. | external-evaluation tests in `test_v1_rules.py` |
| Apply accepted caller-defined empty validation | Review preparation now resolves an exact Canonical Configuration, recompiles the Effective Model, evaluates the checkpointed candidate, emits immutable Validation Run/Findings, derives roles from Profile policy and creates the Review Package. Apply accepts only its package UID; the Git transaction boundary independently reproduces rule observations, findings, deviation suppression, blocking decisions and the run outcome before advancing the ref. | `test_profile_governed_review_validation_and_apply_are_not_caller_defined`, `test_git_boundary_recomputes_validation_outcome` |
| Explicit missing pinned revision fell through to a different revision | Bound resolution now stops with `INDETERMINATE`; it never tries a lower-priority selector after a specified binding is unavailable. | `test_missing_explicit_revision_never_falls_back_to_configuration` |
| Confidential mandatory context could be omitted while reporting complete | Mandatory sensitivity removal returns `incomplete_confidentiality` and records negative context. | `test_mandatory_sensitivity_omission_is_never_reported_complete` |
| Repository service inherited an in-memory fake | `RepositoryDomainService` implements the domain port directly, reads one exact canonical commit, uses SQLite structured projection for query, real Effective Resolution for context, recoverable workspace refs and completed task records. No-project MCP startup fails instead of serving synthetic data. | `test_v1_e2e.py`, `test_v1_contracts.py` |
| SQLite projection was a document dump | Projection now has source metadata, typed resources, aliases, relations and FTS; Query performs FTS discovery and exposes bounded relation traversal while the projection remains disposable. | projection rebuild and MCP contract tests |
| Git operations could write arbitrary JSON/path combinations | Every operation is restricted by operation/resource type, exact identity-derived path, JSON Schema, document hash, immutability and full candidate closure. Closure covers revision/relation lineage, namespace keys, aliases, records, trust issuers/revocation, validation and review references. | Git integrity and attack tests |
| Workspace state was not recovered | Workspace refs are enumerated and latest checkpoints recovered on service startup; applied state receives a final checkpoint. | `test_both_checkpoint_strategies_are_git_recoverable` |
| Trust checks could be bypassed by calling the Git adapter | Trust, delegation and Ed25519 verification now execute at the Git semantic-transaction boundary. An empty repository permits only the explicit proof-of-possession root bootstrap; the public CLI can install initial Rule/Profile governance and the first Configuration without exposing signing through MCP. | `test_public_bootstrap_installs_root_governance_and_initial_configuration`, Git tests |
| Delegation validation only checked a non-empty string | Canonical grants bind principal, workspace, base ancestry, operation, resource scope, expiry, limits and conservative stop conditions. | repository E2E security scenario |
| Approval did not enforce roles, scope or conditions | All Profile-derived Review Package roles need canonical-key signatures; affected resources must be covered; unresolved conditions fail closed; AI attestations fail. The signature also binds approval UID, actor/role, issuance time and provenance UID. | approval tamper and governed E2E tests |
| Local signing key was plaintext base64 | Windows key material is protected with current-user DPAPI; non-Windows fallback requires user-only filesystem protection. | `test_ed25519_approval_binds_package_model_scope_and_role` |
| Provenance/audit anchors were skeletal | Applied changes retain operation/approval hashes; provenance separates used/generated UIDs and records performed-by, tool identity, Review Package, Validation Runs and Context hash; audit anchors form a verifiable hash chain. | `verify_audit_chain` and governed E2E assertions |
| Import workflow was not a canonical v1 workflow | Markdown and rights-cleared text PDF preview require rights/license declarations and emit only Workspace operations with collision-resistant source-hash keys, real timestamps and source/page anchors. Encrypted PDFs are refused without a decrypt attempt. | import and local-corpus tests |
| Wheel did not match source | CI builds into a fresh directory; verification rejects other versions, compares every packaged Python file byte-for-byte with `src`, verifies metadata/schema sets and imports the installed wheel in an isolated environment. | `scripts/verify_distribution.py` on Windows and Ubuntu |
| Context inferred one repository-wide configuration | Context requires an explicit Configuration UID and actor, filters Relation revisions to that snapshot, uses Profile Context Policy and reports confidentiality/budget/model incompleteness. | context tests and governed service implementation |
| Service idempotency and operation limits were inconsistent | Workspace open/propose persist request hashes; Apply checks canonical idempotency before stale-base processing; limits count the exact checkpointed operation set once. | workspace and governed E2E replay tests |
| Capabilities advertised operations that were absent | Repository capability negotiation lists only implemented calls. The adapter-only in-memory double remains test-only. | `test_v1_contracts.py` |
| `1.0.0` overstated runtime maturity | Package/runtime is `0.5.0a2`; design baseline remains `1.0`; documentation states that this is a review candidate. | wheel metadata test and README |

## Local corpus decision

The untracked `测试文档/` corpus is intentionally ignored by Git. Three selected
pages of the locally supplied, unencrypted ASPICE-like document exercise page
anchors and schema-valid candidates. The encrypted MISRA source is tested only
for fail-closed refusal; MISRA-like executable-rule tests use synthetic content.
No extracted standard text, PDF, key material or projection database is committed.

## Deferred scope

P6 cross-vendor interoperability, UI, OCR, Word/Excel layout recovery,
Chinese-specific FTS tokenization, general plugin sandboxing and executable
SHACL/Rego backends remain outside this remediation. They are not represented as
implemented capabilities and do not weaken P1–P5 fail-closed behavior.
