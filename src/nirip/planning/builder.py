"""Plan step builder."""

from __future__ import annotations

from collections.abc import Callable

from nirip.planning.models import (
    CreateWorkspaceStep,
    FocusWindowStep,
    FocusWorkspaceStep,
    MoveWindowToWorkspaceStep,
    MoveWorkspaceToOutputStep,
    PlanStep,
    ResizeAxis,
    ResizeWindowStep,
    SetWindowStateStep,
    SpawnWindowStep,
    WaitForWindowStep,
    WindowProperty,
)
from nirip.planning.ordering import topological_sort
from nirip.resolve.models import AppResolution, DriftKind, Resolution, ResolutionStatus, WorkspaceResolution

SizeParser = Callable[[float | str], tuple[float | None, int | None]]


class PlanBuilder:
    """Builds plan steps with dependency tracking."""

    def __init__(self, parse_size: SizeParser) -> None:
        self._parse_size = parse_size
        self._steps: list[PlanStep] = []
        self._counter = 0
        self._app_first: dict[str, str] = {}
        self._app_last: dict[str, str] = {}

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def _track(self, step: PlanStep) -> None:
        self._steps.append(step)
        if step.app_name and step.workspace_name:
            key = f"{step.workspace_name}/{step.app_name}"
            if key not in self._app_first:
                self._app_first[key] = step.id
            self._app_last[key] = step.id

    def ensure_workspace(self, wr: WorkspaceResolution) -> str | None:
        """Emit workspace creation/move step. Return step id if emitted."""
        if not wr.exists:
            sid = self._next_id("create-ws")
            self._track(
                CreateWorkspaceStep(
                    id=sid,
                    description=f"create workspace '{wr.name}'",
                    workspace_name=wr.name,
                    target_output=wr.desired_output,
                )
            )
            return sid

        if not wr.output_correct and wr.desired_output:
            sid = self._next_id("move-ws")
            self._track(
                MoveWorkspaceToOutputStep(
                    id=sid,
                    description=f"move workspace '{wr.name}' to {wr.desired_output}",
                    workspace_name=wr.name,
                    target_output=wr.desired_output,
                )
            )
            return sid

        return None

    def spawn_app(self, ar: AppResolution, ws_name: str, base_deps: list[str]) -> list[str]:
        """Emit spawn+wait steps. Return deps for placement steps."""
        if ar.spec.spawn is None:
            return list(base_deps)

        spawn_id = self._next_id("spawn")
        wait_id = self._next_id("wait")
        self._track(
            SpawnWindowStep(
                id=spawn_id,
                description=f"spawn {ar.app_name}",
                app_name=ar.app_name,
                workspace_name=ws_name,
                command=ar.spec.spawn.command,
                cwd=ar.spec.spawn.cwd,
                env=ar.spec.spawn.env,
                shell=ar.spec.spawn.shell,
                depends_on=base_deps,
            )
        )
        self._track(
            WaitForWindowStep(
                id=wait_id,
                description=f"wait for {ar.app_name}",
                app_name=ar.app_name,
                workspace_name=ws_name,
                match=ar.spec.match,
                timeout_s=ar.startup_timeout_s,
                depends_on=[spawn_id],
            )
        )
        return [wait_id]

    def place_window(self, ar: AppResolution, wr: WorkspaceResolution, deps: list[str]) -> None:
        """Emit placement/focus steps for an app."""
        wid = ar.match_decision.assigned_window_id

        if ar.needs_move or ar.status == ResolutionStatus.MISSING:
            self._track(
                MoveWindowToWorkspaceStep(
                    id=self._next_id("move"),
                    description=f"move {ar.app_name} to '{wr.name}'",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    window_id=wid,
                    depends_on=deps,
                )
            )

        self._emit_state_steps(ar, wr.name, wid, deps)
        self._emit_resize_steps(ar, wr.name, wid, deps)

        if ar.spec.placement.focus:
            self._track(
                FocusWindowStep(
                    id=self._next_id("focus"),
                    window_id=wid,
                    description=f"focus {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    depends_on=deps,
                )
            )

    def _emit_state_steps(self, ar: AppResolution, ws_name: str, wid: int | None, deps: list[str]) -> None:
        needs_float_or_tile_correction = any(d.kind == DriftKind.WRONG_FLOATING for d in ar.drift)
        if not needs_float_or_tile_correction and ar.status == ResolutionStatus.MISSING:
            needs_float_or_tile_correction = ar.spec.placement.floating
        if needs_float_or_tile_correction:
            prop = WindowProperty.FLOATING if ar.spec.placement.floating else WindowProperty.TILING
            self._track(
                SetWindowStateStep(
                    id=self._next_id("state"),
                    window_id=wid,
                    property=prop,
                    description=f"set {ar.app_name} {prop.value}",
                    app_name=ar.app_name,
                    workspace_name=ws_name,
                    depends_on=deps,
                )
            )

        needs_fullscreen = any(d.kind == DriftKind.WRONG_FULLSCREEN for d in ar.drift)
        if not needs_fullscreen and ar.status == ResolutionStatus.MISSING:
            needs_fullscreen = ar.spec.placement.fullscreen
        if needs_fullscreen:
            self._track(
                SetWindowStateStep(
                    id=self._next_id("state"),
                    window_id=wid,
                    property=WindowProperty.FULLSCREEN,
                    value=ar.spec.placement.fullscreen,
                    description=f"set {ar.app_name} fullscreen",
                    app_name=ar.app_name,
                    workspace_name=ws_name,
                    depends_on=deps,
                )
            )

        needs_maximized = any(d.kind == DriftKind.WRONG_MAXIMIZED for d in ar.drift)
        if not needs_maximized and ar.status == ResolutionStatus.MISSING:
            needs_maximized = ar.spec.placement.maximized
        if needs_maximized:
            self._track(
                SetWindowStateStep(
                    id=self._next_id("state"),
                    window_id=wid,
                    property=WindowProperty.MAXIMIZED,
                    value=ar.spec.placement.maximized,
                    description=f"set {ar.app_name} maximized",
                    app_name=ar.app_name,
                    workspace_name=ws_name,
                    depends_on=deps,
                )
            )

    def _emit_resize_steps(self, ar: AppResolution, ws_name: str, wid: int | None, deps: list[str]) -> None:
        if ar.spec.placement.column_width is not None:
            prop, px = self._parse_size(ar.spec.placement.column_width)
            self._track(
                ResizeWindowStep(
                    id=self._next_id("resize"),
                    window_id=wid,
                    axis=ResizeAxis.WIDTH,
                    proportion=prop,
                    pixels=px,
                    description=f"set column width for {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=ws_name,
                    depends_on=deps,
                )
            )

        if ar.spec.placement.window_height is not None:
            prop, px = self._parse_size(ar.spec.placement.window_height)
            self._track(
                ResizeWindowStep(
                    id=self._next_id("resize"),
                    window_id=wid,
                    axis=ResizeAxis.HEIGHT,
                    proportion=prop,
                    pixels=px,
                    description=f"set window height for {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=ws_name,
                    depends_on=deps,
                )
            )

    def focus_workspace(self, wr: WorkspaceResolution) -> None:
        self._track(
            FocusWorkspaceStep(
                id=self._next_id("focus-ws"),
                description=f"focus workspace '{wr.name}'",
                workspace_name=wr.name,
            )
        )

    def wire_app_dependencies(self, resolution: Resolution) -> None:
        deps_to_add: dict[str, list[str]] = {}
        for wr in resolution.workspace_resolutions:
            for ar in wr.app_resolutions:
                if not ar.spec.depends_on:
                    continue
                first_key = f"{wr.name}/{ar.app_name}"
                first_id = self._app_first.get(first_key)
                if first_id is None:
                    continue
                for dep_name in ar.spec.depends_on:
                    dep_key = f"{wr.name}/{dep_name}"
                    dep_last = self._app_last.get(dep_key)
                    if dep_last:
                        deps_to_add.setdefault(first_id, []).append(dep_last)

        if deps_to_add:
            self._steps = [
                s.model_copy(update={"depends_on": s.depends_on + deps_to_add[s.id]}) if s.id in deps_to_add else s
                for s in self._steps
            ]

    def build(self) -> list[PlanStep]:
        return topological_sort(self._steps)
