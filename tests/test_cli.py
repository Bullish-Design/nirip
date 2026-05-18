from __future__ import annotations

from nirip.cli import format_plan, format_resolution
from nirip.plan import Plan
from nirip.resolve import Resolution, WorkspaceState


def test_format_resolution_converged() -> None:
    resolution = Resolution(
        session_name="s",
        workspaces=[
            WorkspaceState(
                name="w",
                exists=True,
                output_correct=True,
                desired_output=None,
                current_output="DP-1",
                focus=False,
            )
        ],
        apps=[],
    )
    assert "converged" in format_resolution(resolution)


def test_format_plan_empty() -> None:
    plan = Plan(session_name="s", steps=[], resolution=Resolution(session_name="s", workspaces=[], apps=[]))
    assert "nothing to do" in format_plan(plan).lower()
