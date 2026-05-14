"""Plan step to action translation."""
from __future__ import annotations

from typing import Any

from nirip.planning.models import PlanStep, StepKind


def action_for_step(step: PlanStep) -> dict[str, Any] | None:
    """Return a lightweight action descriptor for a plan step."""

    if step.kind == StepKind.WAIT_FOR_WINDOW:
        return None
    action: dict[str, Any] = {"kind": step.kind.value}
    action.update(step.metadata)
    if step.window_id is not None:
        action["window_id"] = step.window_id
    if step.workspace_name is not None:
        action["workspace_name"] = step.workspace_name
    return action
