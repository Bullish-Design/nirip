"""Error hierarchy for nirip."""

from __future__ import annotations


class NiripError(Exception):
    """Base for all nirip errors."""


class SpecError(NiripError):
    """Invalid session spec (parse or structural error)."""


class SpecValidationError(SpecError):
    """Spec validation failed with one or more errors."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None) -> None:
        self.errors = errors
        self.warnings = warnings or []
        msg = f"{len(errors)} validation error(s): {'; '.join(errors[:3])}"
        if len(errors) > 3:
            msg += f" ... and {len(errors) - 3} more"
        super().__init__(msg)


class PlanningError(NiripError):
    """Plan compilation failed."""


class CycleError(PlanningError):
    """Dependency cycle detected during topological sort."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"dependency cycle: {' -> '.join(cycle)}")


class CaptureError(NiripError):
    """Capture operation failed."""


class NiripConnectionError(NiripError):
    """Cannot connect to niri compositor."""
