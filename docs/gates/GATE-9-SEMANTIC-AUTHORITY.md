# Gate 9 — Single semantic authority and governance binding

- Candidate: `1.0.0rc4`
- Contract: LESR Canonical Format `1.0.0`
- State: `PASS`

## Closed findings

| RC3 re-audit finding | RC4 authoritative behavior | Executable evidence |
|---|---|---|
| Two non-equivalent Constraint evaluators | `evaluate_rule` only orchestrates applicability and enforcement; every Constraint is evaluated by `domain.evaluation.evaluate_constraint` against one frozen Graph Snapshot | `test_product_validation_accepts_a_valid_two_hop_graph_path`, quantity tests |
| Quantity values became indeterminate | Runtime values distinguish scalar, decimal quantity, timestamp, list, null, absent and unknown; unit conversion is performed by the same evaluator | `test_product_validation_uses_units_in_the_single_evaluator` |
| Deviation approval was presence-only | Deviation and Exception approvals bind exact governed hash, Revision, Rule, subject, model, type, authorized role, Ed25519 key, time and revocation state | Gate 9 attack matrix |
| Exceptions and normative conflicts were not active | Configuration selects Exception and conflict-resolution records; unresolved direct normative conflicts evaluate indeterminate | Gate 9 exception/conflict tests |
| Governance Findings had no closure evidence | Acknowledgement and Review Findings require a finding-specific signed human attestation before Apply | Gate 9 governance test and Git boundary recomputation |
| Configuration `git_commit` was self-inconsistent | Configuration now separates `base_commit` from a deterministic semantic `state_anchor`; Candidate selection is never represented as a self-referencing commit | state-anchor and Configuration tests |
| Profile compilation remained dual-track | The legacy `ProfileCompiler/ProfileRevision` implementation and schema are removed; product and Git boundaries accept only `NormativeProfileRevision` and `EffectiveModelCompiler` | construction schemas and Git tests |
| Baseline model/schema differed | Domain model, JSON Schema and Apply use `exact_revision_uids`, `exact_relation_revision_uids`, `state_commit` and the same Manifest hash | baseline round-trip and Web E2E |

## Failure modes retained by design

- Missing, expired, revoked, wrong-role or wrong-subject governance evidence fails closed.
- External endpoints are not resolved over the network during evaluation.
- Rule-governed Candidate state is rejected by the generic bootstrap transaction envelope and must use `apply_candidate`.
- Git Tag publication remains non-authoritative and rebuildable from the Baseline Manifest.

## Measurements

- Medium Layer 1: build `10.902929 s`; Context Manifest P95 `0.016513 s`.
- Large Layer 1: build `136.172911 s`; Context Manifest P95 `0.201070 s`.
- Full environment and evidence boundary: [`performance/GATE9-WINDOWS-2026-08-27.md`](../performance/GATE9-WINDOWS-2026-08-27.md).

## Commit scope

This Gate contains semantic-authority unification, governance binding, Configuration/Baseline
state anchoring, active-schema cleanup, product attack tests and release metadata only. It adds
no new UI or interoperability feature.
