"""Plan compilation from resolution."""

from __future__ import annotations

from nirip.errors import PlanningError
from nirip.planning.models import (
    CreateWorkspaceStep,
    FocusWindowStep,
    FocusWorkspaceStep,
    MoveWindowToWorkspaceStep,
    MoveWorkspaceToOutputStep,
    Plan,
    PlanStep,
    ResizeAxis,
    ResizeWindowStep,
    SessionDiff,
    SetWindowStateStep,
    SpawnWindowStep,
    WaitForWindowStep,
    WindowProperty,
)
from nirip.planning.ordering import topological_sort
from nirip.resolve.models import (
    DriftKind,
    AppResolution,
    Resolution,
    ResolutionStatus,
)
from nirip.spec.models import SessionOptions


def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
    """Policy: determine if this app resolution requires action."""
    match ar.status:
        case ResolutionStatus.MATCHED:
            return False
        case ResolutionStatus.OPTIONAL_MISSING:
            return False
        case ResolutionStatus.MISSING:
            return options.launch_missing
        case ResolutionStatus.DRIFTED:
            return True
        case ResolutionStatus.AMBIGUOUS:
            return False


def compile_plan(resolution: Resolution, options: SessionOptions) -> Plan:
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
            ensure_id = next_id("create-ws")
            steps.append(
                CreateWorkspaceStep(
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
            if not _should_act(ar, options):
                continue

            base_deps = [ensure_id] if ensure_id else []
            placement_deps = list(base_deps)
            wid = ar.match_decision.assigned_window_id

            if ar.status == ResolutionStatus.MISSING and ar.spec.spawn:
                spawn_id = next_id("spawn")
                wait_id = next_id("wait")
                steps.append(
                    SpawnWindowStep(
                        id=spawn_id,
                        description=f"spawn {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        command=ar.spec.spawn.command,
                        cwd=ar.spec.spawn.cwd,
                        env=ar.spec.spawn.env,
                        shell=ar.spec.spawn.shell,
                        depends_on=base_deps,
                    )
                )
                steps.append(
                    WaitForWindowStep(
                        id=wait_id,
                        description=f"wait for {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        match=ar.spec.match,
                        timeout_s=ar.startup_timeout_s,
                        depends_on=[spawn_id],
                    )
                )
                placement_deps = [wait_id]

            if ar.needs_move or ar.status == ResolutionStatus.MISSING:
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

            needs_float_or_tile_correction = ar.status == ResolutionStatus.MISSING or any(
                d.kind == DriftKind.WRONG_FLOATING for d in ar.drift
            )
            if needs_float_or_tile_correction:
                prop = WindowProperty.FLOATING if ar.spec.placement.floating else WindowProperty.TILING
                steps.append(
                    SetWindowStateStep(
                        id=next_id("state"),
                        window_id=wid,
                        property=prop,
                        description=f"set {ar.app_name} {prop.value}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        depends_on=placement_deps,
                    )
                )

            if ar.status == ResolutionStatus.MISSING or any(d.kind == DriftKind.WRONG_FULLSCREEN for d in ar.drift):
                steps.append(
                    SetWindowStateStep(
                        id=next_id("state"),
                        window_id=wid,
                        property=WindowProperty.FULLSCREEN,
                        value=ar.spec.placement.fullscreen,
                        description=f"set {ar.app_name} fullscreen",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        depends_on=placement_deps,
                    )
                )

            if ar.status == ResolutionStatus.MISSING or any(d.kind == DriftKind.WRONG_MAXIMIZED for d in ar.drift):
                steps.append(
                    SetWindowStateStep(
                        id=next_id("state"),
                        window_id=wid,
                        property=WindowProperty.MAXIMIZED,
                        value=ar.spec.placement.maximized,
                        description=f"set {ar.app_name} maximized",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        depends_on=placement_deps,
                    )
                )

            if ar.spec.placement.column_width is not None:
                prop, px = _parse_size(ar.spec.placement.column_width)
                steps.append(
                    ResizeWindowStep(
                        id=next_id("resize"),
                        window_id=wid,
                        axis=ResizeAxis.WIDTH,
                        proportion=prop,
                        pixels=px,
                        description=f"set column width for {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        depends_on=placement_deps,
                    )
                )

            if ar.spec.placement.window_height is not None:
                prop, px = _parse_size(ar.spec.placement.window_height)
                steps.append(
                    ResizeWindowStep(
                        id=next_id("resize"),
                        window_id=wid,
                        axis=ResizeAxis.HEIGHT,
                        proportion=prop,
                        pixels=px,
                        description=f"set window height for {ar.app_name}",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        depends_on=placement_deps,
                    )
                )

            if ar.spec.placement.focus:
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

    for wr in resolution.workspace_resolutions:
        if wr.focus:
            steps.append(
                FocusWorkspaceStep(
                    id=next_id("focus-ws"),
                    description=f"focus workspace '{wr.name}'",
                    workspace_name=wr.name,
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
    for wr in resolution.workspace_resolutions:
        for ar in wr.app_resolutions:
            if not ar.spec.depends_on:
                continue
            first_key = f"{wr.name}/{ar.app_name}"
            first_id = app_first_step.get(first_key)
            if first_id is None:
                continue
            for dep_name in ar.spec.depends_on:
                dep_key = f"{wr.name}/{dep_name}"
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
                    diff.drifted.append(label)
            elif ar.status == ResolutionStatus.AMBIGUOUS:
                diff.errors.append(f"ambiguous match: {label}")

    return diff
