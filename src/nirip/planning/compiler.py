"""Plan compilation from resolution."""

from __future__ import annotations

from nirip.planning.models import (
    EnsureWorkspaceStep,
    FocusWindowStep,
    FocusWorkspaceStep,
    MoveWindowToWorkspaceStep,
    MoveWorkspaceToOutputStep,
    Plan,
    PlanStep,
    SessionDiff,
    SetColumnWidthStep,
    SetFloatingStep,
    SetFullscreenStep,
    SetMaximizedStep,
    SetTilingStep,
    SetWindowHeightStep,
    SpawnWindowStep,
    WaitForWindowStep,
)
from nirip.planning.ordering import topological_sort
from nirip.errors import PlanningError
from nirip.resolve.models import DriftKind, NormalizedSession, Resolution, ResolutionStatus


def compile_plan(resolution: Resolution, normalized: NormalizedSession) -> Plan:
    """Compile resolution into ordered execution plan."""
    steps: list[PlanStep] = []
    step_counter = 0

    def next_id(prefix: str) -> str:
        nonlocal step_counter
        step_counter += 1
        return f"{prefix}-{step_counter}"

    for wr in resolution.workspace_resolutions:
        ensure_id = None

        if not wr.exists:
            ensure_id = next_id("ensure-ws")
            steps.append(
                EnsureWorkspaceStep(
                    id=ensure_id,
                    description=f"create workspace '{wr.name}'",
                    workspace_name=wr.name,
                    target_output=wr.desired_output,
                )
            )
        elif not wr.output_correct and wr.desired_output:
            steps.append(
                MoveWorkspaceToOutputStep(
                    id=next_id("move-ws"),
                    description=f"move workspace '{wr.name}' to {wr.desired_output}",
                    workspace_name=wr.name,
                    target_output=wr.desired_output,
                )
            )

        for ar in wr.app_resolutions:
            napp = normalized.app_index[f"{wr.name}/{ar.app_name}"]
            deps = [ensure_id] if ensure_id else []

            if ar.needs_spawn and napp.spawn:
                spawn_id = next_id("spawn")
                steps.append(
                    SpawnWindowStep(
                        id=spawn_id,
                        description=f"spawn {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        command=napp.spawn.command,
                        cwd=napp.spawn.cwd,
                        env=napp.spawn.env,
                        shell=napp.spawn.shell,
                        depends_on=deps,
                    )
                )
                steps.append(
                    WaitForWindowStep(
                        id=next_id("wait"),
                        description=f"wait for {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        match=napp.match,
                        timeout_s=napp.startup_timeout_s,
                        depends_on=[spawn_id],
                    )
                )

            wid = ar.match_decision.assigned_window_id

            if ar.needs_move and wid is not None:
                steps.append(
                    MoveWindowToWorkspaceStep(
                        id=next_id("move"),
                        description=f"move {ar.app_name} to '{wr.name}'",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        window_id=wid,
                        target_workspace=wr.name,
                        depends_on=deps,
                    )
                )

            if wid is not None:
                for d in ar.drift:
                    if d.kind == DriftKind.WRONG_FLOATING:
                        if napp.placement.floating:
                            steps.append(
                                SetFloatingStep(
                                    id=next_id("float"),
                                    window_id=wid,
                                    description=f"set {ar.app_name} floating",
                                    app_name=ar.app_name,
                                    workspace_name=wr.name,
                                )
                            )
                        else:
                            steps.append(
                                SetTilingStep(
                                    id=next_id("tile"),
                                    window_id=wid,
                                    description=f"set {ar.app_name} tiling",
                                    app_name=ar.app_name,
                                    workspace_name=wr.name,
                                )
                            )
                    elif d.kind == DriftKind.WRONG_FULLSCREEN:
                        steps.append(
                            SetFullscreenStep(
                                id=next_id("fs"),
                                window_id=wid,
                                fullscreen=napp.placement.fullscreen,
                                description=f"set {ar.app_name} fullscreen={napp.placement.fullscreen}",
                                app_name=ar.app_name,
                                workspace_name=wr.name,
                            )
                        )
                    elif d.kind == DriftKind.WRONG_MAXIMIZED:
                        steps.append(
                            SetMaximizedStep(
                                id=next_id("max"),
                                window_id=wid,
                                maximized=napp.placement.maximized,
                                description=f"set {ar.app_name} maximized={napp.placement.maximized}",
                                app_name=ar.app_name,
                                workspace_name=wr.name,
                            )
                        )

            if wid is not None and napp.placement.column_width is not None:
                prop, px = _parse_size(napp.placement.column_width)
                steps.append(
                    SetColumnWidthStep(
                        id=next_id("cw"),
                        window_id=wid,
                        proportion=prop,
                        pixels=px,
                        description=f"set column width for {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                    )
                )

            if wid is not None and napp.placement.window_height is not None:
                prop, px = _parse_size(napp.placement.window_height)
                steps.append(
                    SetWindowHeightStep(
                        id=next_id("wh"),
                        window_id=wid,
                        proportion=prop,
                        pixels=px,
                        description=f"set window height for {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                    )
                )

            if wid is not None and napp.placement.focus:
                steps.append(
                    FocusWindowStep(
                        id=next_id("focus"),
                        window_id=wid,
                        description=f"focus {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                    )
                )

    for nws in normalized.workspaces:
        if nws.focus:
            steps.append(
                FocusWorkspaceStep(
                    id=next_id("focus-ws"),
                    description=f"focus workspace '{nws.name}'",
                    workspace_name=nws.name,
                )
            )

    steps = topological_sort(steps)

    return Plan(session_name=resolution.session_name, steps=steps, resolution=resolution)


def _parse_size(value: float | str) -> tuple[float | None, int | None]:
    """Parse size value: float proportion or "px:<integer>" fixed pixels."""
    if isinstance(value, (int, float)):
        return (float(value), None)
    if isinstance(value, str):
        if value.startswith("px:"):
            try:
                return (None, int(value[3:]))
            except ValueError as e:
                raise PlanningError(f"invalid pixel size: {value!r} — expected 'px:<integer>'") from e
        try:
            return (float(value), None)
        except ValueError as e:
            raise PlanningError(f"invalid size value: {value!r}") from e
    raise PlanningError(f"unexpected size type: {type(value).__name__}")


def compile_diff(resolution: Resolution) -> SessionDiff:
    """Human-readable diff from resolution."""
    diff = SessionDiff(session_name=resolution.session_name, warnings=list(resolution.warnings))

    for wr in resolution.workspace_resolutions:
        if not wr.exists:
            diff.workspace_changes.append(f"workspace '{wr.name}' will be created")
        elif wr.desired_output and not wr.output_correct:
            diff.workspace_changes.append(
                f"workspace '{wr.name}' will move output {wr.current_output} -> {wr.desired_output}"
            )

        for ar in wr.app_resolutions:
            label = f"{wr.name}/{ar.app_name}"
            if ar.status == ResolutionStatus.MATCHED:
                diff.already_matched.append(label)
            elif ar.status == ResolutionStatus.MISSING:
                diff.will_spawn.append(label)
            elif ar.status == ResolutionStatus.DRIFTED:
                if ar.needs_move:
                    diff.will_move.append(label)
                if any(d.kind != DriftKind.WRONG_WORKSPACE for d in ar.drift):
                    diff.will_adjust.append(label)
            elif ar.status == ResolutionStatus.AMBIGUOUS:
                diff.errors.append(f"ambiguous match: {label}")

    return diff
