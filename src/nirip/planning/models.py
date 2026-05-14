"""Planning models."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, computed_field

from nirip.resolve.models import Resolution


class StepKind(StrEnum):
    ENSURE_WORKSPACE = "ensure_workspace"
    MOVE_WORKSPACE_TO_OUTPUT = "move_workspace_to_output"
    SPAWN_WINDOW = "spawn_window"
    WAIT_FOR_WINDOW = "wait_for_window"
    MOVE_WINDOW_TO_WORKSPACE = "move_window_to_workspace"
    SET_FLOATING = "set_floating"
    SET_TILING = "set_tiling"
    FOCUS_WINDOW = "focus_window"
    FOCUS_WORKSPACE = "focus_workspace"


class PlanStep(BaseModel):
    """Single imperative step."""

    id: str
    kind: StepKind
    app_name: str | None = None
    workspace_name: str | None = None
    window_id: int | None = None
    description: str
    depends_on: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    """Compiled execution plan."""

    session_name: str
    steps: list[PlanStep]
    resolution: Resolution
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def requires_spawn(self) -> bool:
        return any(s.kind == StepKind.SPAWN_WINDOW for s in self.steps)

    @computed_field
    @property
    def step_count(self) -> int:
        return len(self.steps)

    @computed_field
    @property
    def is_empty(self) -> bool:
        return len(self.steps) == 0


class SessionDiff(BaseModel):
    """Human-readable diff between desired and current state."""

    session_name: str
    already_matched: list[str] = Field(default_factory=list)
    will_spawn: list[str] = Field(default_factory=list)
    will_move: list[str] = Field(default_factory=list)
    will_adjust: list[str] = Field(default_factory=list)
    workspace_changes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def has_drift(self) -> bool:
        return bool(self.will_spawn or self.will_move or self.will_adjust or self.workspace_changes)

    @computed_field
    @property
    def has_errors(self) -> bool:
        return bool(self.errors)
