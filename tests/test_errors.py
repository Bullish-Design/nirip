from nirip.errors import (
    AmbiguousMatchError,
    CaptureError,
    ExecutionError,
    MatchError,
    NiripConnectionError,
    NiripError,
    PlanningError,
    SpecError,
    SpecValidationError,
    StepTimeoutError,
)


def test_error_hierarchy() -> None:
    assert issubclass(SpecValidationError, SpecError)
    assert issubclass(SpecError, NiripError)
    assert issubclass(AmbiguousMatchError, MatchError)
    assert issubclass(StepTimeoutError, ExecutionError)
    assert issubclass(CaptureError, NiripError)
    assert issubclass(PlanningError, NiripError)
    assert issubclass(NiripConnectionError, NiripError)
