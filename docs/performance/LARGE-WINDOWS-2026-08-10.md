# Large Layer-1 semantic-kernel measurement — Windows — 2026-08-10

- Dataset: 100,000 Objects / 500,000 Revisions / 1,000,000 Relations.
- Semantics: exact Relation Type binding, Formal Trace, immutable Graph Snapshot,
  Configuration and Effective Model hashes enabled; no sampling or disabled feature.
- Samples: 10 warm-ups and 100 measured Context Manifest calls.
- Dataset/Graph construction: 119.446989 s.
- Context Manifest P95: 0.162790 s.
- Python: 3.12.13.
- System: Windows 10 Enterprise LTSC 10.0.19044, NVMe local workspace.
- Result: completed within the 24 GiB process budget without semantic degradation.

This is the explicit large stress/trend result. It does not replace the frozen
Windows 11/32 GiB reference-machine record and carries no 3-second interactive gate.
It is not evidence for Projection, Rule compilation, Review, Apply, signing, HTTP or
Baseline latency.
