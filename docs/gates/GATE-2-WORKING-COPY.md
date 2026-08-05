# Gate 2 — Working Copy and Candidate State

- Contract version: `1.0.0`
- State: `PASS`

Workspace state is no longer an array of caller-authored Canonical Resource
operations. Each object has at most one active Working Copy containing exact base
Revision, Effective Model, Delegation, fields, Fragments, Relation proposals,
validation state, append-only edit log and deterministic Working State Hash.

The pure editor accepts only the nine frozen Edit Operation kinds. Checkpoints fix
base, aggregate state hash, edit scope, actor, validation summary, time, Workspace
Ref and a recoverable immutable Workspace snapshot. Submit creates a checkpoint,
formal-content Candidate Revisions, Relation Revisions, proposed lifecycle records
and a Semantic Diff, then makes both Workspace and Working Copies read-only.
Candidates remain under the Workspace Ref and are not promoted by type conversion;
only Gate 5 Apply can copy their immutable resources into the Canonical Tree.

Tests cover continuous editing, unique active copy enforcement, deterministic hash,
checkpoint serialization/recovery, base revision progression, candidate/diff
binding, and post-submit write rejection. Graph evaluation is intentionally absent
until Gate 3 consumes this exact Candidate State.
