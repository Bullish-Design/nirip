"""Resolution layer models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, computed_field

from nirip._base import NiripModel
from nirip.spec.models import MatchRule, PlacementSpec, SessionOptions, SpawnSpec


class NormalizedApp(NiripModel):
    name: str
    workspace_name: str
    match: MatchRule
    spawn: SpawnSpec | None
    placement: PlacementSpec
    optional: bool
    startup_timeout_s: float
    depends_on: list[str]


class NormalizedWorkspace(NiripModel):
    name: str
    output: str | None
    focus: bool
    app_names: list[str]


class NormalizedSession(NiripModel):
    name: str
    description: str
    options: SessionOptions
    workspaces: list[NormalizedWorkspace]
    apps: list[NormalizedApp]
    app_index: dict[str, NormalizedApp] = Field(default_factory=dict)


class MatchCandidate(NiripModel):
    window_id: int
    confidence: float
    reasons: list[str]


class MatchDecision(NiripModel):
    app_name: str
    workspace_name: str
    assigned_window_id: int | None = None
    candidates: list[MatchCandidate]
    confidence: float = 0.0
    rationale: list[str]

    @computed_field
    @property
    def is_ambiguous(self) -> bool:
        return sum(1 for c in self.candidates if c.confidence > 0.6) > 1

    @computed_field
    @property
    def is_matched(self) -> bool:
        return self.assigned_window_id is not None


class ResolutionStatus(StrEnum):
    MATCHED = "matched"
    DRIFTED = "drifted"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    OPTIONAL_MISSING = "optional_missing"


class DriftKind(StrEnum):
    WRONG_WORKSPACE = "wrong_workspace"
    WRONG_FLOATING = "wrong_floating"
    WRONG_FULLSCREEN = "wrong_fullscreen"
    WRONG_MAXIMIZED = "wrong_maximized"


class DriftItem(NiripModel):
    kind: DriftKind
    current: str
    desired: str


class AppResolution(NiripModel):
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    match_decision: MatchDecision
    drift: list[DriftItem]
    action_required: bool

    @computed_field
    @property
    def needs_spawn(self) -> bool:
        return self.status == ResolutionStatus.MISSING and self.action_required

    @computed_field
    @property
    def needs_move(self) -> bool:
        return any(d.kind == DriftKind.WRONG_WORKSPACE for d in self.drift)


class WorkspaceResolution(NiripModel):
    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    app_resolutions: list[AppResolution]


class Resolution(NiripModel):
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]
    unmatched_apps: list[AppResolution]
    ambiguous_apps: list[AppResolution]
    warnings: list[str]

    @computed_field
    @property
    def has_drift(self) -> bool:
        for wr in self.workspace_resolutions:
            if not wr.exists or not wr.output_correct:
                return True
            if any(ar.action_required for ar in wr.app_resolutions):
                return True
        return bool(self.unmatched_apps)

    @computed_field
    @property
    def fully_converged(self) -> bool:
        return not self.has_drift and not self.ambiguous_apps
