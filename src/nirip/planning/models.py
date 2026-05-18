"""Planning models."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Discriminator, Field, computed_field, model_validator

from nirip._base import NiripModel
from nirip.resolve.models import Resolution
from nirip.spec.models import MatchRule


class StepBase(NiripModel):
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    app_name: str | None = None
    workspace_name: str | None = None


class CreateWorkspaceStep(StepBase):
    kind: Literal["create_workspace"] = "create_workspace"
    target_output: str | None = None


class MoveWorkspaceToOutputStep(StepBase):
    kind: Literal["move_workspace_to_output"] = "move_workspace_to_output"
    target_output: str


class SpawnWindowStep(StepBase):
    kind: Literal["spawn_window"] = "spawn_window"
    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False


class WaitForWindowStep(StepBase):
    kind: Literal["wait_for_window"] = "wait_for_window"
    match: MatchRule
    timeout_s: float


class MoveWindowToWorkspaceStep(StepBase):
    kind: Literal["move_window_to_workspace"] = "move_window_to_workspace"
    window_id: int | None = None
    target_workspace: str


class WindowProperty(StrEnum):
    FLOATING = "floating"
    TILING = "tiling"
    FULLSCREEN = "fullscreen"
    MAXIMIZED = "maximized"


class SetWindowStateStep(StepBase):
    kind: Literal["set_window_state"] = "set_window_state"
    window_id: int | None = None
    property: WindowProperty
    value: bool = True


class ResizeAxis(StrEnum):
    WIDTH = "width"
    HEIGHT = "height"


class ResizeWindowStep(StepBase):
    kind: Literal["resize_window"] = "resize_window"
    window_id: int | None = None
    axis: ResizeAxis
    proportion: float | None = None
    pixels: int | None = None

    @model_validator(mode="after")
    def _exactly_one_size(self) -> ResizeWindowStep:
        has_prop = self.proportion is not None
        has_px = self.pixels is not None
        if has_prop == has_px:
            raise ValueError("exactly one of 'proportion' or 'pixels' must be set")
        return self


class FocusWindowStep(StepBase):
    kind: Literal["focus_window"] = "focus_window"
    window_id: int | None = None


class FocusWorkspaceStep(StepBase):
    kind: Literal["focus_workspace"] = "focus_workspace"


PlanStep = Annotated[
    CreateWorkspaceStep
    | MoveWorkspaceToOutputStep
    | SpawnWindowStep
    | WaitForWindowStep
    | MoveWindowToWorkspaceStep
    | SetWindowStateStep
    | ResizeWindowStep
    | FocusWindowStep
    | FocusWorkspaceStep,
    Discriminator("kind"),
]


class Plan(NiripModel):
    session_name: str
    steps: list[PlanStep]
    resolution: Resolution
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def requires_spawn(self) -> bool:
        return any(s.kind == "spawn_window" for s in self.steps)

    @computed_field
    @property
    def step_count(self) -> int:
        return len(self.steps)

    @computed_field
    @property
    def is_empty(self) -> bool:
        return len(self.steps) == 0


class SessionDiff(NiripModel):
    session_name: str
    already_matched: list[str] = Field(default_factory=list)
    will_spawn: list[str] = Field(default_factory=list)
    will_move: list[str] = Field(default_factory=list)
    drifted: list[str] = Field(default_factory=list)
    workspace_changes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def has_drift(self) -> bool:
        return bool(self.will_spawn or self.will_move or self.drifted or self.workspace_changes)

    @computed_field
    @property
    def has_errors(self) -> bool:
        return bool(self.errors)
