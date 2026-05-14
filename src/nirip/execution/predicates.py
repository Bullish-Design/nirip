"""Step verification predicates."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from nirip.planning.models import PlanStep, StepKind


class SnapshotLike(Protocol):
    windows: dict[int, Any]
    workspaces: dict[int, Any]


StepPredicate = Callable[[SnapshotLike], bool]


def predicate_for_step(step: PlanStep) -> StepPredicate | None:
    """Return a predicate that checks if a step's outcome is already satisfied."""

    if step.kind == StepKind.WAIT_FOR_WINDOW:
        return None

    if step.kind == StepKind.ENSURE_WORKSPACE:
        ws_name = step.workspace_name

        def _ws_exists(snapshot: SnapshotLike) -> bool:
            return any(getattr(ws, "name", None) == ws_name for ws in snapshot.workspaces.values())

        return _ws_exists

    if step.kind == StepKind.MOVE_WINDOW_TO_WORKSPACE:
        window_id = step.window_id
        ws_name = step.workspace_name

        def _window_in_ws(snapshot: SnapshotLike) -> bool:
            if window_id is None or ws_name is None:
                return False
            window = snapshot.windows.get(window_id)
            if window is None:
                return False
            target_ws = None
            for ws in snapshot.workspaces.values():
                if getattr(ws, "name", None) == ws_name:
                    target_ws = ws
                    break
            if target_ws is None:
                return False
            return getattr(window, "workspace_id", None) == getattr(target_ws, "id", None)

        return _window_in_ws

    if step.kind in (StepKind.SET_FLOATING, StepKind.SET_TILING):
        window_id = step.window_id
        want_floating = step.kind == StepKind.SET_FLOATING

        def _float_matches(snapshot: SnapshotLike) -> bool:
            if window_id is None:
                return False
            window = snapshot.windows.get(window_id)
            if window is None:
                return False
            return getattr(window, "is_floating", None) == want_floating

        return _float_matches

    return None
