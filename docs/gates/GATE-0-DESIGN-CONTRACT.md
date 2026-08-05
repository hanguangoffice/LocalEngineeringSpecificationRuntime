# Gate 0 — Design freeze and contracts

- Contract version: `1.0.0`
- State: `PASS`
- Scope commit: Gate 0 commit on `codex/lesr-runtime-1.0`

## Result

The repository authority boundary now requires `.repository-manifest.json` in the
canonical root. The manifest fixes canonical format `1.0.0`, the complete Schema
Catalog, the shared CLI/MCP Capability Descriptor and the deliberate break from
0.5. A missing manifest is rejected as `LESR-MANIFEST-MISSING`; there is no
implicit upgrade path.

The status vocabulary for this programme is exactly `PLANNED`, `IN_PROGRESS`,
`PASS`, `FAIL`, and `DEFERRED`. Architecture experiments, implemented features,
integrated features, and passed release gates are reported independently.

## Verification and measurements

- Every catalogued Draft 2020-12 Schema is loaded, reference-resolved, and checked.
- Repository initialization writes a byte-deterministic manifest and validates it
  on every subsequent initialization.
- The Capability Descriptor has no nonexistent suggested capability and prevents
  MCP publication of administrative or private-key operations.
- Canonical JSON continues to reject binary floating-point values.

## Failure modes exercised

- missing manifest (0.5 repository);
- changed canonical/runtime version;
- changed or unsorted Schema Catalog;
- changed capability surface;
- invalid manifest self-hash;
- undeclared suggested capability.

## Retained limitations

P3 interoperability, multi-user service operation, plugin sandboxing, specialized
Chinese tokenization, SHACL/Rego execution, and external network resolution remain
`DEFERRED`. Passing this Gate is a contract freeze, not a claim that Gates 1–7 are
implemented or release-qualified.
