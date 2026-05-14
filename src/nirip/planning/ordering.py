"""Plan step ordering helpers."""
from __future__ import annotations

from collections import defaultdict, deque

from nirip.planning.models import PlanStep


def topological_sort(steps: list[PlanStep]) -> list[PlanStep]:
    """Sort steps according to step dependency IDs."""

    id_map = {step.id: step for step in steps}
    indegree = {step.id: 0 for step in steps}
    edges: dict[str, list[str]] = defaultdict(list)

    for step in steps:
        for dep in step.depends_on:
            if dep not in id_map:
                continue
            edges[dep].append(step.id)
            indegree[step.id] += 1

    queue: deque[str] = deque(sorted([sid for sid, degree in indegree.items() if degree == 0]))
    ordered: list[PlanStep] = []

    while queue:
        sid = queue.popleft()
        ordered.append(id_map[sid])
        for nxt in sorted(edges[sid]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(steps):
        return steps
    return ordered
