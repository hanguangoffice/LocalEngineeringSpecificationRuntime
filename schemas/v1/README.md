# LESR Canonical Schemas v1

These Draft 2020-12 schemas are the machine-readable portion of the LESR v1.0
construction specification. Their `$id` values and `schema_version` are public
contracts. Runtime adapters may add presentation fields outside Canonical State,
but Canonical resources reject undeclared fields.

`common.schema.json` defines UUIDv7, SHA-256, UTC timestamp, canonical semantic
values, quantities and relation endpoints. Raw JSON floating-point values are
intentionally absent from `canonical_value`.

Run `python scripts/verify_construction_schemas.py` to validate every schema,
resolve all local references and validate embedded examples.
