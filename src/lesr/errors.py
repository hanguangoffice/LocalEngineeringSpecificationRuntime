"""Stable domain errors exposed by services and, later, MCP."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LESRError(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    suggested_action: str | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
