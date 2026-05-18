from __future__ import annotations

from nirip.cli import build_parser, format_plan, format_resolution, format_result, main
from nirip.execute import ApplyResult, StepOutcome, StepResult
from nirip.plan import Plan, PlanStep, StepKind
from nirip.resolve import AppResolution, DriftItem, DriftKind, Resolution, ResolutionStatus, WorkspaceState
from nirip.spec import AppSpec, MatchRule


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


def test_format_resolution_drift_and_spawn() -> None:
    resolution = Resolution(
        session_name="s",
        workspaces=[
            WorkspaceState(
                name="w",
                exists=False,
                output_correct=False,
                desired_output="DP-1",
                current_output=None,
                focus=False,
            )
        ],
        apps=[
            AppResolution(
                app_name="a",
                workspace_name="w",
                status=ResolutionStatus.MISSING,
                window_id=None,
                is_ambiguous=False,
                drift=[],
                spec=AppSpec(name="a", match=MatchRule(app_id="a")),
                startup_timeout_s=2.0,
            ),
            AppResolution(
                app_name="b",
                workspace_name="w",
                status=ResolutionStatus.DRIFTED,
                window_id=1,
                is_ambiguous=False,
                drift=[DriftItem(kind=DriftKind.WRONG_FLOATING, current="False", desired="True")],
                spec=AppSpec(name="b", match=MatchRule(app_id="b")),
                startup_timeout_s=2.0,
            ),
        ],
    )
    text = format_resolution(resolution)
    assert "Will spawn:" in text
    assert "Drifted:" in text
    assert "Workspace changes:" in text


def test_format_result_failed_steps() -> None:
    fake_step = StepResult(
        step=PlanStep(id="x", kind=StepKind.FOCUS_WORKSPACE, description="d"),
        outcome=StepOutcome.FAILED,
        message="boom",
    )
    result = ApplyResult(session_name="s", success=False, steps=[fake_step], total_duration_s=1.0)
    out = format_result(result)
    assert "FAILED" in out
    assert "boom" in out


def test_build_parser_subcommands() -> None:
    parser = build_parser()
    args = parser.parse_args(["plan", "x.yaml"])
    assert args.command == "plan"
    assert args.session_file == "x.yaml"


def test_main_no_command_returns_1() -> None:
    assert main([]) == 1
