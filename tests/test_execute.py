from __future__ import annotations

from tests.conftest import FakeSnapshot, FakeWindow, FakeWorkspace

from nirip.execute import ApplyResult, StepOutcome, StepResult, _is_satisfied, _resolve_wid
from nirip.plan import PlanStep, StepKind, WindowProperty


def test_resolve_wid_prefers_step_window() -> None:
    step = PlanStep(id="s", kind=StepKind.FOCUS_WINDOW, description="x", window_id=5, app_name="a")
    assert _resolve_wid(step, {"a": type("A", (), {"matched_window_id": 9})()}) == 5


def test_is_satisfied_for_move_and_state() -> None:
    snap = FakeSnapshot(
        windows={1: FakeWindow(id=1, workspace_id=2, is_floating=True)},
        workspaces={2: FakeWorkspace(id=2, name="code")},
    )
    move = PlanStep(id="m", kind=StepKind.MOVE_WINDOW, description="m", window_id=1, workspace_name="code")
    state = PlanStep(
        id="s",
        kind=StepKind.SET_STATE,
        description="s",
        window_id=1,
        property=WindowProperty.FLOATING,
        value=True,
    )
    assert _is_satisfied(move, snap) is True  # type: ignore[arg-type]
    assert _is_satisfied(state, snap) is True  # type: ignore[arg-type]


def test_apply_result_counters() -> None:
    step = PlanStep(id="x", kind=StepKind.FOCUS_WORKSPACE, description="x")
    result = ApplyResult(
        session_name="s",
        success=False,
        steps=[
            StepResult(step=step, outcome=StepOutcome.COMPLETED, message="ok"),
            StepResult(step=step, outcome=StepOutcome.SKIPPED, message="skip"),
            StepResult(step=step, outcome=StepOutcome.FAILED, message="fail"),
        ],
        total_duration_s=1.0,
    )
    assert result.completed_count == 1
    assert result.skipped_count == 1
    assert len(result.failed_steps) == 1
