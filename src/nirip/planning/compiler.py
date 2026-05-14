"""Compile Resolution to Plan and SessionDiff."""
from __future__ import annotations

from nirip.planning.models import Plan, PlanStep, SessionDiff, StepKind
from nirip.planning.ordering import topological_sort
from nirip.resolve.models import DriftKind, Resolution, ResolutionStatus


def compile_plan(resolution: Resolution) -> Plan:
    """Compile a resolution into an execution plan."""

    steps: list[PlanStep] = []
    warnings = list(resolution.warnings)
    counter = 0

    def new_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-{counter}"

    for ws in resolution.workspace_resolutions:
        if not ws.exists:
            steps.append(
                PlanStep(
                    id=new_id("ws"),
                    kind=StepKind.ENSURE_WORKSPACE,
                    workspace_name=ws.name,
                    description=f"Ensure workspace '{ws.name}' exists",
                )
            )
        if ws.desired_output and not ws.output_correct:
            steps.append(
                PlanStep(
                    id=new_id("ws-move"),
                    kind=StepKind.MOVE_WORKSPACE_TO_OUTPUT,
                    workspace_name=ws.name,
                    description=f"Move workspace '{ws.name}' to output '{ws.desired_output}'",
                    metadata={"output": ws.desired_output},
                )
            )

        for app in ws.app_resolutions:
            if app.status == ResolutionStatus.MATCHED:
                continue
            if app.status == ResolutionStatus.AMBIGUOUS:
                warnings.append(f"Ambiguous match for {app.workspace_name}/{app.app_name}; skipping")
                continue
            if app.status == ResolutionStatus.OPTIONAL_MISSING:
                continue
            if app.status == ResolutionStatus.MISSING:
                spawn_id = new_id("spawn")
                steps.append(
                    PlanStep(
                        id=spawn_id,
                        kind=StepKind.SPAWN_WINDOW,
                        app_name=app.app_name,
                        workspace_name=app.workspace_name,
                        description=f"Spawn app '{app.app_name}'",
                    )
                )
                steps.append(
                    PlanStep(
                        id=new_id("wait"),
                        kind=StepKind.WAIT_FOR_WINDOW,
                        app_name=app.app_name,
                        workspace_name=app.workspace_name,
                        description=f"Wait for app '{app.app_name}' window",
                        depends_on=[spawn_id],
                    )
                )
            if app.status == ResolutionStatus.DRIFTED:
                for drift in app.drift:
                    if drift.kind == DriftKind.WRONG_WORKSPACE:
                        steps.append(
                            PlanStep(
                                id=new_id("move"),
                                kind=StepKind.MOVE_WINDOW_TO_WORKSPACE,
                                app_name=app.app_name,
                                workspace_name=app.workspace_name,
                                window_id=app.match_decision.best,
                                description=f"Move '{app.app_name}' to workspace '{app.workspace_name}'",
                            )
                        )
                    if drift.kind == DriftKind.WRONG_FLOATING:
                        kind = StepKind.SET_FLOATING if drift.desired == "True" else StepKind.SET_TILING
                        steps.append(
                            PlanStep(
                                id=new_id("float"),
                                kind=kind,
                                app_name=app.app_name,
                                workspace_name=app.workspace_name,
                                window_id=app.match_decision.best,
                                description=f"Set floating for '{app.app_name}' to {drift.desired}",
                            )
                        )
                    if drift.kind == DriftKind.WRONG_FULLSCREEN:
                        kind = (
                            StepKind.SET_FULLSCREEN
                            if drift.desired == "True"
                            else StepKind.UNSET_FULLSCREEN
                        )
                        steps.append(
                            PlanStep(
                                id=new_id("fs"),
                                kind=kind,
                                app_name=app.app_name,
                                workspace_name=app.workspace_name,
                                window_id=app.match_decision.best,
                                description=f"Set fullscreen for '{app.app_name}' to {drift.desired}",
                            )
                        )
                    if drift.kind == DriftKind.WRONG_MAXIMIZED:
                        kind = (
                            StepKind.SET_MAXIMIZED
                            if drift.desired == "True"
                            else StepKind.UNSET_MAXIMIZED
                        )
                        steps.append(
                            PlanStep(
                                id=new_id("max"),
                                kind=kind,
                                app_name=app.app_name,
                                workspace_name=app.workspace_name,
                                window_id=app.match_decision.best,
                                description=f"Set maximized for '{app.app_name}' to {drift.desired}",
                            )
                        )

    return Plan(
        session_name=resolution.session_name,
        steps=topological_sort(steps),
        resolution=resolution,
        warnings=warnings,
    )


def compile_diff(resolution: Resolution) -> SessionDiff:
    """Create a human-readable diff from resolution."""

    diff = SessionDiff(session_name=resolution.session_name, warnings=list(resolution.warnings))
    for ws in resolution.workspace_resolutions:
        if not ws.exists:
            diff.workspace_changes.append(f"{ws.name}: create workspace")
        if ws.desired_output and not ws.output_correct:
            diff.workspace_changes.append(f"{ws.name}: move to output {ws.desired_output}")

        for app in ws.app_resolutions:
            if app.status == ResolutionStatus.MATCHED:
                if app.match_decision.best is not None:
                    diff.already_matched.append(
                        f"{app.app_name}: matched window {app.match_decision.best}"
                    )
            elif app.status == ResolutionStatus.MISSING:
                diff.will_spawn.append(f"{app.app_name}: will spawn")
            elif app.status == ResolutionStatus.OPTIONAL_MISSING:
                diff.warnings.append(f"{app.app_name}: no match found (optional)")
            elif app.status == ResolutionStatus.AMBIGUOUS:
                diff.errors.append(f"{app.app_name}: ambiguous match")
            elif app.status == ResolutionStatus.DRIFTED:
                for drift in app.drift:
                    if drift.kind == DriftKind.WRONG_WORKSPACE:
                        diff.will_move.append(f"{app.app_name}: move to {app.workspace_name}")
                    else:
                        diff.will_adjust.append(f"{app.app_name}: {drift.kind.value}")
    return diff
