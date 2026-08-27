# Gate 9 semantic-kernel performance evidence — Windows — 2026-08-27

These are Layer 1 semantic-kernel measurements, not Projection, governed transaction or
product E2E measurements. Formal graph traversal, exact Revision selection and Context
planning remained enabled; `semantics_disabled` was empty.

| Tier | Objects | Revisions | Relations | Build | Context Manifest P95 |
|---|---:|---:|---:|---:|---:|
| Medium | 10,000 | 50,000 | 100,000 | 10.902929 s | 0.016513 s |
| Large | 100,000 | 500,000 | 1,000,000 | 136.172911 s | 0.201070 s |

- Python: 3.12.13.
- Platform reported by Python: `Windows-10-10.0.19044-SP0`.
- Each Context value used 10 warm-ups and 100 measured samples.
- Large used the complete generated graph; it did not sample or reduce the one-million
  Relation dataset.

Stable 1.0 still requires separately labelled Layer 2 Medium, Layer 3 Medium and Layer 4
critical-interaction evidence. These Layer 1 results must not be quoted as those product
measurements.
