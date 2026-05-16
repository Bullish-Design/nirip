import pytest

from nirip.errors import CycleError
from nirip.planning.models import EnsureWorkspaceStep, FocusWorkspaceStep
from nirip.planning.ordering import topological_sort


def test_topological_sort() -> None:
    a = EnsureWorkspaceStep(id="a", description="a", workspace_name="w")
    b = FocusWorkspaceStep(id="b", description="b", workspace_name="w", depends_on=["a"])
    out = topological_sort([b, a])
    assert [s.id for s in out] == ["a", "b"]


def test_cycle_detected() -> None:
    a = FocusWorkspaceStep(id="a", description="a", workspace_name="w", depends_on=["b"])
    b = FocusWorkspaceStep(id="b", description="b", workspace_name="w", depends_on=["a"])
    with pytest.raises(CycleError):
        topological_sort([a, b])
