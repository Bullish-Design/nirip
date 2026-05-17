"""Plan executor."""

from __future__ import annotations

import time

from niri_state import WaitTimeoutError

from nirip.execution.handlers import execute_step
from nirip.execution.models import ApplyResult, SessionPorts, StepOutcome, StepResult
from nirip.execution.runtime import AppRuntimeState, SessionRuntime
from nirip.planning.models import Plan
from nirip.spec.models import SessionOptions


async def execute_plan(plan: Plan, ports: SessionPorts, options: SessionOptions) -> ApplyResult:
    t0 = time.monotonic()
    runtime = _init_runtime(plan)

    results: list[StepResult] = []
    for step in plan.steps:
        t_step = time.monotonic()
        try:
            result = await execute_step(step, ports, runtime)
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
        results.append(result)
        if result.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT) and options.stop_on_error:
            break

    return ApplyResult(
        session_name=plan.session_name,
        success=all(r.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED) for r in results),
        steps=results,
        total_duration_s=time.monotonic() - t0,
    )


def _init_runtime(plan: Plan) -> SessionRuntime:
    runtime = SessionRuntime(session_name=plan.session_name, started_at=time.monotonic())
    for step in plan.steps:
        if step.app_name and step.app_name not in runtime.apps:
            runtime.apps[step.app_name] = AppRuntimeState(
                app_name=step.app_name,
                workspace_name=step.workspace_name or "",
            )
    return runtime
