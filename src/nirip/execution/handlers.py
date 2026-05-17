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
from nirip.resolve.matcher import evaluate_rule


async def _request(client: Any, req: Any) -> None:
    resp = client.request(req)
    if asyncio.iscoroutine(resp):
        await resp


_WAIT_CONFIG = NiriStateConfig()

_STATE_ACTIONS: dict[WindowProperty, Callable[[int], Any]] = {
    WindowProperty.FLOATING: actions.move_window_to_floating,
    WindowProperty.TILING: actions.move_window_to_tiling,
    WindowProperty.FULLSCREEN: actions.fullscreen_window,
    WindowProperty.MAXIMIZED: actions.maximize_window_to_edges,
}

_STATE_CHECKS: dict[WindowProperty, Callable[[Any], bool]] = {
    WindowProperty.FLOATING: lambda w: w.is_floating,
    WindowProperty.TILING: lambda w: not w.is_floating,
    WindowProperty.FULLSCREEN: lambda w: getattr(w, "is_fullscreen", False),
    WindowProperty.MAXIMIZED: lambda w: getattr(w, "is_maximized", False),
}


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
        case CreateWorkspaceStep():
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
            wid_int = wid
            target_workspace = step.target_workspace
            workspace_ref = actions.workspace_by_name(step.target_workspace)
            await _request(
                ports.client,
                actions.move_window_to_workspace(workspace_ref, window_id=wid_int),
            )

            def moved(snap: Snapshot) -> bool:
                w = snap.windows.get(wid_int)
                target = next((ws for ws in snap.workspaces.values() if ws.name == target_workspace), None)
                return w is not None and target is not None and w.workspace_id == target.id

            await _wait(ports.state, moved, timeout=5.0)
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message="window moved",
                window_id=wid_int,
            )
        case SetWindowStateStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            await _request(ports.client, _STATE_ACTIONS[step.property](wid))
            check = _STATE_CHECKS[step.property]
            target_val = step.value
            try:
                await _wait(
                    ports.state,
                    lambda snap, _wid=wid, _check=check, _val=target_val: (
                        (w := snap.windows.get(_wid)) is not None and _check(w) == _val
                    ),
                    timeout=1.5,
                )
            except WaitTimeoutError:
                pass
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message=f"{step.property} set",
                window_id=wid,
            )
        case ResizeWindowStep():
            wid = _resolve_window_id(step, runtime)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            change = (
                actions.size_set_proportion(step.proportion)
                if step.proportion is not None
                else actions.size_set_fixed(step.pixels or 0)
            )
            if step.axis == ResizeAxis.WIDTH:
                await _request(ports.client, actions.focus_window(wid))
                await _request(ports.client, actions.set_column_width(change))
            else:
                await _request(ports.client, actions.set_window_height(change, wid))
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message=f"{step.axis} resized",
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
