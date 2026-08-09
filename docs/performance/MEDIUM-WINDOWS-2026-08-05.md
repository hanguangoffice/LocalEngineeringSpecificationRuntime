# Medium Layer-1 semantic-kernel measurement — Windows — 2026-08-05

- Dataset: 10,000 Objects / 50,000 Revisions / 100,000 Relations.
- Semantics: exact pinned Relation Type Revision, complete Formal Trace credit checks,
  immutable Graph Snapshot, Configuration and Effective Model hashes enabled.
- Samples: 10 warm-ups and 100 measured Context Manifest calls.
- Re-run 2026-08-10 dataset/Graph construction: 11.844956 s.
- Re-run 2026-08-10 Context Manifest P95: 0.016315 s.
- Python: 3.12.13.
- Machine: Intel Core i7-12700H (14 cores/20 logical processors), 16 GiB RAM,
  NVMe SSD, Windows 10 Enterprise LTSC 10.0.19044.
- Cache: hot in-memory graph; cold Projection Build is not included.

This local machine has less RAM and an older Windows version than the frozen reference
condition, so this result is conservative supporting evidence rather than a replacement
for the Windows 11/32 GiB release record. Cross-platform functional gates run separately
in CI. This is a Graph/Context kernel microbenchmark: it does **not** measure Git,
Projection, Rule compilation, Review, Apply, signing, HTTP, or Baseline latency and must
not be quoted as end-to-end product performance.
