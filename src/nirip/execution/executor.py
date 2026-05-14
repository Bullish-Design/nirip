"""Plan executor."""
from __future__ import annotations

import time
from typing import Any, Protocol

from nirip.execution.actions import StepAction, action_for_step
from nirip.execution.models import ApplyResult, StepOutcome, StepResult
from nirip.execution.predicates import predicate_for_step
from nirip.planning.models import Plan


class ActionClient(Protocol):
    async def request(self, payload: StepAction) -> Any: ...


class PlanExecutor:
    """Execute a compiled plan against a runtime client/state pair."""

    def __init__(self, client: ActionClient | None = None) -> None:
        self.client = client

    async def execute(
        self,
        plan: Plan,
        snapshot: Any | None = None,
        *,
        stop_on_error: bool = False,
    ) -> ApplyResult:
        """Execute all steps in order and return outcomes."""

        start = time.monotonic()
        results: list[StepResult] = []

        for step in plan.steps:
            step_start = time.monotonic()
            predicate = predicate_for_step(step)
            if predicate is not None and snapshot is not None and predicate(snapshot):
                results.append(
                    StepResult(
                        step=step,
                        outcome=StepOutcome.SKIPPED,
                        message="already satisfied",
                        duration_s=time.monotonic() - step_start,
                    )
                )
                continue

            action = action_for_step(step)
            if action is not None and self.client is not None:
                try:
                    await self.client.request(action)
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        StepResult(
                            step=step,
                            outcome=StepOutcome.FAILED,
                            message=f"action failed: {exc}",
                            duration_s=time.monotonic() - step_start,
                        )
                    )
                    if stop_on_error:
                        break
                    continue

            results.append(
                StepResult(
                    step=step,
                    outcome=StepOutcome.COMPLETED,
                    message="completed",
                    duration_s=time.monotonic() - step_start,
                    window_id=step.window_id,
                )
            )

        success = all(r.outcome not in (StepOutcome.FAILED, StepOutcome.TIMED_OUT) for r in results)
        return ApplyResult(
            session_name=plan.session_name,
            success=success,
            steps=results,
            total_duration_s=time.monotonic() - start,
        )
