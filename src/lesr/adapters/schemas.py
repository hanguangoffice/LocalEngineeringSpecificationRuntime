"""Runtime access to the reviewed LESR v1 JSON Schemas."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry, Resource


class SchemaCatalog:
    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            packaged = files("lesr").joinpath("schemas/v1")
            root = Path(str(packaged))
            if not root.exists():
                root = Path(__file__).resolve().parents[3] / "schemas" / "v1"
        self.schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in root.glob("*.schema.json")
        }
        self.registry = Registry().with_resources(
            (
                schema["$id"],
                Resource.from_contents(schema),
            )
            for schema in self.schemas.values()
        )

    def validate(self, name: str, value: Any) -> None:
        schema = self.schemas[name]
        validator = validator_for(schema)(
            schema,
            registry=self.registry,
            format_checker=FormatChecker(),
        )
        validator.validate(value)
