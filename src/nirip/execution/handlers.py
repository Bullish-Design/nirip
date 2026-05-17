"""Per-step execution handlers."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

from niri_pypc import actions
from niri_state import NiriState, Snapshot, WaitTimeoutError
from niri_state.api.config import NiriStateConfig
from niri_state.api.waiters import wait_until

from nirip.execution.models import SessionPorts, StepOutcome, StepResult
from nirip.execution.predicates import is_already_satisfied
from nirip.execution.runtime import SessionRuntime
from nirip.planning.models import (
    EnsureWorkspaceStep,
    FocusWindowStep,
    FocusWorkspaceStep,
    MoveWindowToWorkspaceStep,
    MoveWorkspaceToOutputStep,
    PlanStep,
    SetColumnWidthStep,
    SetFloatingStep,
    SetFullscreenStep,
    SetMaximizedStep,
    SetTilingStep,
    SetWindowHeightStep,
    SpawnWindowStep,
    WaitForWindowStep,
)
from nirip.resolve.matcher import evaluate_rule


async def _request(client: Any, req: Any) -> None:
    resp = client.request(req)
    if asyncio.iscoroutine(resp):
        await resp


_WAIT_CONFIG = NiriStateConfig()


async def _wait(state: NiriState, predicate: Callable[[Snapshot], bool], timeout: float) -> Snapshot:
    return await wait_until(state, predicate, config=_WAIT_CONFIG, timeout=timeout)


def _resolve_window_id(step: PlanStep, runtime: SessionRuntime) -> int | None:
    wid = getattr(step, "window_id", None)
    if wid is not None:
        return wid
    if step.app_name and step.app_name in runtime.apps:
        return runtime.apps[step.app_name].matched_window_id
    return None


async def execute_step(step: PlanStep, ports: SessionPorts, runtime: SessionRuntime) -> StepResult:
    if is_already_satisfied(step, ports.state.snapshot):
        return StepResult(step=step, outcome=StepOutcome.SKIPPED, message="already satisfied")

    match step:
        case EnsureWorkspaceStep():
            await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
            await _wait(
                ports.state,
                lambda snap: any(ws.name == step.workspace_name for ws in snap.workspaces.values()),
                timeout=3.0,
            )
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace ensured")
        case MoveWorkspaceToOutputStep():
            workspace_ref = actions.workspace_by_name(step.workspace_name or "")
            await _request(
                ports.client,
                actions.move_workspace_to_monitor(step.target_output, workspace_ref),
            )
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace moved")
        case SpawnWindowStep():
            env = os.environ.copy()
            env.update(step.env)
            if isinstance(step.command, str):
                proc = await asyncio.create_subprocess_exec("/bin/sh", "-lc", step.command, cwd=step.cwd, env=env)
            else:
                proc = await asyncio.create_subprocess_exec(*step.command, cwd=step.cwd, env=env)
            if step.app_name and step.app_name in runtime.apps:
                app_state = runtime.apps[step.app_name]
                app_state.spawned = True
                app_state.spawn_pid = proc.pid
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="spawned", spawn_pid=proc.pid)
        case WaitForWindowStep():
            matched_wid: int | None = None

            def predicate(snap: Any) -> bool:
                nonlocal matched_wid
                for w in snap.windows.values():
                    matched, _, _ = evaluate_rule(step.match, w)
                    if matched:
                        matched_wid = w.id
                        return True
                return False

            await _wait(ports.state, predicate, step.timeout_s)
            if step.app_name and step.app_name in runtime.apps:
                runtime.apps[step.app_name].matched_window_id = matched_wid
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message=f"window appeared (id={matched_wid})",
                window_id=matched_wid,
            )
        case MoveWindowToWorkspaceStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            workspace_ref = actions.workspace_by_name(step.target_workspace)
            await _request(
                ports.client,
                actions.move_window_to_workspace(workspace_ref, window_id=wid),
            )
            def moved(snap: Snapshot) -> bool:
                w = snap.windows.get(wid)
                target = next((ws for ws in snap.workspaces.values() if ws.name == step.target_workspace), None)
                return w is not None and target is not None and w.workspace_id == target.id

            await _wait(ports.state, moved, timeout=5.0)
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="window moved",
                window_id=wid,
            )
        case SetFloatingStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            await _request(ports.client, actions.move_window_to_floating(wid))
            try:
                await _wait(
                    ports.state,
                    lambda snap: (w := snap.windows.get(wid)) is not None and w.is_floating,
                    timeout=1.5,
                )
            except WaitTimeoutError:
                pass
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="window set floating",
                window_id=wid,
            )
        case SetTilingStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            await _request(ports.client, actions.move_window_to_tiling(wid))
            try:
                await _wait(
                    ports.state,
                    lambda snap: (w := snap.windows.get(wid)) is not None and not w.is_floating,
                    timeout=1.5,
                )
            except WaitTimeoutError:
                pass
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="window set tiling",
                window_id=wid,
            )
        case SetFullscreenStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            await _request(ports.client, actions.fullscreen_window(wid))
            try:
                await _wait(
                    ports.state,
                    lambda snap: (w := snap.windows.get(wid)) is not None
                    and getattr(w, "is_fullscreen", False) == step.fullscreen,
                    timeout=1.5,
                )
            except WaitTimeoutError:
                pass
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="fullscreen toggled",
                window_id=wid,
            )
        case SetMaximizedStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            await _request(ports.client, actions.maximize_window_to_edges(wid))
            try:
                await _wait(
                    ports.state,
                    lambda snap: (w := snap.windows.get(wid)) is not None
                    and getattr(w, "is_maximized", False) == step.maximized,
                    timeout=1.5,
                )
            except WaitTimeoutError:
                pass
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="maximized toggled",
                window_id=wid,
            )
        case SetColumnWidthStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            await _request(ports.client, actions.focus_window(wid))
            change = (
                actions.size_set_proportion(step.proportion)
                if step.proportion is not None
                else actions.size_set_fixed(step.pixels or 0)
            )
            await _request(ports.client, actions.set_column_width(change))
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="column width set",
                window_id=wid,
            )
        case SetWindowHeightStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            change = (
                actions.size_set_proportion(step.proportion)
                if step.proportion is not None
                else actions.size_set_fixed(step.pixels or 0)
            )
            await _request(ports.client, actions.set_window_height(change, wid))
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="window height set",
                window_id=wid,
            )
        case FocusWindowStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            await _request(ports.client, actions.focus_window(wid))
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="window focused",
                window_id=wid,
            )
        case FocusWorkspaceStep():
            await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace focused")
        case _:
            return StepResult(step=step, outcome=StepOutcome.FAILED, message="unhandled step kind")
