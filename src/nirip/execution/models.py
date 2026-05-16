"""Execution layer models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import computed_field

from niri_pypc import NiriClient
from niri_state import NiriState

from nirip._base import NiripModel
from nirip.planning.models import PlanStep


class StepOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class StepResult(NiripModel):
    step: PlanStep
    outcome: StepOutcome
    message: str
    window_id: int | None = None
    duration_s: float = 0.0


class ApplyResult(NiripModel):
    session_name: str
    success: bool
    steps: list[StepResult]
    total_duration_s: float

    @computed_field
    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.COMPLETED)

    @computed_field
    @property
    def skipped_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.SKIPPED)

    @computed_field
    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT)]


@dataclass
class SessionPorts:
    """Runtime services for session execution."""

    state: NiriState
    client: NiriClient
