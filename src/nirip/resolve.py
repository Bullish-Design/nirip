"""Window matching, assignment, and resolution against live state."""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import IntEnum, StrEnum
from functools import lru_cache
from typing import Any, NamedTuple, Protocol, runtime_checkable

from niri_pypc.types.generated.models import Window
from niri_state import Snapshot
from pydantic import BaseModel, Field

from nirip.spec import _FROZEN, AppSpec, MatchRule, SessionSpec


@runtime_checkable
class WorkspaceLike(Protocol):
    """Minimal workspace interface used by drift detection."""

    @property
    def id(self) -> int: ...

    @property
    def name(self) -> str | None: ...

    @property
    def output(self) -> str | None: ...


class MatchTier(IntEnum):
    """Match quality. Higher = more specific = preferred in assignment."""

    NONE = 0
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    EXACT = 4


class DriftKind(StrEnum):
    WRONG_WORKSPACE = "wrong_workspace"
    WRONG_FLOATING = "wrong_floating"
    WRONG_FULLSCREEN = "wrong_fullscreen"
    WRONG_MAXIMIZED = "wrong_maximized"


class DriftItem(BaseModel):
    model_config = _FROZEN

    kind: DriftKind
    current: str
    desired: str


class ResolutionStatus(StrEnum):
    MATCHED = "matched"
    DRIFTED = "drifted"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    OPTIONAL_MISSING = "optional_missing"


class AppResolution(BaseModel):
    model_config = _FROZEN

    app_name: str
    workspace_name: str
    status: ResolutionStatus
    window_id: int | None = None
    is_ambiguous: bool = False
    drift: list[DriftItem]
    spec: AppSpec
    startup_timeout_s: float

    @property
    def needs_move(self) -> bool:
        return any(d.kind == DriftKind.WRONG_WORKSPACE for d in self.drift)


class WorkspaceState(BaseModel):
    model_config = _FROZEN

    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    focus: bool


class Resolution(BaseModel):
    model_config = _FROZEN

    session_name: str
    workspaces: list[WorkspaceState]
    apps: list[AppResolution]
    warnings: list[str] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        if any(not ws.exists or not ws.output_correct for ws in self.workspaces):
            return True
        return any(ar.status in (ResolutionStatus.DRIFTED, ResolutionStatus.MISSING) for ar in self.apps)

    @property
    def fully_converged(self) -> bool:
        return not self.has_drift and not any(ar.status == ResolutionStatus.AMBIGUOUS for ar in self.apps)

    def apps_in(self, workspace_name: str) -> list[AppResolution]:
        return [ar for ar in self.apps if ar.workspace_name == workspace_name]


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


class _Assignment(NamedTuple):
    window_id: int | None
    is_ambiguous: bool


class StatePropMapping(NamedTuple):
    """Canonical mapping between drift kinds and window/placement properties."""

    drift_kind: DriftKind
    window_attr: str
    placement_attr: str


STATE_PROPERTY_MAP: list[StatePropMapping] = [
    StatePropMapping(DriftKind.WRONG_FLOATING, "is_floating", "floating"),
    StatePropMapping(DriftKind.WRONG_FULLSCREEN, "is_fullscreen", "fullscreen"),
    StatePropMapping(DriftKind.WRONG_MAXIMIZED, "is_maximized", "maximized"),
]


def evaluate_rule(rule: MatchRule, window: Window) -> tuple[bool, MatchTier]:
    """Evaluate a match rule against a window."""
    best_tier = MatchTier.NONE
    failed = False

    if rule.app_id is not None:
        if window.app_id == rule.app_id:
            best_tier = max(best_tier, MatchTier.EXACT)
        else:
            failed = True

    if rule.app_id_regex is not None:
        if window.app_id and _compile(rule.app_id_regex).search(window.app_id):
            best_tier = max(best_tier, MatchTier.STRONG)
        else:
            failed = True

    if rule.title is not None:
        if window.title == rule.title:
            best_tier = max(best_tier, MatchTier.MODERATE)
        else:
            failed = True

    if rule.title_regex is not None:
        if window.title and _compile(rule.title_regex).search(window.title):
            best_tier = max(best_tier, MatchTier.WEAK)
        else:
            failed = True

    if rule.pid is not None:
        if getattr(window, "pid", None) == rule.pid:
            best_tier = max(best_tier, MatchTier.EXACT)
        else:
            failed = True

    if rule.any_of:
        any_results = [evaluate_rule(sub, window) for sub in rule.any_of]
        any_match = [r for r in any_results if r[0]]
        if any_match:
            best_tier = max(best_tier, max(r[1] for r in any_match))
        else:
            failed = True

    if rule.not_rule:
        not_match, _ = evaluate_rule(rule.not_rule, window)
        if not_match:
            failed = True

    if failed:
        return False, MatchTier.NONE
    if best_tier == MatchTier.NONE:
        # Composite-only rules (for example, only `not`) can match without
        # raising a positive tier. Treat as weak rather than "no match quality".
        best_tier = MatchTier.WEAK
    return True, best_tier


def _assign(apps: list[tuple[str, AppSpec]], windows: Iterable[Window]) -> list[_Assignment]:
    """Return assignment data per app index."""
    window_list = list(windows)
    all_candidates: list[list[tuple[int, MatchTier]]] = []
    for _ws_name, app_spec in apps:
        candidates: list[tuple[int, MatchTier]] = []
        for w in window_list:
            matched, tier = evaluate_rule(app_spec.match, w)
            if matched:
                candidates.append((w.id, tier))
        all_candidates.append(candidates)

    triples: list[tuple[int, int, MatchTier]] = []
    for app_idx, app_candidates in enumerate(all_candidates):
        for window_id, tier in app_candidates:
            triples.append((app_idx, window_id, tier))
    triples.sort(key=lambda triple: triple[2], reverse=True)

    assigned_app: set[int] = set()
    assigned_window: set[int] = set()
    assigned: dict[int, int] = {}

    for app_idx, window_id, _tier in triples:
        if app_idx in assigned_app or window_id in assigned_window:
            continue
        assigned[app_idx] = window_id
        assigned_app.add(app_idx)
        assigned_window.add(window_id)

    out: list[_Assignment] = []
    for idx, candidates in enumerate(all_candidates):
        wid = assigned.get(idx)
        is_ambiguous = False
        if len(candidates) >= 2:
            tiers = [tier for _wid, tier in candidates]
            top = max(tiers)
            is_ambiguous = sum(1 for tier in tiers if tier == top) > 1
        out.append(_Assignment(window_id=wid, is_ambiguous=is_ambiguous))
    return out


def resolve(spec: SessionSpec, snapshot: Snapshot) -> Resolution:
    """Resolve a session spec against a live snapshot."""
    ws_by_name: dict[str, WorkspaceLike] = {
        ws.name: ws for ws in snapshot.workspaces.values() if ws.name is not None
    }
    default_timeout = spec.options.default_startup_timeout_s

    all_apps: list[tuple[str, AppSpec]] = []
    for ws in spec.workspaces:
        for app_spec in ws.apps:
            all_apps.append((ws.name, app_spec))

    assignments = _assign(all_apps, snapshot.windows.values())

    workspaces: list[WorkspaceState] = []
    for ws in spec.workspaces:
        live_ws = ws_by_name.get(ws.name)
        exists = live_ws is not None
        output_correct = exists and (ws.output is None or live_ws.output == ws.output)
        workspaces.append(
            WorkspaceState(
                name=ws.name,
                focus=ws.focus,
                exists=exists,
                output_correct=output_correct,
                desired_output=ws.output,
                current_output=live_ws.output if live_ws else None,
            )
        )

    apps: list[AppResolution] = []
    for idx, (ws_name, app_spec) in enumerate(all_apps):
        assignment = assignments[idx]
        window_id, is_ambiguous = assignment.window_id, assignment.is_ambiguous
        timeout = app_spec.startup_timeout_s or default_timeout

        if window_id is not None:
            window = snapshot.windows[window_id]
            drift = _detect_drift(window, app_spec, ws_name, ws_by_name)
            status = ResolutionStatus.DRIFTED if drift else ResolutionStatus.MATCHED
        else:
            drift = []
            if app_spec.optional:
                status = ResolutionStatus.OPTIONAL_MISSING
            else:
                status = ResolutionStatus.MISSING

        if is_ambiguous:
            status = ResolutionStatus.AMBIGUOUS

        apps.append(
            AppResolution(
                app_name=app_spec.name,
                workspace_name=ws_name,
                status=status,
                window_id=window_id,
                is_ambiguous=is_ambiguous,
                drift=drift,
                spec=app_spec,
                startup_timeout_s=timeout,
            )
        )

    return Resolution(session_name=spec.name, workspaces=workspaces, apps=apps, warnings=[])


def _detect_drift(
    window: Window,
    app_spec: AppSpec,
    ws_name: str,
    ws_by_name: dict[str, WorkspaceLike],
) -> list[DriftItem]:
    drift: list[DriftItem] = []

    target_ws = ws_by_name.get(ws_name)
    if target_ws is None or window.workspace_id != target_ws.id:
        drift.append(
            DriftItem(
                kind=DriftKind.WRONG_WORKSPACE,
                current=str(window.workspace_id),
                desired=ws_name,
            )
        )

    for prop in STATE_PROPERTY_MAP:
        current_val: Any = getattr(window, prop.window_attr, False)
        desired_val: Any = getattr(app_spec.placement, prop.placement_attr)
        if current_val != desired_val:
            drift.append(DriftItem(kind=prop.drift_kind, current=str(current_val), desired=str(desired_val)))

    return drift
