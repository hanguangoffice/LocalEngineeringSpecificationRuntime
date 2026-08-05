"""Local Engineering Specification Runtime for Design Baseline v1.0."""

from lesr.domain.semantic import (
    ConfigurationSnapshot,
    ImmutableRecord,
    LogicalObject,
    RelationAssertion,
    Revision,
)

__version__ = "0.5.0a2"
__design_baseline__ = "1.0"
__all__ = [
    "ConfigurationSnapshot",
    "ImmutableRecord",
    "LogicalObject",
    "RelationAssertion",
    "Revision",
    "__design_baseline__",
    "__version__",
]
