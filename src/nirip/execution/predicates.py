"""Skip-check predicates for plan steps."""

from __future__ import annotations

from niri_state import Snapshot

from nirip.execution._checks import STATE_CHECKS
from nirip.planning.models import (
    CreateWorkspaceStep,
    MoveWindowToWorkspaceStep,
    PlanStep,
    SetWindowStateStep,
)


def is_already_satisfied(step: PlanStep, snapshot: Snapshot) -> bool:
    match step:
        case CreateWorkspaceStep():
            return any(ws.name == step.workspace_name for ws in snapshot.workspaces.values())
        case MoveWindowToWorkspaceStep():
            if step.window_id is None:
                return False
            w = snapshot.windows.get(step.window_id)
            if w is None:
                return False
            target = next((ws for ws in snapshot.workspaces.values() if ws.name == step.workspace_name), None)
            return target is not None and w.workspace_id == target.id
        case SetWindowStateStep():
            if step.window_id is None:
                return False
            w = snapshot.windows.get(step.window_id)
            if w is None:
                return False
            return STATE_CHECKS[step.property](w) == step.value
        case _:
            return False
