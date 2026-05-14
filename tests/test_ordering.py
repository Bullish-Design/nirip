import pytest

from nirip.errors import CycleError
from nirip.planning.models import PlanStep, StepKind
from nirip.planning.ordering import topological_sort


def _step(id: str, depends_on: list[str] | None = None) -> PlanStep:
    return PlanStep(
        id=id,
        kind=StepKind.SPAWN_WINDOW,
        description=f"step {id}",
        depends_on=depends_on or [],
    )


def test_topological_sort_linear() -> None:
    steps = [_step("c", ["b"]), _step("b", ["a"]), _step("a")]
    result = topological_sort(steps)
    ids = [s.id for s in result]
    assert ids.index("a") < ids.index("b") < ids.index("c")


def test_topological_sort_no_deps() -> None:
    steps = [_step("b"), _step("a"), _step("c")]
    result = topological_sort(steps)
    assert len(result) == 3


def test_topological_sort_cycle_raises() -> None:
    steps = [_step("a", ["b"]), _step("b", ["a"])]
    with pytest.raises(CycleError, match="cycle"):
        topological_sort(steps)


def test_topological_sort_unknown_dep_ignored() -> None:
    steps = [_step("a", ["nonexistent"])]
    result = topological_sort(steps)
    assert len(result) == 1
