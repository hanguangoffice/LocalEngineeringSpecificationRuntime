# Gate 1 — Profile Semantic Kernel

- Contract version: `1.0.0`
- State: `PASS`

The normative order is fixed to Foundation → Domain → Industry → Organization →
Project. Mapping Packs and Configuration Tailoring Overlays are independent
resources and never acquire normative precedence by appearing in that stack.

Kind, Facet, Relation Type, and Workflow are immutable, content-addressed
Revisions. Relation Type contains only direction, endpoint compatibility, Binding,
workflow, Core Role, and grantable Formal Trace categories; cardinality and graph
requirements remain Rule concerns. Lifecycle projection consumes one exact Workflow
Revision and has no fixed domain-state enum.

`EffectiveModelCompiler` sorts every input and emits stable selection, source,
authority, conflict explanation and Model Hash. `replace` is rejected unless the
target declares itself replaceable, caller authority is sufficient, and both
compatibility and impact evidence hashes are fixed. `tailor` is accepted only from
a Configuration Overlay with an explicit boundary.

Verification randomizes Profile and definition load order across deterministic
fixtures. Failure fixtures cover missing definitions, duplicate extension,
non-narrowing refinement, Profile-level tailoring, unauthorized replacement, and
invalid overlay operations. Passing this Gate does not claim graph evaluation or
Working Copy integration; those belong to Gates 2 and 3.
