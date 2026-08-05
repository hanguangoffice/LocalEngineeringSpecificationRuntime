# P3 Configuration and Context

## Question and hypothesis

Can LESR resolve exact effective revisions and produce a context contract whose
mandatory set is deterministic, complete under the model and free of stale
revisions? Explicit configuration priority plus auditable selection rules is
expected to outperform implicit "current" and similarity-first retrieval.

## Scope and dataset

The resolver implements pinned, workspace, configuration, variant/time and
low-risk latest-approved resolution. The planner covers invariants, direct
mandatory/conditional relations, effective rules, deviations, sensitivity,
token budget, negative context and completeness. Five required task types are
executed over a versioned MQTT/CAN-style synthetic graph.

## Measurements and results

- Mandatory recall: 100% for all five gate tasks.
- Stale revision inclusion: zero; excluded revisions appear in Negative Context.
- Ambiguous resolution: `INDETERMINATE`, never implicit latest.
- High-risk fallback: rejected.
- Budget below the mandatory set: mandatory material remains visible and the
  contract reports `INCOMPLETE_BUDGET`.
- Every included mandatory item has a target, relation, invariant or rule reason.

## Failure modes

The prototype does not yet cover multi-baseline composition, temporal overlap
resolution, variant-expression compilation, security redaction substitution or
large-graph performance. A missing configuration is intentionally partial or
indeterminate instead of being repaired heuristically.

## Decision and reversal cost

P3 passes. Keep explicit Evaluation Context, deterministic mandatory selection,
negative context and completeness as domain invariants. Storage/index choices
remain reversible because the planner consumes resolved domain resources.

## Code to keep / delete

Keep resolution precedence tests, five task scenarios and completeness tests.
Replace prototype in-memory scans with a projection-backed domain port only
after P4 establishes the canonical commit boundary.

## Open issues

Finalize variant DSL, temporal selection, configuration-closure Profile rules,
sensitivity transformations and performance targets in the final construction
specification.
