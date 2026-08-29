# LESR architecture status

LESR is a local, single-repository, single-user semantic engineering control plane
for people and AI agents.
Git commit trees are canonical authority; SQLite/FTS5 and the task database are
rebuildable local runtime state. Domain services mediate every authoritative write.
CLI, MCP, and Web are adapters to one Capability Descriptor and do not embed a
second policy evaluator.

The normal product flow is goal-driven rather than operation-driven. A Mission
orchestrates Work Packages and specialist Agent Runs; Context, Working Copy,
validation, impact, rebase and Git transaction capabilities execute behind that
flow. Only policy-derived Decision Requests interrupt the user. The complete product
contract is in `AGENTIC-PRODUCT-CONTRACT.md`.

The zero-spec intake layer is deliberately pre-authority. It verifies and reads
licensed upstream Spec Kit/arc42 snapshots, preserves the user's statements,
selects a scenario pack, and creates editable Working Copies. It cannot publish
a Revision. Bootstrap, template selection and Context assembly are background
runtime work. Formal signing is used only when the effective Profile assigns a
human responsibility boundary.

The 0.5 operation-queue workspace and shallow relation validation are superseded.
The 1.0 dependency order is: frozen contracts; Profile semantic kernel; real
Working Copy and Candidate State; immutable Graph Snapshot and pure evaluation;
semantic rebase/reconciliation; review/approval/baseline governance; operations;
then the local Web product.

Status words are intentionally non-interchangeable:

- **Architecture Validated**: an experiment supports a design decision.
- **Feature Implemented**: production code and focused tests exist.
- **Integrated**: every authority boundary consumes the same implementation.
- **Release Gate Passed**: the versioned Gate report and all required suites pass.

Earlier P1–P5 prototype reports are architectural evidence only. In particular,
Bounded Path, Aggregate, Context completeness, Formal Trace, and client probes are
not release claims unless their corresponding 1.0 Gate report is `PASS`.
