"""Step verification predicates."""
from __future__ import annotations

from typing import Protocol

from nirip.planning.models import PlanStep, StepKind


class SnapshotLike(Protocol):
    windows: dict[int, object]
    workspaces: dict[int, object]


def predicate_for_step(step: PlanStep):
    """Return a predicate that checks if a step has completed."""

    if step.kind == StepKind.WAIT_FOR_WINDOW:
        return lambda snapshot: bool(snapshot.windows)
    return lambda _snapshot: True
