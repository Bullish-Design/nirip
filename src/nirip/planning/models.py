"""Planning models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Discriminator, Field, computed_field

from nirip._base import NiripModel
from nirip.resolve.models import Resolution
from nirip.spec.models import MatchRule


class StepBase(NiripModel):
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    app_name: str | None = None
    workspace_name: str | None = None


class EnsureWorkspaceStep(StepBase):
    kind: Literal["ensure_workspace"] = "ensure_workspace"
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
    window_id: int
    target_workspace: str


class SetFloatingStep(StepBase):
    kind: Literal["set_floating"] = "set_floating"
    window_id: int


class SetTilingStep(StepBase):
    kind: Literal["set_tiling"] = "set_tiling"
    window_id: int


class SetFullscreenStep(StepBase):
    kind: Literal["set_fullscreen"] = "set_fullscreen"
    window_id: int
    fullscreen: bool


class SetMaximizedStep(StepBase):
    kind: Literal["set_maximized"] = "set_maximized"
    window_id: int
    maximized: bool


class SetColumnWidthStep(StepBase):
    kind: Literal["set_column_width"] = "set_column_width"
    window_id: int
    proportion: float | None = None
    pixels: int | None = None


class SetWindowHeightStep(StepBase):
    kind: Literal["set_window_height"] = "set_window_height"
    window_id: int
    proportion: float | None = None
    pixels: int | None = None


class FocusWindowStep(StepBase):
    kind: Literal["focus_window"] = "focus_window"
    window_id: int


class FocusWorkspaceStep(StepBase):
    kind: Literal["focus_workspace"] = "focus_workspace"


PlanStep = Annotated[
    EnsureWorkspaceStep
    | MoveWorkspaceToOutputStep
    | SpawnWindowStep
    | WaitForWindowStep
    | MoveWindowToWorkspaceStep
    | SetFloatingStep
    | SetTilingStep
    | SetFullscreenStep
    | SetMaximizedStep
    | SetColumnWidthStep
    | SetWindowHeightStep
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
