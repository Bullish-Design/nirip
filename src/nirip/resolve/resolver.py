"""Session resolution against live compositor state."""

from __future__ import annotations

from typing import Any

from niri_pypc.types.generated.models import Window, Workspace
from niri_state import Snapshot

from nirip.resolve.matcher import assign_windows
from nirip.resolve.models import (
    AppResolution,
    DriftItem,
    DriftKind,
    Resolution,
    ResolutionStatus,
    WorkspaceResolution,
)
from nirip.spec.models import AppSpec, SessionSpec


def resolve(spec: SessionSpec, snapshot: Snapshot) -> Resolution:
    """Resolve a session spec against a live snapshot."""
    ws_by_name = {ws.name: ws for ws in snapshot.workspaces.values() if ws.name is not None}
    default_timeout = spec.options.default_startup_timeout_s

    all_apps: list[tuple[str, AppSpec]] = []
    for ws in spec.workspaces:
        for app_spec in ws.apps:
            all_apps.append((ws.name, app_spec))

    decisions = assign_windows(all_apps, snapshot.windows.values())
    decision_index = {(ws_name, app.name): d for (ws_name, app), d in zip(all_apps, decisions, strict=True)}

    workspace_resolutions: list[WorkspaceResolution] = []

    for ws in spec.workspaces:
        live_ws = ws_by_name.get(ws.name)
        exists = live_ws is not None
        output_correct = exists and (ws.output is None or live_ws.output == ws.output)

        app_resolutions: list[AppResolution] = []
        for app_spec in ws.apps:
            decision = decision_index[(ws.name, app_spec.name)]
            timeout = app_spec.startup_timeout_s or default_timeout

            if decision.assigned_window_id is not None:
                window = snapshot.windows[decision.assigned_window_id]
                drift = _detect_drift(window, app_spec, ws.name, ws_by_name)
                status = ResolutionStatus.DRIFTED if drift else ResolutionStatus.MATCHED
            else:
                drift = []
                if app_spec.optional:
                    status = ResolutionStatus.OPTIONAL_MISSING
                else:
                    status = ResolutionStatus.MISSING

            if decision.is_ambiguous:
                status = ResolutionStatus.AMBIGUOUS

            ar = AppResolution(
                app_name=app_spec.name,
                workspace_name=ws.name,
                status=status,
                match_decision=decision,
                drift=drift,
                spec=app_spec,
                startup_timeout_s=timeout,
            )
            app_resolutions.append(ar)

        workspace_resolutions.append(
            WorkspaceResolution(
                name=ws.name,
                focus=ws.focus,
                exists=exists,
                output_correct=output_correct,
                desired_output=ws.output,
                current_output=live_ws.output if live_ws else None,
                app_resolutions=app_resolutions,
            )
        )

    return Resolution(
        session_name=spec.name,
        workspace_resolutions=workspace_resolutions,
        warnings=[],
    )


_PROPERTY_CHECKS: list[tuple[DriftKind, str, str]] = [
    (DriftKind.WRONG_FLOATING, "is_floating", "floating"),
    (DriftKind.WRONG_FULLSCREEN, "is_fullscreen", "fullscreen"),
]


def _detect_drift(
    window: Window,
    app_spec: AppSpec,
    ws_name: str,
    ws_by_name: dict[str, Workspace],
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

    for kind, win_attr, place_attr in _PROPERTY_CHECKS:
        current_val: Any = getattr(window, win_attr, False)
        desired_val: Any = getattr(app_spec.placement, place_attr)
        if current_val != desired_val:
            drift.append(DriftItem(kind=kind, current=str(current_val), desired=str(desired_val)))

    if hasattr(window, "is_maximized"):
        if window.is_maximized != app_spec.placement.maximized:
            drift.append(
                DriftItem(
                    kind=DriftKind.WRONG_MAXIMIZED,
                    current=str(window.is_maximized),
                    desired=str(app_spec.placement.maximized),
                )
            )

    return drift
