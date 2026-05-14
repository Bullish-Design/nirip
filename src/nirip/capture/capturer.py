"""Capture live desktop into a scaffold SessionSpec."""
from __future__ import annotations

from pydantic import BaseModel, computed_field

from nirip.capture.inference import infer_app_name, infer_match_rule
from nirip.spec.models import AppSpec, SessionSpec, WorkspaceSpec


class CapturedSession(BaseModel):
    """Result of a capture operation."""

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


def capture_from_snapshot(snapshot: object, *, name: str | None = None) -> CapturedSession:
    """Capture current snapshot into a scaffold spec."""

    workspaces = getattr(snapshot, "workspaces", {})
    windows = getattr(snapshot, "windows", {})

    apps_by_ws: dict[int, list[AppSpec]] = {wid: [] for wid in workspaces.keys()}
    for window in windows.values():
        ws_id = getattr(window, "workspace_id", None)
        if ws_id in apps_by_ws:
            apps_by_ws[ws_id].append(
                AppSpec(
                    name=infer_app_name(window),
                    match=infer_match_rule(window),
                )
            )

    ws_specs: list[WorkspaceSpec] = []
    for ws_id, workspace in workspaces.items():
        ws_name = getattr(workspace, "name", None)
        if ws_name is None:
            continue
        ws_specs.append(
            WorkspaceSpec(
                name=ws_name,
                output=getattr(workspace, "output", None),
                apps=apps_by_ws.get(ws_id, []),
            )
        )

    spec = SessionSpec(name=name or "captured", workspaces=ws_specs)
    notes = ["Captured scaffold uses conservative app_id matching; add spawn commands manually."]
    return CapturedSession(spec=spec, notes=notes)
