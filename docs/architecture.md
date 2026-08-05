# LESR 1.0 architecture status

LESR is a local, single-repository, single-user semantic engineering runtime.
Git commit trees are canonical authority; SQLite/FTS5 and the task database are
rebuildable local runtime state. Domain services mediate every authoritative write.
CLI, MCP, and Web are adapters to one Capability Descriptor and do not embed a
second policy evaluator.

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
