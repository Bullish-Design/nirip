"""Tests for CLI output formatters."""

from nirip.cli.formatting import format_diff, format_plan
from nirip.planning.models import Plan, SessionDiff
from nirip.resolve.models import Resolution


def test_format_diff_converged() -> None:
    diff = SessionDiff(session_name="test")
    output = format_diff(diff)
    assert "No changes needed" in output


def test_format_diff_with_spawn() -> None:
    diff = SessionDiff(session_name="test", will_spawn=["dev/firefox"])
    output = format_diff(diff)
    assert "+ dev/firefox" in output


def test_format_diff_with_optional_missing() -> None:
    diff = SessionDiff(session_name="test", optional_missing=["dev/slack"])
    output = format_diff(diff)
    assert "Optional (not running): 1" in output
    assert "? dev/slack" in output


def test_format_plan_empty() -> None:
    resolution = Resolution(
        session_name="test",
        workspace_resolutions=[],
        warnings=[],
    )
    plan = Plan(session_name="test", steps=[], resolution=resolution, warnings=[])
    output = format_plan(plan)
    assert "nothing to do" in output.lower()
