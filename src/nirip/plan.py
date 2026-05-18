"""Plan step generation and ordering."""

from __future__ import annotations

from collections import defaultdict, deque
from enum import StrEnum
from typing import Protocol, TypedDict, Unpack

from pydantic import BaseModel, Field, model_validator

from nirip.resolve import AppResolution, DriftKind, Resolution, ResolutionStatus, STATE_PROPERTY_MAP, WorkspaceState
from nirip.spec import _FROZEN, MatchRule, NiripError, SessionOptions


class StepKind(StrEnum):
    CREATE_WORKSPACE = "create_workspace"
    MOVE_WORKSPACE_TO_OUTPUT = "move_workspace_to_output"
    SPAWN_WINDOW = "spawn_window"
    WAIT_FOR_WINDOW = "wait_for_window"
    MOVE_WINDOW = "move_window"
    SET_STATE = "set_state"
    RESIZE = "resize"
    FOCUS_WINDOW = "focus_window"
    FOCUS_WORKSPACE = "focus_workspace"


class WindowProperty(StrEnum):
    FLOATING = "floating"
    TILING = "tiling"
    FULLSCREEN = "fullscreen"
    MAXIMIZED = "maximized"


class ResizeAxis(StrEnum):
    WIDTH = "width"
    HEIGHT = "height"


class PlanStep(BaseModel):
    """Single execution step. Fields are sparse per kind."""

    model_config = _FROZEN

    id: str
    kind: StepKind
    description: str
    depends_on: list[str] = Field(default_factory=list)

    app_name: str | None = None
    workspace_name: str | None = None
    window_id: int | None = None

    command: list[str] | str | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False

    match: MatchRule | None = None
    timeout_s: float | None = None

    target_output: str | None = None

    property: WindowProperty | None = None
    value: bool = True

    axis: ResizeAxis | None = None
    proportion: float | None = None
    pixels: int | None = None

    @model_validator(mode="after")
    def _validate_for_kind(self) -> PlanStep:
        if self.kind == StepKind.SPAWN_WINDOW and self.command is None:
            raise ValueError("SPAWN_WINDOW requires command")
        if self.kind == StepKind.WAIT_FOR_WINDOW and (self.match is None or self.timeout_s is None):
            raise ValueError("WAIT_FOR_WINDOW requires match and timeout_s")
        if self.kind == StepKind.MOVE_WORKSPACE_TO_OUTPUT and self.target_output is None:
            raise ValueError("MOVE_WORKSPACE_TO_OUTPUT requires target_output")
        if self.kind == StepKind.SET_STATE and self.property is None:
            raise ValueError("SET_STATE requires property")
        if self.kind == StepKind.RESIZE and self.axis is None:
            raise ValueError("RESIZE requires axis")
        return self


class Plan(BaseModel):
    model_config = _FROZEN

    session_name: str
    steps: list[PlanStep]
    resolution: Resolution

    @property
    def is_empty(self) -> bool:
        return not self.steps


class _StepParams(TypedDict, total=False):
    app_name: str | None
    workspace_name: str | None
    window_id: int | None
    command: list[str] | str | None
    cwd: str | None
    env: dict[str, str]
    shell: bool
    match: MatchRule | None
    timeout_s: float | None
    target_output: str | None
    property: WindowProperty | None
    value: bool
    axis: ResizeAxis | None
    proportion: float | None
    pixels: int | None
    depends_on: list[str]


class EmitFn(Protocol):
    def __call__(self, kind: StepKind, description: str, **kwargs: Unpack[_StepParams]) -> str: ...


_PROP_TO_WINDOW_PROPERTY: dict[str, tuple[WindowProperty, WindowProperty | None]] = {
    "floating": (WindowProperty.FLOATING, WindowProperty.TILING),
    "fullscreen": (WindowProperty.FULLSCREEN, None),
    "maximized": (WindowProperty.MAXIMIZED, None),
}

_STATE_DRIFT_MAP: list[tuple[DriftKind, str, WindowProperty, WindowProperty | None]] = [
    (prop.drift_kind, prop.placement_attr, *_PROP_TO_WINDOW_PROPERTY[prop.placement_attr]) for prop in STATE_PROPERTY_MAP
]


def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
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
        case _:
            raise ValueError(f"unhandled status: {ar.status}")


def _workspace_steps(
    ws: WorkspaceState,
    emit: EmitFn,
) -> list[str]:
    if not ws.exists:
        sid = emit(
            StepKind.CREATE_WORKSPACE,
            f"create workspace '{ws.name}'",
            workspace_name=ws.name,
            target_output=ws.desired_output,
        )
        return [sid]

    if not ws.output_correct and ws.desired_output:
        sid = emit(
            StepKind.MOVE_WORKSPACE_TO_OUTPUT,
            f"move workspace '{ws.name}' to {ws.desired_output}",
            workspace_name=ws.name,
            target_output=ws.desired_output,
        )
        return [sid]

    return []


def _spawn_steps(
    ar: AppResolution,
    ws_name: str,
    base_deps: list[str],
    emit: EmitFn,
) -> list[str]:
    if ar.spec.spawn is None:
        return list(base_deps)

    spawn_id = emit(
        StepKind.SPAWN_WINDOW,
        f"spawn {ar.app_name}",
        app_name=ar.app_name,
        workspace_name=ws_name,
        command=ar.spec.spawn.command,
        cwd=ar.spec.spawn.cwd,
        env=ar.spec.spawn.env,
        shell=ar.spec.spawn.shell,
        depends_on=base_deps,
    )
    wait_id = emit(
        StepKind.WAIT_FOR_WINDOW,
        f"wait for {ar.app_name}",
        app_name=ar.app_name,
        workspace_name=ws_name,
        match=ar.spec.match,
        timeout_s=ar.startup_timeout_s,
        depends_on=[spawn_id],
    )
    return [wait_id]


def _placement_steps(
    ar: AppResolution,
    ws_name: str,
    deps: list[str],
    emit: EmitFn,
) -> None:
    if ar.needs_move or ar.status == ResolutionStatus.MISSING:
        # window_id may be None for MISSING apps; the executor resolves it from
        # matched_window_id populated by an earlier WAIT_FOR_WINDOW dependency.
        emit(
            StepKind.MOVE_WINDOW,
            f"move {ar.app_name} to '{ws_name}'",
            app_name=ar.app_name,
            workspace_name=ws_name,
            window_id=ar.window_id,
            depends_on=deps,
        )

    for drift_kind, placement_attr, true_prop, false_prop in _STATE_DRIFT_MAP:
        needs = any(d.kind == drift_kind for d in ar.drift)
        desired = bool(getattr(ar.spec.placement, placement_attr))
        if not needs and ar.status == ResolutionStatus.MISSING:
            needs = desired
        if not needs:
            continue

        prop = true_prop if desired or false_prop is None else false_prop
        emit(
            StepKind.SET_STATE,
            f"set {ar.app_name} {prop.value}",
            app_name=ar.app_name,
            workspace_name=ws_name,
            window_id=ar.window_id,
            property=prop,
            value=desired,
            depends_on=deps,
        )

    if ar.spec.placement.column_width is not None:
        proportion, pixels = _parse_size(ar.spec.placement.column_width)
        emit(
            StepKind.RESIZE,
            f"set column width for {ar.app_name}",
            app_name=ar.app_name,
            workspace_name=ws_name,
            window_id=ar.window_id,
            axis=ResizeAxis.WIDTH,
            proportion=proportion,
            pixels=pixels,
            depends_on=deps,
        )

    if ar.spec.placement.window_height is not None:
        proportion, pixels = _parse_size(ar.spec.placement.window_height)
        emit(
            StepKind.RESIZE,
            f"set window height for {ar.app_name}",
            app_name=ar.app_name,
            workspace_name=ws_name,
            window_id=ar.window_id,
            axis=ResizeAxis.HEIGHT,
            proportion=proportion,
            pixels=pixels,
            depends_on=deps,
        )

    if ar.spec.placement.focus:
        emit(
            StepKind.FOCUS_WINDOW,
            f"focus {ar.app_name}",
            app_name=ar.app_name,
            workspace_name=ws_name,
            window_id=ar.window_id,
            depends_on=deps,
        )


def _wire_dependencies(
    steps: list[PlanStep],
    app_first: dict[str, str],
    app_last: dict[str, str],
    resolution: Resolution,
) -> list[PlanStep]:
    deps_to_add: dict[str, list[str]] = {}

    for ws in resolution.workspaces:
        for ar in resolution.apps_in(ws.name):
            if not ar.spec.depends_on:
                continue
            first_key = f"{ws.name}/{ar.app_name}"
            first_id = app_first.get(first_key)
            if first_id is None:
                continue
            for dep_name in ar.spec.depends_on:
                dep_key = f"{ws.name}/{dep_name}"
                dep_last = app_last.get(dep_key)
                if dep_last:
                    deps_to_add.setdefault(first_id, []).append(dep_last)

    if not deps_to_add:
        return steps
    return [
        s.model_copy(update={"depends_on": s.depends_on + deps_to_add[s.id]}) if s.id in deps_to_add else s
        for s in steps
    ]


def _parse_size(value: float | str) -> tuple[float | None, int | None]:
    if isinstance(value, (int, float)):
        return (float(value), None)
    if isinstance(value, str):
        if value.startswith("px:"):
            try:
                return (None, int(value[3:]))
            except ValueError as e:
                raise NiripError(f"invalid pixel size: {value!r} — expected 'px:<integer>'") from e
        try:
            return (float(value), None)
        except ValueError as e:
            raise NiripError(f"invalid size value: {value!r}") from e
    raise NiripError(f"unexpected size type: {type(value).__name__}")


def _topological_sort(steps: list[PlanStep]) -> list[PlanStep]:
    id_map = {step.id: step for step in steps}
    indegree = {step.id: 0 for step in steps}
    edges: dict[str, list[str]] = defaultdict(list)

    for step in steps:
        for dep in step.depends_on:
            if dep not in id_map:
                continue
            edges[dep].append(step.id)
            indegree[step.id] += 1

    queue: deque[str] = deque(sorted([sid for sid, degree in indegree.items() if degree == 0]))
    ordered: list[PlanStep] = []

    while queue:
        sid = queue.popleft()
        ordered.append(id_map[sid])
        for nxt in sorted(edges[sid]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(steps):
        ordered_ids = {step.id for step in ordered}
        cycle_ids = [step.id for step in steps if step.id not in ordered_ids]
        raise NiripError(f"dependency cycle among steps: {cycle_ids}")
    return ordered


def _validate_window_id_contracts(steps: list[PlanStep]) -> None:
    """Ensure runtime-resolved window ids have a WAIT_FOR_WINDOW dependency ancestor."""
    needs_wid = {StepKind.MOVE_WINDOW, StepKind.SET_STATE, StepKind.RESIZE, StepKind.FOCUS_WINDOW}
    wait_steps = {step.id for step in steps if step.kind == StepKind.WAIT_FOR_WINDOW}
    dep_map = {step.id: set(step.depends_on) for step in steps}

    def has_wait_ancestor(step_id: str, visited: set[str] | None = None) -> bool:
        if visited is None:
            visited = set()
        if step_id in visited:
            return False
        visited.add(step_id)
        if step_id in wait_steps:
            return True
        return any(has_wait_ancestor(dep, visited) for dep in dep_map.get(step_id, set()))

    for step in steps:
        if step.kind in needs_wid and step.window_id is None:
            if not has_wait_ancestor(step.id):
                raise NiripError(
                    f"step {step.id} ({step.kind.value}) has no window_id and no "
                    "WAIT_FOR_WINDOW in dependency chain"
                )


def build_plan(resolution: Resolution, options: SessionOptions) -> Plan:
    steps: list[PlanStep] = []
    counter = 0
    app_first: dict[str, str] = {}
    app_last: dict[str, str] = {}

    def emit(kind: StepKind, description: str, **kwargs: Unpack[_StepParams]) -> str:
        nonlocal counter
        counter += 1
        sid = f"{kind.value}-{counter}"
        step = PlanStep(id=sid, kind=kind, description=description, **kwargs)
        steps.append(step)
        key = f"{step.workspace_name}/{step.app_name}" if step.app_name and step.workspace_name else None
        if key:
            if key not in app_first:
                app_first[key] = sid
            app_last[key] = sid
        return sid

    for ws in resolution.workspaces:
        base_deps = _workspace_steps(ws, emit)
        for ar in resolution.apps_in(ws.name):
            if not _should_act(ar, options):
                continue
            placement_deps = list(base_deps)
            if ar.status == ResolutionStatus.MISSING and ar.spec.spawn:
                placement_deps = _spawn_steps(ar, ws.name, base_deps, emit)
            _placement_steps(ar, ws.name, placement_deps, emit)

    for ws in resolution.workspaces:
        if ws.focus:
            emit(StepKind.FOCUS_WORKSPACE, f"focus workspace '{ws.name}'", workspace_name=ws.name)

    steps = _wire_dependencies(steps, app_first, app_last, resolution)
    _validate_window_id_contracts(steps)

    return Plan(
        session_name=resolution.session_name,
        steps=_topological_sort(steps),
        resolution=resolution,
    )
