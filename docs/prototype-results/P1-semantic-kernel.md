# P1 Semantic Kernel

## Question

Can the v1.0 identity, immutable revision, lifecycle, relation-binding, Facet,
Fragment and lineage invariants be represented without legacy `Artifact`
special cases?

## Hypothesis

Frozen typed models plus canonical JSON can express the stable kernel while
keeping storage and runtime technology reversible.

## Scope and dataset

The executable dataset contains 30 requirement/design/test objects, 20
MISRA-like rules, 20 CAN signals, and 10 change/deviation/evidence resources.
All content is synthetic. Tests cover aliases, fragments, lifecycle projection,
relation binding and formal trace credit. Split, consolidation and promotion are
represented through normal governed objects and lineage relation assertions.

## Alternatives

- UUIDv7 versus ULID for Internal UID.
- Canonical JSON versus canonicalized YAML for semantic hashing.
- Mutable aggregate records versus immutable Revision/Record models.

## Measurements and results

- Both UID candidates are time sortable and collision resistant for the gate.
- UUIDv7 wins because it uses a standardized 128-bit UUID representation and
  avoids a LESR-specific identifier parser.
- Canonical JSON wins for hashing because ordering and scalar encoding are
  unambiguous; YAML remains suitable for authored or presentation views.
- Lifecycle projection detects invalid record chains as `INDETERMINATE`.
- Proposed/inferred/fragment relations do not silently earn formal trace credit.

## Failure modes

UID and namespace federation, very large composite objects, and schema migration
remain outside P1. A frozen model alone is insufficient if callers can insert
mutable dictionaries, so semantic payload is represented as immutable typed
fields containing canonical JSON scalars/structures.

## Decision

P1 passes for the prototype scope. Use UUIDv7 and canonical JSON as the leading
P2-P5 candidates; do not freeze them for the final runtime until P4 Git and
interoperability consequences are measured.

## Reversal cost

Low: UID generation and serialization are behind functions and no public
long-term schema has been published.

## Code to keep / delete

Keep the invariant tests and dataset. Treat model classes as disposable until
the final construction specification is approved. Delete the legacy Artifact
inheritance model at final cutover.

## Open issues

Cross-repository UID collision handling, namespace URI syntax, Profile schema
migration and signed identity assertions remain for the final specification.
