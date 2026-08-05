# Gate 3 — Graph, Rule, Validation, Context and Impact

- Contract version: `1.0.0`
- State: `PASS`

All semantic reads now consume an immutable, content-hashed Graph Snapshot fixing
Configuration, Canonical Commit, Effective Model, optional Workspace/Checkpoint,
explicit Evaluation Time, selected Revisions, Relation Revisions, Candidate Overlay
and unresolved external endpoints. Candidate nodes cannot appear without the exact
overlay identity. External endpoints are either pinned imported snapshots or
`INDETERMINATE`; evaluation performs no network lookup.

The pure evaluator grants Formal Trace only when Relation Type, direction,
Kind/Facet endpoints, Binding, asserted/imported provenance, active lifecycle and
category all agree. The attack matrix rejects Proposed, Inferred, Fragment,
Retired, reversed, wrong endpoint, Binding and category cases. Bounded Relation Path
supports direction, sequence, alternatives, repetition through depth 1–16, cycle
policy, endpoint filters, Binding and Formal Trace requirements.

The frozen Rule operator vocabulary covers field, relation, graph, lifecycle,
process/evidence, time, Aggregate and fixed observation families. Real Aggregate
evaluation retains decimal strings and three-valued unknowns. Context separates
Manifest, Focused Read and persistent Deep Trace; FTS candidates are Supporting
only, and absence of a mandatory relation yields `INCOMPLETE_MISSING_RELATION`.
Impact reports paths and governed resource classes and cannot claim `COMPLETE` at a
depth limit, with unresolved external state, Profile conflict or indeterminate
Configuration.

Gate tests cover the attack matrix, direction/path behavior, Candidate Overlay,
Aggregate unknowns, Context missing edges and every Impact completeness precedence.
