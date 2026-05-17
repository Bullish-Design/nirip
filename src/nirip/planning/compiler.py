"""Plan compilation from resolution."""

from __future__ import annotations

from collections.abc import Callable

from nirip.errors import PlanningError
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
from nirip.resolve.models import (
    AppResolution,
    DriftKind,
    NormalizedApp,
    NormalizedSession,
    Resolution,
    ResolutionStatus,
)


def compile_plan(resolution: Resolution, normalized: NormalizedSession) -> Plan:
    """Compile resolution into ordered execution plan."""
    steps: list[PlanStep] = []
    step_counter = 0

    def next_id(prefix: str) -> str:
        nonlocal step_counter
        step_counter += 1
        return f"{prefix}-{step_counter}"

    for wr in resolution.workspace_resolutions:
        ensure_id: str | None = None

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
            if not ar.action_required:
                continue

            napp = normalized.app_index[f"{wr.name}/{ar.app_name}"]
            base_deps = [ensure_id] if ensure_id else []
            placement_deps = list(base_deps)
            wid = ar.match_decision.assigned_window_id

            if ar.needs_spawn and napp.spawn:
                spawn_id = next_id("spawn")
                wait_id = next_id("wait")
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
                        depends_on=base_deps,
                    )
                )
                steps.append(
                    WaitForWindowStep(
                        id=wait_id,
                        description=f"wait for {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        match=napp.match,
                        timeout_s=napp.startup_timeout_s,
                        depends_on=[spawn_id],
                    )
                )
                placement_deps = [wait_id]

            if ar.needs_move or ar.needs_spawn:
                steps.append(
                    MoveWindowToWorkspaceStep(
                        id=next_id("move"),
                        description=f"move {ar.app_name} to '{wr.name}'",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        window_id=wid,
                        target_workspace=wr.name,
                        depends_on=placement_deps,
                    )
                )

            _emit_float_tiling(steps, next_id, ar, napp, wr.name, wid, placement_deps)

            if ar.needs_spawn or any(d.kind == DriftKind.WRONG_FULLSCREEN for d in ar.drift):
                if napp.placement.fullscreen:
                    steps.append(
                        SetFullscreenStep(
                            id=next_id("fs"),
                            window_id=wid,
                            fullscreen=True,
                            description=f"set {ar.app_name} fullscreen",
                            app_name=ar.app_name,
                            workspace_name=wr.name,
                            depends_on=placement_deps,
                        )
                    )

            if ar.needs_spawn or any(d.kind == DriftKind.WRONG_MAXIMIZED for d in ar.drift):
                if napp.placement.maximized:
                    steps.append(
                        SetMaximizedStep(
                            id=next_id("max"),
                            window_id=wid,
                            maximized=True,
                            description=f"set {ar.app_name} maximized",
                            app_name=ar.app_name,
                            workspace_name=wr.name,
                            depends_on=placement_deps,
                        )
                    )

            if napp.placement.column_width is not None:
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
                        depends_on=placement_deps,
                    )
                )

            if napp.placement.window_height is not None:
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
                        depends_on=placement_deps,
                    )
                )

            if napp.placement.focus:
                steps.append(
                    FocusWindowStep(
                        id=next_id("focus"),
                        window_id=wid,
                        description=f"focus {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        depends_on=placement_deps,
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

    app_first_step: dict[str, str] = {}
    app_last_step: dict[str, str] = {}
    for s in steps:
        if s.app_name and s.workspace_name:
            key = f"{s.workspace_name}/{s.app_name}"
            if key not in app_first_step:
                app_first_step[key] = s.id
            app_last_step[key] = s.id

    deps_to_add: dict[str, list[str]] = {}
    for nws in normalized.workspaces:
        for app_name in nws.app_names:
            napp = normalized.app_index[f"{nws.name}/{app_name}"]
            if not napp.depends_on:
                continue
            first_key = f"{nws.name}/{app_name}"
            first_id = app_first_step.get(first_key)
            if first_id is None:
                continue
            for dep_name in napp.depends_on:
                dep_key = f"{nws.name}/{dep_name}"
                dep_last = app_last_step.get(dep_key)
                if dep_last:
                    deps_to_add.setdefault(first_id, []).append(dep_last)

    if deps_to_add:
        steps = [
            s.model_copy(update={"depends_on": s.depends_on + deps_to_add[s.id]}) if s.id in deps_to_add else s
            for s in steps
        ]

    steps = topological_sort(steps)

    return Plan(session_name=resolution.session_name, steps=steps, resolution=resolution)


def _emit_float_tiling(
    steps: list[PlanStep],
    next_id: Callable[[str], str],
    ar: AppResolution,
    napp: NormalizedApp,
    ws_name: str,
    wid: int | None,
    deps: list[str],
) -> None:
    needs_it = ar.needs_spawn or any(d.kind == DriftKind.WRONG_FLOATING for d in ar.drift)
    if not needs_it:
        return
    if napp.placement.floating:
        steps.append(
            SetFloatingStep(
                id=next_id("float"),
                window_id=wid,
                description=f"set {ar.app_name} floating",
                app_name=ar.app_name,
                workspace_name=ws_name,
                depends_on=deps,
            )
        )
    else:
        steps.append(
            SetTilingStep(
                id=next_id("tile"),
                window_id=wid,
                description=f"set {ar.app_name} tiling",
                app_name=ar.app_name,
                workspace_name=ws_name,
                depends_on=deps,
            )
        )


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
