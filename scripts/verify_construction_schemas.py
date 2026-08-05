from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from lesr.domain.catalog import SCHEMA_CATALOG

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" / "v1"


REQUIRED_SCHEMAS = set(SCHEMA_CATALOG)


def load_schemas() -> dict[Path, dict[str, Any]]:
    paths = set(SCHEMA_ROOT.glob("*.schema.json"))
    names = {path.name for path in paths}
    missing = REQUIRED_SCHEMAS - names
    unexpected = names - REQUIRED_SCHEMAS
    if missing or unexpected:
        raise ValueError(
            f"schema catalog mismatch; missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    return {path: json.loads(path.read_text(encoding="utf-8")) for path in paths}


def iter_references(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            yield reference
        for child in value.values():
            yield from iter_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_references(child)


def verify() -> int:
    schemas = load_schemas()
    resources: list[tuple[str, Resource[Any]]] = []
    for path, schema in schemas.items():
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str):
            raise TypeError(f"{path.name}: missing string $id")
        resources.append((schema_id, Resource.from_contents(schema)))
    registry = Registry().with_resources(resources)

    example_count = 0
    for path, schema in sorted(schemas.items()):
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        validator = validator_class(
            schema,
            registry=registry,
            format_checker=FormatChecker(),
        )
        resolver = registry.resolver(base_uri=schema["$id"])
        for reference in iter_references(schema):
            resolver.lookup(reference)
        for index, example in enumerate(schema.get("examples", [])):
            errors = sorted(validator.iter_errors(example), key=lambda item: list(item.path))
            if errors:
                messages = "; ".join(error.message for error in errors)
                raise ValueError(f"{path.name} example {index}: {messages}")
            example_count += 1

    common = schemas[SCHEMA_ROOT / "common.schema.json"]
    canonical_options = common["$defs"]["canonical_value"]["oneOf"]
    if any(option.get("type") == "number" for option in canonical_options):
        raise ValueError("canonical_value must not allow raw JSON floating-point numbers")

    print(f"Verified {len(schemas)} construction schemas and {example_count} examples (1.0).")
    return 0


if __name__ == "__main__":
    raise SystemExit(verify())
