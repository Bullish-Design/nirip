"""Skip-check predicates for plan steps."""

from __future__ import annotations

from niri_state import Snapshot

from nirip.planning.models import (
    EnsureWorkspaceStep,
    MoveWindowToWorkspaceStep,
    PlanStep,
    SetWindowStateStep,
    WindowProperty,
)

_STATE_CHECKS = {
    WindowProperty.FLOATING: lambda w: w.is_floating,
    WindowProperty.TILING: lambda w: not w.is_floating,
    WindowProperty.FULLSCREEN: lambda w: getattr(w, "is_fullscreen", False),
    WindowProperty.MAXIMIZED: lambda w: getattr(w, "is_maximized", False),
}


def is_already_satisfied(step: PlanStep, snapshot: Snapshot) -> bool:
    match step:
        case EnsureWorkspaceStep():
            return any(ws.name == step.workspace_name for ws in snapshot.workspaces.values())
        case MoveWindowToWorkspaceStep():
            if step.window_id is None:
                return False
            w = snapshot.windows.get(step.window_id)
            if w is None:
                return False
            target = next((ws for ws in snapshot.workspaces.values() if ws.name == step.target_workspace), None)
            return target is not None and w.workspace_id == target.id
        case SetWindowStateStep():
            if step.window_id is None:
                return False
            w = snapshot.windows.get(step.window_id)
            if w is None:
                return False
            return _STATE_CHECKS[step.property](w) == step.value
        case _:
            return False
