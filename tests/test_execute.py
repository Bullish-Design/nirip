from __future__ import annotations

import asyncio

import pytest
from tests.conftest import FakeSnapshot, FakeWindow, FakeWorkspace

from nirip.execute import (
    ApplyResult,
    SessionRuntime,
    StepOutcome,
    StepResult,
    _is_satisfied,
    _resolve_wid,
    execute_plan,
)
from nirip.plan import Plan, PlanStep, StepKind, WindowProperty
from nirip.resolve import Resolution
from nirip.spec import SessionOptions


def test_resolve_wid_prefers_step_window() -> None:
    step = PlanStep(id="s", kind=StepKind.FOCUS_WINDOW, description="x", window_id=5, app_name="a", workspace_name="w")
    assert _resolve_wid(step, {"w/a": type("A", (), {"matched_window_id": 9})()}) == 5


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


def test_execute_plan_stops_on_error(monkeypatch) -> None:
    steps = [
        PlanStep(id="a", kind=StepKind.FOCUS_WORKSPACE, description="a"),
        PlanStep(id="b", kind=StepKind.FOCUS_WORKSPACE, description="b"),
    ]
    plan = Plan(session_name="s", steps=steps, resolution=Resolution(session_name="s", workspaces=[], apps=[]))

    async def fake_execute(step, _ports, _apps):
        if step.id == "a":
            return StepResult(step=step, outcome=StepOutcome.FAILED, message="nope")
        return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="ok")

    monkeypatch.setattr("nirip.execute._execute_step", fake_execute)
    ports = SessionRuntime(state=type("S", (), {"snapshot": FakeSnapshot()})(), client=object())  # type: ignore[arg-type]
    result = asyncio.run(execute_plan(plan, ports, SessionOptions(stop_on_error=True)))
    assert len(result.steps) == 1
    assert result.steps[0].outcome == StepOutcome.FAILED
