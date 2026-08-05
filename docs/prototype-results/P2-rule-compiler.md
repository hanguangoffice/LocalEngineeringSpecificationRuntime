# P2 Rule Compiler

## Question and hypothesis

Can user-approved rule text be compiled into a closed, typed, deterministic and
explainable representation without executing Profile-supplied code? The
hypothesis is that a LESR-owned AST, validated by schemas and fixtures, is a
safer authority than loading executable policy snippets.

## Scope and dataset

The prototype separates rule source, AST, evaluation environment and decision.
It implements Kleene three-valued applicability, absent/null/unknown/value,
typed quantities and dimensions, bounded relation constraints, modality,
operation-specific enforcement, exception, deviation and direct conflict
detection. The reference rule carries all eight required fixture categories.

## Alternatives and measurements

- Custom closed AST with JSON-schema-compatible data is the authoritative
  candidate.
- SHACL and Rego projections were limited to inspection/interoperability; they
  intentionally do not execute inside a Profile.
- Measurements are deterministic AST hashes, fixture coverage/pass rate,
  diagnostic stability and explanation-tree completeness.

## Results and failure modes

P2 passes its prototype gate. Unknown applicability never becomes not
applicable; incompatible units become evaluator errors; unbounded relation
paths are rejected; exception, deviation and conflict remain distinct. The
prototype does not yet implement the full aggregate language, authority DAG,
temporal operators, validator isolation or production performance limits.

## Decision and reversal cost

Continue with the custom typed AST plus schema validation. Keep SHACL/Rego as
export adapters. Reversal cost remains moderate because Rule Source and domain
outcomes are independent of the concrete serialized AST.

## Code to keep / delete

Keep truth tables, unit tests, fixture taxonomy and error expectations. Treat
the compiler implementation as disposable until P3/P4 establish configuration
hashing and canonical-state requirements.

## Open issues

Finalize authority partial ordering, aggregate semantics, registered-validator
sandbox, temporal values, function registry and schema migration after the
remaining gates.
