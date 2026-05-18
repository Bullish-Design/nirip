"""Resolution layer models."""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import computed_field

from nirip._base import NiripModel
from nirip.spec.models import AppSpec


class MatchTier(IntEnum):
    """Match quality. Higher = more specific = preferred in assignment."""

    NONE = 0
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    EXACT = 4


class MatchCandidate(NiripModel):
    window_id: int
    tier: MatchTier
    reasons: list[str]


class MatchDecision(NiripModel):
    app_name: str
    workspace_name: str
    assigned_window_id: int | None = None
    candidates: list[MatchCandidate]
    tier: MatchTier = MatchTier.NONE
    reasons: list[str]

    @computed_field
    @property
    def is_ambiguous(self) -> bool:
        if len(self.candidates) < 2:
            return False
        tiers = [c.tier for c in self.candidates]
        top = max(tiers)
        return sum(1 for tier in tiers if tier == top) > 1

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
    spec: AppSpec
    startup_timeout_s: float

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
    focus: bool
    app_resolutions: list[AppResolution]


class Resolution(NiripModel):
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]
    warnings: list[str]

    @computed_field
    @property
    def all_app_resolutions(self) -> list[AppResolution]:
        return [ar for wr in self.workspace_resolutions for ar in wr.app_resolutions]

    @computed_field
    @property
    def unmatched_apps(self) -> list[AppResolution]:
        return [ar for ar in self.all_app_resolutions if ar.status == ResolutionStatus.MISSING]

    @computed_field
    @property
    def ambiguous_apps(self) -> list[AppResolution]:
        return [ar for ar in self.all_app_resolutions if ar.status == ResolutionStatus.AMBIGUOUS]

    @computed_field
    @property
    def has_drift(self) -> bool:
        for wr in self.workspace_resolutions:
            if not wr.exists or not wr.output_correct:
                return True
            if any(ar.status in (ResolutionStatus.DRIFTED, ResolutionStatus.MISSING) for ar in wr.app_resolutions):
                return True
        return False

    @computed_field
    @property
    def fully_converged(self) -> bool:
        return not self.has_drift and not self.ambiguous_apps
