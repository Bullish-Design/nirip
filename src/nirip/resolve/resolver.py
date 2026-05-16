"""Session resolution against live compositor state."""

from __future__ import annotations

from niri_state import Snapshot

from nirip.resolve.matcher import assign_windows
from nirip.resolve.models import (
    AppResolution,
    DriftItem,
    DriftKind,
    NormalizedSession,
    Resolution,
    ResolutionStatus,
    WorkspaceResolution,
)


def resolve(normalized: NormalizedSession, snapshot: Snapshot) -> Resolution:
    """Resolve a normalized session against a live snapshot."""
    ws_by_name = {ws.name: ws for ws in snapshot.workspaces.values() if ws.name is not None}

    decisions = assign_windows(normalized.apps, snapshot.windows.values())
    decision_index = {(d.workspace_name, d.app_name): d for d in decisions}

    workspace_resolutions: list[WorkspaceResolution] = []
    unmatched: list[AppResolution] = []
    ambiguous: list[AppResolution] = []

    for nws in normalized.workspaces:
        live_ws = ws_by_name.get(nws.name)
        exists = live_ws is not None
        output_correct = exists and (nws.output is None or live_ws.output == nws.output)

        app_resolutions: list[AppResolution] = []
        for app_name in nws.app_names:
            napp = normalized.app_index[f"{nws.name}/{app_name}"]
            decision = decision_index[(nws.name, app_name)]

            if decision.assigned_window_id is not None:
                window = snapshot.windows[decision.assigned_window_id]
                drift = _detect_drift(window, napp, nws.name, ws_by_name)
                status = ResolutionStatus.DRIFTED if drift else ResolutionStatus.MATCHED
                action_required = bool(drift)
            else:
                drift = []
                if napp.optional:
                    status = ResolutionStatus.OPTIONAL_MISSING
                    action_required = False
                else:
                    status = ResolutionStatus.MISSING
                    action_required = normalized.options.launch_missing

            if decision.is_ambiguous:
                status = ResolutionStatus.AMBIGUOUS

            ar = AppResolution(
                app_name=app_name,
                workspace_name=nws.name,
                status=status,
                match_decision=decision,
                drift=drift,
                action_required=action_required,
            )
            app_resolutions.append(ar)

            if status == ResolutionStatus.MISSING:
                unmatched.append(ar)
            if status == ResolutionStatus.AMBIGUOUS:
                ambiguous.append(ar)

        workspace_resolutions.append(
            WorkspaceResolution(
                name=nws.name,
                exists=exists,
                output_correct=output_correct,
                desired_output=nws.output,
                current_output=live_ws.output if live_ws else None,
                app_resolutions=app_resolutions,
            )
        )

    return Resolution(
        session_name=normalized.name,
        workspace_resolutions=workspace_resolutions,
        unmatched_apps=unmatched,
        ambiguous_apps=ambiguous,
        warnings=[],
    )


def _detect_drift(window: object, napp: object, ws_name: str, ws_by_name: dict[str, object]) -> list[DriftItem]:
    drift: list[DriftItem] = []

    target_ws = ws_by_name.get(ws_name)
    window_ws_id = getattr(window, "workspace_id", None)
    if target_ws is None:
        drift.append(DriftItem(kind=DriftKind.WRONG_WORKSPACE, current=str(window_ws_id), desired=ws_name))
    elif window_ws_id != getattr(target_ws, "id", None):
        drift.append(DriftItem(kind=DriftKind.WRONG_WORKSPACE, current=str(window_ws_id), desired=ws_name))

    if getattr(window, "is_floating", False) != napp.placement.floating:
        drift.append(
            DriftItem(
                kind=DriftKind.WRONG_FLOATING,
                current=str(getattr(window, "is_floating", False)),
                desired=str(napp.placement.floating),
            )
        )

    if getattr(window, "is_fullscreen", False) != napp.placement.fullscreen:
        drift.append(
            DriftItem(
                kind=DriftKind.WRONG_FULLSCREEN,
                current=str(getattr(window, "is_fullscreen", False)),
                desired=str(napp.placement.fullscreen),
            )
        )

    if hasattr(window, "is_maximized"):
        if window.is_maximized != napp.placement.maximized:
            drift.append(
                DriftItem(
                    kind=DriftKind.WRONG_MAXIMIZED,
                    current=str(window.is_maximized),
                    desired=str(napp.placement.maximized),
                )
            )

    return drift
