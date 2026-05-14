"""Resolve desired session state against a live snapshot."""
from __future__ import annotations

from typing import Protocol

from nirip.resolve.matcher import WindowLike, match_app
from nirip.resolve.models import (
    AppResolution,
    DriftItem,
    DriftKind,
    NormalizedSession,
    Resolution,
    ResolutionStatus,
    WorkspaceResolution,
)


class WorkspaceLike(Protocol):
    id: int
    name: str | None
    output: str | None


class SnapshotLike(Protocol):
    windows: dict[int, WindowLike]
    workspaces: dict[int, WorkspaceLike]


def _workspace_by_name(snapshot: SnapshotLike, name: str) -> WorkspaceLike | None:
    for workspace in snapshot.workspaces.values():
        if workspace.name == name:
            return workspace
    return None


def resolve(normalized: NormalizedSession, snapshot: SnapshotLike) -> Resolution:
    """Resolve normalized session against current snapshot."""

    all_windows = list(snapshot.windows.values())
    workspace_resolutions: list[WorkspaceResolution] = []
    unmatched: list[AppResolution] = []
    ambiguous: list[AppResolution] = []
    warnings: list[str] = []

    for ws in normalized.workspaces:
        live_ws = _workspace_by_name(snapshot, ws.name)
        exists = live_ws is not None
        current_output = live_ws.output if live_ws else None
        output_correct = ws.output is None or ws.output == current_output

        app_resolutions: list[AppResolution] = []
        for app_name in ws.app_names:
            app = normalized.app_index[f"{ws.name}/{app_name}"]
            decision = match_app(app.name, ws.name, app.match, all_windows)
            drift: list[DriftItem] = []

            status = ResolutionStatus.MATCHED
            action_required = False

            if decision.is_ambiguous:
                status = ResolutionStatus.AMBIGUOUS
                action_required = True
            elif not decision.is_matched:
                if app.optional:
                    status = ResolutionStatus.OPTIONAL_MISSING
                else:
                    status = ResolutionStatus.MISSING
                    action_required = True
            else:
                window = snapshot.windows.get(decision.best)
                if window is not None and live_ws is not None and window.workspace_id != live_ws.id:
                    drift.append(
                        DriftItem(
                            kind=DriftKind.WRONG_WORKSPACE,
                            current=str(window.workspace_id),
                            desired=str(live_ws.id),
                        )
                    )
                if window is not None and window.is_floating != app.placement.floating:
                    drift.append(
                        DriftItem(
                            kind=DriftKind.WRONG_FLOATING,
                            current=str(window.is_floating),
                            desired=str(app.placement.floating),
                        )
                    )

                if drift:
                    status = ResolutionStatus.DRIFTED
                    action_required = True

            app_resolution = AppResolution(
                app_name=app.name,
                workspace_name=ws.name,
                status=status,
                match_decision=decision,
                drift=drift,
                action_required=action_required,
            )
            app_resolutions.append(app_resolution)
            if status == ResolutionStatus.MISSING:
                unmatched.append(app_resolution)
            if status == ResolutionStatus.AMBIGUOUS:
                ambiguous.append(app_resolution)

        if not output_correct:
            warnings.append(
                f"Workspace '{ws.name}' on output '{current_output}', desired '{ws.output}'"
            )

        workspace_resolutions.append(
            WorkspaceResolution(
                name=ws.name,
                exists=exists,
                output_correct=output_correct,
                desired_output=ws.output,
                current_output=current_output,
                app_resolutions=app_resolutions,
            )
        )

    return Resolution(
        session_name=normalized.name,
        workspace_resolutions=workspace_resolutions,
        unmatched_apps=unmatched,
        ambiguous_apps=ambiguous,
        warnings=warnings,
    )
