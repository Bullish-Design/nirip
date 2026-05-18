"""Async plan execution engine."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from niri_pypc import NiriClient, actions
from niri_state import NiriState, Snapshot, WaitTimeoutError
from niri_state.api.config import NiriStateConfig
from niri_state.api.waiters import wait_until
from pydantic import BaseModel

from nirip.plan import Plan, PlanStep, ResizeAxis, StepKind, WindowProperty
from nirip.resolve import evaluate_rule
from nirip.spec import _FROZEN, SessionOptions

_WAIT_CONFIG = NiriStateConfig()  # frozen default wait behavior for state confirmations


class StepOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class StepResult(BaseModel):
    model_config = _FROZEN

    step: PlanStep
    outcome: StepOutcome
    message: str
    window_id: int | None = None
    spawn_pid: int | None = None
    duration_s: float = 0.0


class ApplyResult(BaseModel):
    model_config = _FROZEN

    session_name: str
    success: bool
    steps: list[StepResult]
    total_duration_s: float

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.COMPLETED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.SKIPPED)

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT)]


@dataclass
class SessionRuntime:
    state: NiriState
    client: NiriClient


class ExecutionHook(Protocol):
    def on_step_start(self, step: PlanStep) -> None: ...

    def on_step_complete(self, step: PlanStep, result: StepResult) -> None: ...

    def on_plan_complete(self, result: ApplyResult) -> None: ...


class _NullHook:
    def on_step_start(self, step: PlanStep) -> None:
        pass

    def on_step_complete(self, step: PlanStep, result: StepResult) -> None:
        pass

    def on_plan_complete(self, result: ApplyResult) -> None:
        pass


@dataclass
class _AppState:
    matched_window_id: int | None = None
    spawn_process: Any = None


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


async def _request(client: Any, req: Any) -> None:
    resp = client.request(req)
    if asyncio.iscoroutine(resp):
        await resp


async def _wait(state: NiriState, predicate: Callable[[Snapshot], bool], timeout: float) -> Snapshot:
    return await wait_until(state, predicate, config=_WAIT_CONFIG, timeout=timeout)


def _resolve_wid(step: PlanStep, apps: dict[str, _AppState]) -> int | None:
    if step.window_id is not None:
        return step.window_id
    if step.app_name and step.workspace_name:
        app_key = f"{step.workspace_name}/{step.app_name}"
        if app_key in apps:
            return apps[app_key].matched_window_id
    return None


def _is_satisfied(step: PlanStep, snapshot: Snapshot) -> bool:
    match step.kind:
        case StepKind.CREATE_WORKSPACE:
            return any(ws.name == step.workspace_name for ws in snapshot.workspaces.values())
        case StepKind.MOVE_WINDOW:
            if step.window_id is None:
                return False
            w = snapshot.windows.get(step.window_id)
            if w is None:
                return False
            target = next((ws for ws in snapshot.workspaces.values() if ws.name == step.workspace_name), None)
            return target is not None and w.workspace_id == target.id
        case StepKind.SET_STATE:
            if step.window_id is None or step.property is None:
                return False
            w = snapshot.windows.get(step.window_id)
            if w is None:
                return False
            return _STATE_CHECKS[step.property](w) == step.value
        case _:
            return False


async def _execute_step(step: PlanStep, ports: SessionRuntime, apps: dict[str, _AppState]) -> StepResult:
    if _is_satisfied(step, ports.state.snapshot):
        return StepResult(step=step, outcome=StepOutcome.SKIPPED, message="already satisfied")

    match step.kind:
        case StepKind.CREATE_WORKSPACE:
            await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
            await _wait(
                ports.state,
                lambda snap: any(ws.name == step.workspace_name for ws in snap.workspaces.values()),
                timeout=3.0,
            )
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace ensured")

        case StepKind.MOVE_WORKSPACE_TO_OUTPUT:
            workspace_ref = actions.workspace_by_name(step.workspace_name or "")
            await _request(
                ports.client,
                actions.move_workspace_to_monitor(step.target_output or "", workspace_ref),
            )
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace moved")

        case StepKind.SPAWN_WINDOW:
            env = os.environ.copy()
            env.update(step.env)
            if isinstance(step.command, str):
                proc = await asyncio.create_subprocess_exec("/bin/sh", "-c", step.command, cwd=step.cwd, env=env)
            else:
                proc = await asyncio.create_subprocess_exec(*(step.command or []), cwd=step.cwd, env=env)
            if step.app_name and step.workspace_name:
                app_key = f"{step.workspace_name}/{step.app_name}"
                if app_key in apps:
                    apps[app_key].spawn_process = proc
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="spawned", spawn_pid=proc.pid)

        case StepKind.WAIT_FOR_WINDOW:
            matched_wid: int | None = None
            rule = step.match
            if rule is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="missing match rule")

            def predicate(snap: Any) -> bool:
                nonlocal matched_wid
                for w in snap.windows.values():
                    matched, _ = evaluate_rule(rule, w)
                    if matched:
                        matched_wid = w.id
                        return True
                return False

            app_key = f"{step.workspace_name}/{step.app_name}" if step.app_name and step.workspace_name else ""
            proc = apps.get(app_key, _AppState()).spawn_process
            if proc is not None:
                wait_task = asyncio.create_task(_wait(ports.state, predicate, step.timeout_s or 0.0))
                exit_task = asyncio.create_task(proc.wait())
                done, pending = await asyncio.wait({wait_task, exit_task}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                if exit_task in done and wait_task not in done:
                    rc = exit_task.result()
                    return StepResult(
                        step=step,
                        outcome=StepOutcome.FAILED,
                        message=f"process exited with code {rc} before window appeared",
                    )
                if wait_task in done:
                    await wait_task
            else:
                await _wait(ports.state, predicate, step.timeout_s or 0.0)

            if app_key and app_key in apps:
                apps[app_key].matched_window_id = matched_wid
            return StepResult(
                step=step,
                outcome=StepOutcome.COMPLETED,
                message=f"window appeared (id={matched_wid})",
                window_id=matched_wid,
            )

        case StepKind.MOVE_WINDOW:
            wid = _resolve_wid(step, apps)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            wid_int = wid
            target_workspace = step.workspace_name or ""
            workspace_ref = actions.workspace_by_name(target_workspace)
            await _request(ports.client, actions.move_window_to_workspace(workspace_ref, window_id=wid_int))

            def moved(snap: Snapshot) -> bool:
                w = snap.windows.get(wid_int)
                target = next((ws for ws in snap.workspaces.values() if ws.name == target_workspace), None)
                return w is not None and target is not None and w.workspace_id == target.id

            await _wait(ports.state, moved, timeout=5.0)
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window moved", window_id=wid_int)

        case StepKind.SET_STATE:
            wid = _resolve_wid(step, apps)
            if wid is None or step.property is None:
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
                return StepResult(
                    step=step,
                    outcome=StepOutcome.COMPLETED,
                    message=f"{step.property} set (unconfirmed)",
                    window_id=wid,
                )
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message=f"{step.property} set", window_id=wid)

        case StepKind.RESIZE:
            wid = _resolve_wid(step, apps)
            if wid is None or step.axis is None:
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
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message=f"{step.axis} resized", window_id=wid)

        case StepKind.FOCUS_WINDOW:
            wid = _resolve_wid(step, apps)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
            await _request(ports.client, actions.focus_window(wid))
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window focused", window_id=wid)

        case StepKind.FOCUS_WORKSPACE:
            await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace focused")

        case _:
            return StepResult(step=step, outcome=StepOutcome.FAILED, message="unhandled step kind")


async def execute_plan(
    plan: Plan,
    ports: SessionRuntime,
    options: SessionOptions,
    hook: ExecutionHook | None = None,
) -> ApplyResult:
    t0 = time.monotonic()
    exec_hook = hook or _NullHook()

    apps: dict[str, _AppState] = {}
    for step in plan.steps:
        if step.app_name and step.workspace_name:
            key = f"{step.workspace_name}/{step.app_name}"
            if key not in apps:
                apps[key] = _AppState()

    results: list[StepResult] = []
    for step in plan.steps:
        exec_hook.on_step_start(step)
        t_step = time.monotonic()
        try:
            result = await _execute_step(step, ports, apps)
        except WaitTimeoutError:
            result = StepResult(
                step=step,
                outcome=StepOutcome.TIMED_OUT,
                message="timed out waiting for condition",
                duration_s=time.monotonic() - t_step,
            )
        except (ConnectionError, OSError) as e:
            result = StepResult(
                step=step,
                outcome=StepOutcome.FAILED,
                message=f"transport error: {e}",
                duration_s=time.monotonic() - t_step,
            )

        if result.duration_s == 0.0:
            result = result.model_copy(update={"duration_s": time.monotonic() - t_step})

        exec_hook.on_step_complete(step, result)
        results.append(result)
        if result.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT) and options.stop_on_error:
            break

    apply_result = ApplyResult(
        session_name=plan.session_name,
        success=all(r.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED) for r in results),
        steps=results,
        total_duration_s=time.monotonic() - t0,
    )
    exec_hook.on_plan_complete(apply_result)
    return apply_result
