# LESR 0.5.0a1 audit remediation matrix

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
| Explicit missing pinned revision fell through to a different revision | Bound resolution now stops with `INDETERMINATE`; it never tries a lower-priority selector after a specified binding is unavailable. | `test_missing_explicit_revision_never_falls_back_to_configuration` |
| Confidential mandatory context could be omitted while reporting complete | Mandatory sensitivity removal returns `incomplete_confidentiality` and records negative context. | `test_mandatory_sensitivity_omission_is_never_reported_complete` |
| Repository service inherited an in-memory fake | `RepositoryDomainService` implements the domain port directly, reads one exact canonical commit, uses SQLite structured projection for query, real Effective Resolution for context, recoverable workspace refs and completed task records. No-project MCP startup fails instead of serving synthetic data. | `test_v1_e2e.py`, `test_v1_contracts.py` |
| SQLite projection was a document dump | Projection now has source metadata, typed resources, aliases, relations and FTS; it remains disposable and is rebuilt after failure. | `test_projection_failure_does_not_rollback_and_projection_rebuilds` |
| Git operations could write arbitrary JSON/path combinations | Every operation is restricted by operation/resource type, exact identity-derived path, JSON Schema, document hash, immutability and post-state referential closure before the atomic ref update. | `test_path_escape_schema_bypass_and_ai_approval_are_rejected` |
| Workspace state was not recovered | Workspace refs are enumerated and latest checkpoints recovered on service startup; applied state receives a final checkpoint. | `test_both_checkpoint_strategies_are_git_recoverable` |
| Trust records came from the Apply request | Approval verification only searches exact Canonical State for actor/key trust. A valid request-supplied rogue trust record remains unauthorized. | `test_repository_capability_apply_requires_valid_human_signature` |
| Delegation validation only checked a non-empty string | Canonical grants bind principal, workspace, base ancestry, operation, resource scope, expiry, limits and conservative stop conditions. | repository E2E security scenario |
| Approval did not enforce roles, scope or conditions | All Review Package roles need canonical-key signatures; affected resources must be covered; unresolved conditions fail closed; AI attestations fail. Attestations are stored as immutable canonical resources. | approval and E2E security tests |
| Local signing key was plaintext base64 | Windows key material is protected with current-user DPAPI; non-Windows fallback requires user-only filesystem protection. | `test_ed25519_approval_binds_package_model_scope_and_role` |
| Provenance/audit anchors were skeletal | Applied changes retain operation/approval hashes, provenance carries responsible actor, tool, delegation and source UIDs, and audit anchors form a verifiable hash chain. | `verify_audit_chain` assertion in `test_v1_git.py` |
| Import workflow was not a canonical v1 workflow | Markdown and rights-cleared text PDF preview emit schema-valid Logical Object and Revision Workspace operations with source hash and section/page anchors; import never writes canonical state. Encrypted PDFs are refused without a decrypt attempt. | `test_v1_markdown.py`, `test_local_pdf_corpus.py` |
| Capabilities advertised operations that were absent | Repository capability negotiation lists only implemented calls. The adapter-only in-memory double remains test-only. | `test_v1_contracts.py` |
| `1.0.0` overstated runtime maturity | Package/runtime is `0.5.0a1`; design baseline remains `1.0`; documentation states that this is a review candidate. | wheel metadata test and README |

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
