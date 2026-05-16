from nirip.errors import CaptureError, CycleError, NiripError, PlanningError, SpecError, SpecValidationError


def test_error_hierarchy() -> None:
    assert issubclass(SpecError, NiripError)
    assert issubclass(PlanningError, NiripError)
    assert issubclass(CaptureError, NiripError)


def test_spec_validation_fields() -> None:
    err = SpecValidationError(["e1", "e2"], ["w1"])
    assert err.errors == ["e1", "e2"]
    assert err.warnings == ["w1"]


def test_cycle_error() -> None:
    err = CycleError(["a", "b", "a"])
    assert err.cycle == ["a", "b", "a"]
