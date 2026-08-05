# P4 Git Canonical State and Semantic Transaction

## Question and hypothesis

Can a Git commit tree be the authoritative state while a multi-resource Apply
is atomic, idempotent and recoverable on Windows? Git plumbing with a temporary
index and compare-and-swap `update-ref` should provide the required boundary.

## Scope and alternatives

The prototype writes snapshots, Applied Change, provenance, audit and
idempotency records into one candidate tree, then atomically advances the
canonical ref. It compares isolated commit-per-checkpoint refs with a persistent
workspace branch. SQLite is a delete-and-rebuild projection only.

## Measurements and results

- Multi-resource state becomes visible in one canonical ref advance.
- Failures after staging, before commit and before ref leave the old ref intact.
- A crash after ref advancement is recovered by idempotent retry.
- Same key/different transaction is rejected; stale base is rejected.
- Historical Revision paths cannot be overwritten.
- Projection failure leaves Git authoritative and a fresh SQLite projection can
  be rebuilt from the commit tree.
- Unicode and long canonical paths survive the Git plumbing path.
- Both checkpoint strategies are recoverable without publishing workspace state
  on the canonical branch.

## Failure modes

Actual antivirus/file-lock interference is environment-specific; the temporary
index cleanup and ref transaction were exercised, but production hardening still
needs process-level kill tests and repository maintenance policy. Cross-process
audit streaming is represented as a canonical audit anchor, not an external
append service.

## Decision and reversal cost

P4 passes. Use a temporary Git index plus `commit-tree` and expected-old-value
`update-ref`. Prefer a workspace ref/branch for active editing and reserve
isolated checkpoint refs for durable milestones. Applied Change need not be
one-to-one with fine-grained checkpoints. Reversal cost is moderate because the
domain transaction remains independent of Git command execution.

## Code to keep / delete

Keep fault-injection, idempotency, stale-base, immutable-history and projection
rebuild tests. Replace direct subprocess details behind a production Git port
after the final specification.

## Open issues

Define garbage collection, signatures, multi-worktree locking, external Git
reconciliation UX, audit anchoring policy and pack/ref retention before release.
