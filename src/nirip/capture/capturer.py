"""Capture current state as a session scaffold."""

from __future__ import annotations

from pydantic import computed_field

from niri_state import Snapshot
from niri_state.api.selectors import windows, workspaces

from nirip._base import NiripModel
from nirip.capture.inference import infer_app_name, infer_match_rule
from nirip.spec.models import AppSpec, SessionSpec, WorkspaceSpec


class CapturedSession(NiripModel):
    spec: SessionSpec
    notes: list[str]

    @computed_field
    @property
    def app_count(self) -> int:
        return sum(len(ws.apps) for ws in self.spec.workspaces)

    @computed_field
    @property
    def workspace_count(self) -> int:
        return len(self.spec.workspaces)


def capture_from_snapshot(snapshot: Snapshot, *, name: str | None = None) -> CapturedSession:
    workspace_specs = []
    notes = []

    for ws in workspaces.list_workspaces(snapshot):
        if ws.name is None:
            notes.append(f"skipped unnamed workspace (id={ws.id})")
            continue
        apps = []
        for w in windows.list_windows_on_workspace(snapshot, ws.id):
            apps.append(AppSpec(name=infer_app_name(w), match=infer_match_rule(w)))
        workspace_specs.append(WorkspaceSpec(name=ws.name, output=ws.output, apps=apps))

    notes.append("Add spawn commands for apps you want auto-launched")
    notes.append("Refine match rules for more reliable matching")

    return CapturedSession(spec=SessionSpec(name=name or "captured", workspaces=workspace_specs), notes=notes)
