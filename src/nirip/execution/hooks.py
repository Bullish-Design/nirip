"""Execution lifecycle hooks."""

from __future__ import annotations

import sys
from typing import Protocol

from nirip.execution.models import ApplyResult, StepResult
from nirip.planning.models import PlanStep


class ExecutionHook(Protocol):
    def on_step_start(self, step: PlanStep) -> None: ...
    def on_step_complete(self, step: PlanStep, result: StepResult) -> None: ...
    def on_plan_complete(self, result: ApplyResult) -> None: ...


class NullHook:
    """Default no-op hook."""

    def on_step_start(self, step: PlanStep) -> None:
        del step

    def on_step_complete(self, step: PlanStep, result: StepResult) -> None:
        del step, result

    def on_plan_complete(self, result: ApplyResult) -> None:
        del result


class LoggingHook:
    """Prints step progress to stderr."""

    def on_step_start(self, step: PlanStep) -> None:
        print(f"  -> {step.description}...", file=sys.stderr, flush=True)

    def on_step_complete(self, step: PlanStep, result: StepResult) -> None:
        del step
        print(f"     {result.outcome} ({result.duration_s:.1f}s)", file=sys.stderr, flush=True)

    def on_plan_complete(self, result: ApplyResult) -> None:
        status = "OK" if result.success else "FAILED"
        print(f"  Plan {status} in {result.total_duration_s:.1f}s", file=sys.stderr, flush=True)
