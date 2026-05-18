"""Capture current compositor state as a session spec template."""

from __future__ import annotations

from niri_state import Snapshot
from niri_state.api.selectors import windows, workspaces

from nirip.spec import AppSpec, MatchRule, SessionSpec, WorkspaceSpec


def capture(snapshot: Snapshot, *, name: str | None = None) -> SessionSpec:
    """Export live state as a session spec template."""
    workspace_specs: list[WorkspaceSpec] = []
    for ws in workspaces.list_workspaces(snapshot):
        if ws.name is None:
            continue
        apps: list[AppSpec] = []
        for w in windows.list_windows_on_workspace(snapshot, ws.id):
            apps.append(AppSpec(name=_infer_name(w), match=_infer_match(w)))
        workspace_specs.append(WorkspaceSpec(name=ws.name, output=ws.output, apps=apps))
    return SessionSpec(name=name or "captured", workspaces=workspace_specs)


def _infer_name(window) -> str:
    if window.app_id:
        return window.app_id.rsplit(".", 1)[-1].lower().replace(" ", "-")
    if window.title:
        return window.title.lower().replace(" ", "-")[:30]
    return f"app-{window.id}"


def _infer_match(window) -> MatchRule:
    if window.app_id:
        return MatchRule(app_id=window.app_id)
    if window.title:
        return MatchRule(title=window.title)
    return MatchRule(title=f"window-{window.id}")
