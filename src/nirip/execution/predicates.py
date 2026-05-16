"""Skip-check predicates for plan steps."""

from __future__ import annotations

from niri_state import Snapshot

from nirip.planning.models import (
    EnsureWorkspaceStep,
    MoveWindowToWorkspaceStep,
    PlanStep,
    SetFloatingStep,
    SetFullscreenStep,
    SetMaximizedStep,
    SetTilingStep,
)


def is_already_satisfied(step: PlanStep, snapshot: Snapshot) -> bool:
    match step:
        case EnsureWorkspaceStep():
            return any(ws.name == step.workspace_name for ws in snapshot.workspaces.values())
        case MoveWindowToWorkspaceStep():
            w = snapshot.windows.get(step.window_id)
            if w is None:
                return False
            target = next((ws for ws in snapshot.workspaces.values() if ws.name == step.target_workspace), None)
            return target is not None and w.workspace_id == target.id
        case SetFloatingStep():
            w = snapshot.windows.get(step.window_id)
            return w is not None and w.is_floating
        case SetTilingStep():
            w = snapshot.windows.get(step.window_id)
            return w is not None and not w.is_floating
        case SetFullscreenStep():
            w = snapshot.windows.get(step.window_id)
            return w is not None and w.is_fullscreen == step.fullscreen
        case SetMaximizedStep():
            w = snapshot.windows.get(step.window_id)
            return w is not None and getattr(w, "is_maximized", False) == step.maximized
        case _:
            return False
