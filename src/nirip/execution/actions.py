"""Plan step to action translation."""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any

from nirip.planning.models import PlanStep, StepKind


class StepAction(BaseModel):
    """Typed action descriptor for a plan step."""

    kind: str
    window_id: int | None = None
    workspace_name: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


def action_for_step(step: PlanStep) -> StepAction | None:
    """Return a typed action descriptor for a plan step."""

    if step.kind == StepKind.WAIT_FOR_WINDOW:
        return None
    return StepAction(
        kind=step.kind.value,
        window_id=step.window_id,
        workspace_name=step.workspace_name,
        extra=dict(step.metadata),
    )
