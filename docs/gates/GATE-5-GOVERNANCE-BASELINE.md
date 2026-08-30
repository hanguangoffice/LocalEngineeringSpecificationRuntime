# Gate 5 — Review, Approval, Apply and Baseline

- Contract version: `1.0.0`
- State: `PASS`

Review Comment, Comment Resolution, Condition Satisfaction and Approval Revocation
are immutable records with UUIDv7 identity and explicit references. Comment Resolution
references `comment_uid`; Condition Satisfaction retains the original condition value
and evidence; Approval Revocation references the approval UID. Review Policy defines
Quorum separately by stage and role. Partial Approval is valid only when the union
equals the complete Candidate Scope; Conditional Approval remains inert until each
condition has an evidence-bearing Satisfaction record.

`GovernanceEvaluator.evaluate` is a pure function accepting the exact Review Package
and governance records. It verifies Ed25519 signatures, Package/Model binding,
expiry, trusted role/key/revocation, preparer independence, comment closure,
conditions, scope and every stage quorum. Service and Git Transaction integration
call this same function; no caller-authored summarized result is trusted.

Pre-Apply revocation invalidates the Approval immediately. Post-Apply/Baseline
revocation preserves history and emits an Assurance Finding plus Revalidation
Trigger. Baseline preparation requires Complete Configuration, passed Validation
and complete Impact before review. The Manifest fixes the prior engineering
`state_commit`; its containing commit is distinct, and a Git Tag is only a
rebuildable publication aid. Tag failure is `pending_rebuild` and never rolls back
Canonical State.

Tests cover combined partial scope, multi-reviewer quorum, conditions, open comments,
revocation on both sides of Apply and baseline completeness prerequisites.

This is historical Gate evidence for Contract 1.0. Later Runtime simplification removed
redundant per-record auxiliary hashes without changing the Review Package evidence
binding or Ed25519 approval boundary; see `../integrity-boundaries.md`. Current release
status must be established by the current version's own verification record.
