"""Resolution and normalization models."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from nirip.spec.models import MatchRule, PlacementSpec, SessionOptions, SpawnSpec


class NormalizedApp(BaseModel):
    """An app after default merging and reference resolution."""

    name: str
    workspace_name: str
    match: MatchRule
    spawn: SpawnSpec | None
    placement: PlacementSpec
    optional: bool
    startup_timeout_s: float
    depends_on: list[str]


class NormalizedWorkspace(BaseModel):
    """A workspace after default merging."""

    name: str
    output: str | None
    focus: bool
    app_names: list[str]


class NormalizedSession(BaseModel):
    """The session spec after all normalization passes."""

    name: str
    description: str
    options: SessionOptions
    workspaces: list[NormalizedWorkspace]
    apps: list[NormalizedApp]
    app_index: dict[str, NormalizedApp] = Field(default_factory=dict)


class MatchCandidate(BaseModel):
    """A single window evaluated against a MatchRule."""

    window_id: int
    confidence: float
    reasons: list[str]


class MatchDecision(BaseModel):
    """Result of matching an app against all live windows."""

    app_name: str
    workspace_name: str
    best: int | None = None
    candidates: list[MatchCandidate]
    confidence: float = 0.0
    rationale: list[str]

    @computed_field
    @property
    def is_ambiguous(self) -> bool:
        high_confidence = [c for c in self.candidates if c.confidence > 0.6]
        return len(high_confidence) > 1

    @computed_field
    @property
    def is_matched(self) -> bool:
        return self.best is not None


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


class DriftItem(BaseModel):
    """A single deviation from desired state."""

    kind: DriftKind
    current: str
    desired: str


class AppResolution(BaseModel):
    """Resolution status for a single declared app."""

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


class WorkspaceResolution(BaseModel):
    """Resolution status for a single declared workspace."""

    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    app_resolutions: list[AppResolution]


class Resolution(BaseModel):
    """Complete resolution of a session spec against live state."""

    session_name: str
    workspace_resolutions: list[WorkspaceResolution]
    unmatched_apps: list[AppResolution]
    ambiguous_apps: list[AppResolution]
    warnings: list[str]

    @computed_field
    @property
    def has_drift(self) -> bool:
        return any(
            app.action_required for ws in self.workspace_resolutions for app in ws.app_resolutions
        ) or any((not ws.exists or not ws.output_correct) for ws in self.workspace_resolutions)

    @computed_field
    @property
    def fully_converged(self) -> bool:
        return not self.has_drift and not self.unmatched_apps and not self.ambiguous_apps
