"""Nirip error hierarchy."""


class NiripError(Exception):
    """Base for all nirip errors."""


class SpecError(NiripError):
    """Invalid session spec (parse error, validation failure)."""


class SpecValidationError(SpecError):
    """Spec validation failed (empty match rules, conflicts, etc.)."""


class MatchError(NiripError):
    """Window matching failure."""


class AmbiguousMatchError(MatchError):
    """Multiple windows match with similar confidence."""


class PlanningError(NiripError):
    """Plan generation failed (unresolvable conflicts)."""


class CycleError(PlanningError):
    """Dependency cycle detected among plan steps."""


class ExecutionError(NiripError):
    """Step execution failed."""


class StepTimeoutError(ExecutionError):
    """Window didn't appear within timeout."""


class CaptureError(NiripError):
    """Capture failed."""


class NiripConnectionError(NiripError):
    """Cannot connect to niri compositor."""
