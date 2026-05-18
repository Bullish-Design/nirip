"""Window assignment strategies."""

from __future__ import annotations

from nirip.resolve.models import MatchCandidate, MatchTier
from nirip.spec.models import AppSpec


class GreedyAssigner:
    """Greedy assignment: highest-tier-first, first-come-first-served."""

    def assign(
        self,
        apps: list[tuple[str, AppSpec]],
        candidates: list[list[MatchCandidate]],
    ) -> dict[int, int]:
        del apps  # candidates are already aligned by app index

        triples: list[tuple[int, int, MatchTier]] = []
        for app_idx, app_candidates in enumerate(candidates):
            for candidate in app_candidates:
                triples.append((app_idx, candidate.window_id, candidate.tier))
        triples.sort(key=lambda triple: triple[2], reverse=True)

        assigned_app: set[int] = set()
        assigned_window: set[int] = set()
        result: dict[int, int] = {}

        for app_idx, window_id, _tier in triples:
            if app_idx in assigned_app or window_id in assigned_window:
                continue
            result[app_idx] = window_id
            assigned_app.add(app_idx)
            assigned_window.add(window_id)

        return result
