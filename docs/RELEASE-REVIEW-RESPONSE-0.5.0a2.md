# LESR 0.5.0a2 release-review response

This response addresses the substantive findings in the 0.5.0a1 release review.
Items explicitly removed by the intermediary as ZIP hand-off misunderstandings are
not treated as product defects and did not trigger repository cleanup work.

## Release decision

The runtime remains an Alpha review candidate. The Design Baseline is still 1.0;
runtime version 0.5.0a2 identifies the new implementation and wheel separately
from the reviewed 0.5.0a1 artifact.

## Closed blockers

- Rule/Profile governance is now a mandatory Apply gate. Callers cannot provide
  their own Effective Model hash, required roles, Validation list, Finding list or
  semantic operation list at Apply time.
- Validation Run, Validation Finding and Review Package are immutable schema-bound
  canonical resources. Apply reloads the checkpointed package, recompiles its
  exact Configuration/Effective Model, while the Git transaction boundary
  independently reproduces observations, findings, deviation suppression,
  blocking decisions and the run outcome before advancing the canonical ref.
- Git adapter calls cannot bypass authorization. The transaction engine verifies
  Canonical Trust, Delegation and complete Ed25519 attestations itself.
- CI distribution verification now checks a fresh wheel against every source byte,
  package metadata and the complete schema set, then installs and imports it in an
  isolated environment. Other LESR versions in the release directory are rejected.

## Other substantive closures

- Profile field symbols, units, review policies and context policies are executable;
  aggregate constraints and non-declarative evaluation kinds are represented by the
  runtime AST.
- Context requires an explicit Configuration UID/actor and uses only configured
  Relation revisions. Query supports FTS and bounded graph traversal.
- A public, one-time proof-of-possession bootstrap installs root trust and initial
  governance; the first Configuration has a separate signed initialization path.
- Approval signatures bind identity, role, issuance time and provenance. Review,
  validation, approval and transaction provenance are recoverable from Git.
- Canonical closure now validates revision/relation lineage, key/alias uniqueness,
  record subjects/supersession, trust/delegation references and governance evidence.
- Import preview requires rights/license metadata and uses source-hash-qualified
  Human Keys. Local evaluation documents remain uncommitted.

## Verification

The repository gates are: baseline Manifest 81/81, construction schemas,
deterministic serialization, pytest, Ruff, strict mypy, Windows/Ubuntu CI and
installed-wheel parity. P6, UI, OCR, specialist Chinese tokenization and Claude
Code re-validation remain explicitly deferred and are not claimed as complete.

The final local remediation run completed 68 tests, verified 24 frozen schemas and
all 81 baseline Manifest entries, and installed/imported a freshly built 0.5.0a2
wheel whose Python files match `src/` byte-for-byte. The GitHub Windows/Ubuntu
results remain an independent PR gate rather than a locally asserted result.
