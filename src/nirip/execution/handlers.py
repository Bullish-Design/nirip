"""Per-step execution handlers."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from niri_pypc import actions
from niri_state import WaitTimeoutError
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


async def _wait(state: Any, predicate: Any, timeout: float) -> Any:
    try:
        return await wait_until(state, predicate, timeout=timeout)
    except TypeError:
        return await wait_until(state, predicate, config=None, timeout=timeout)


async def execute_step(step: PlanStep, ports: SessionPorts, runtime: SessionRuntime) -> StepResult:
    t0 = time.monotonic()
    if is_already_satisfied(step, ports.state.snapshot):
        return StepResult(step=step, outcome=StepOutcome.SKIPPED, message="already satisfied")

    try:
        match step:
            case EnsureWorkspaceStep():
                await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace ensured")
            case MoveWorkspaceToOutputStep():
                await _request(
                    ports.client,
                    actions.move_workspace_to_monitor(step.target_output, actions.workspace_by_name(step.workspace_name or "")),
                )
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace moved")
            case SpawnWindowStep():
                env = os.environ.copy()
                env.update(step.env)
                if isinstance(step.command, str):
                    proc = await asyncio.create_subprocess_exec(
                        "/bin/sh", "-lc", step.command, cwd=step.cwd, env=env
                    )
                else:
                    proc = await asyncio.create_subprocess_exec(*step.command, cwd=step.cwd, env=env)
                if step.app_name and step.app_name in runtime.apps:
                    app_state = runtime.apps[step.app_name]
                    app_state.spawned = True
                    app_state.spawn_pid = proc.pid
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="spawned", window_id=proc.pid)
            case WaitForWindowStep():
                async def predicate(snap: Any) -> bool:
                    for w in snap.windows.values():
                        matched, _, _ = evaluate_rule(step.match, w)
                        if matched:
                            return True
                    return False

                await _wait(ports.state, predicate, step.timeout_s)
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window appeared")
            case MoveWindowToWorkspaceStep():
                await _request(
                    ports.client,
                    actions.move_window_to_workspace(actions.workspace_by_name(step.target_workspace), window_id=step.window_id),
                )
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window moved", window_id=step.window_id)
            case SetFloatingStep():
                await _request(ports.client, actions.move_window_to_floating(step.window_id))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window set floating", window_id=step.window_id)
            case SetTilingStep():
                await _request(ports.client, actions.move_window_to_tiling(step.window_id))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window set tiling", window_id=step.window_id)
            case SetFullscreenStep():
                await _request(ports.client, actions.fullscreen_window(step.window_id))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="fullscreen toggled", window_id=step.window_id)
            case SetMaximizedStep():
                await _request(ports.client, actions.maximize_window_to_edges(step.window_id))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="maximized toggled", window_id=step.window_id)
            case SetColumnWidthStep():
                await _request(ports.client, actions.focus_window(step.window_id))
                change = (
                    actions.size_set_proportion(step.proportion)
                    if step.proportion is not None
                    else actions.size_set_fixed(step.pixels or 0)
                )
                await _request(ports.client, actions.set_column_width(change))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="column width set", window_id=step.window_id)
            case SetWindowHeightStep():
                change = (
                    actions.size_set_proportion(step.proportion)
                    if step.proportion is not None
                    else actions.size_set_fixed(step.pixels or 0)
                )
                await _request(ports.client, actions.set_window_height(change, step.window_id))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window height set", window_id=step.window_id)
            case FocusWindowStep():
                await _request(ports.client, actions.focus_window(step.window_id))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window focused", window_id=step.window_id)
            case FocusWorkspaceStep():
                await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
                return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace focused")
    except WaitTimeoutError:
        return StepResult(
            step=step,
            outcome=StepOutcome.TIMED_OUT,
            message="timed out waiting for condition",
            duration_s=time.monotonic() - t0,
        )
    except Exception as e:
        return StepResult(
            step=step,
            outcome=StepOutcome.FAILED,
            message=str(e),
            duration_s=time.monotonic() - t0,
        )

    return StepResult(step=step, outcome=StepOutcome.FAILED, message="unhandled step", duration_s=time.monotonic() - t0)
