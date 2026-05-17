"""Window matching: rule evaluation and global assignment."""

from __future__ import annotations

import re
from collections.abc import Iterable

from niri_pypc.types.generated.models import Window

from nirip.resolve.models import MatchCandidate, MatchDecision, MatchTier
from nirip.spec.models import AppSpec, MatchRule


def evaluate_rule(rule: MatchRule, window: Window) -> tuple[bool, MatchTier, list[str]]:
    """Evaluate a match rule against a window."""
    best_tier = MatchTier.NONE
    reasons: list[str] = []
    failed = False

    if rule.app_id is not None:
        if window.app_id == rule.app_id:
            best_tier = max(best_tier, MatchTier.EXACT)
            reasons.append(f"app_id exact: {rule.app_id}")
        else:
            failed = True
            reasons.append(f"app_id mismatch: wanted {rule.app_id}, got {window.app_id}")

    if rule.app_id_regex is not None:
        if window.app_id and re.search(rule.app_id_regex, window.app_id):
            best_tier = max(best_tier, MatchTier.STRONG)
            reasons.append(f"app_id_regex: {rule.app_id_regex}")
        else:
            failed = True
            reasons.append(f"app_id_regex no match: {rule.app_id_regex}")

    if rule.title is not None:
        if window.title == rule.title:
            best_tier = max(best_tier, MatchTier.MODERATE)
            reasons.append(f"title exact: {rule.title}")
        else:
            failed = True
            reasons.append(f"title mismatch: wanted {rule.title}, got {window.title}")

    if rule.title_regex is not None:
        if window.title and re.search(rule.title_regex, window.title):
            best_tier = max(best_tier, MatchTier.WEAK)
            reasons.append(f"title_regex: {rule.title_regex}")
        else:
            failed = True
            reasons.append(f"title_regex no match: {rule.title_regex}")

    if rule.pid is not None:
        if getattr(window, "pid", None) == rule.pid:
            best_tier = max(best_tier, MatchTier.EXACT)
            reasons.append(f"pid: {rule.pid}")
        else:
            failed = True
            reasons.append(f"pid mismatch: wanted {rule.pid}, got {getattr(window, 'pid', None)}")

    if rule.any_of:
        any_results = [evaluate_rule(sub, window) for sub in rule.any_of]
        any_match = [r for r in any_results if r[0]]
        if any_match:
            best_tier = max(best_tier, max(r[1] for r in any_match))
            reasons.append("any_of matched")
        else:
            failed = True
            reasons.append("any_of had no matches")

    if rule.not_rule:
        not_match, _, _ = evaluate_rule(rule.not_rule, window)
        if not_match:
            failed = True
            reasons.append("not_rule matched; expected no match")
        else:
            reasons.append("not_rule satisfied")

    if failed:
        return False, MatchTier.NONE, reasons
    if best_tier == MatchTier.NONE:
        best_tier = MatchTier.WEAK
    return True, best_tier, reasons


def assign_windows(apps: list[tuple[str, AppSpec]], windows: Iterable[Window]) -> list[MatchDecision]:
    """Globally consistent 1:1 app-to-window assignment."""
    window_list = list(windows)

    all_candidates: list[list[MatchCandidate]] = []
    for _ws_name, app_spec in apps:
        candidates = []
        for w in window_list:
            matched, tier, reasons = evaluate_rule(app_spec.match, w)
            if matched:
                candidates.append(MatchCandidate(window_id=w.id, tier=tier, reasons=reasons))
        all_candidates.append(candidates)

    triples: list[tuple[int, int, MatchTier]] = []
    for app_idx, candidates in enumerate(all_candidates):
        for c in candidates:
            triples.append((app_idx, c.window_id, MatchTier(c.tier)))
    triples.sort(key=lambda t: t[2], reverse=True)

    assigned_app: set[int] = set()
    assigned_window: set[int] = set()
    app_to_window: dict[int, int] = {}

    for app_idx, window_id, _tier in triples:
        if app_idx in assigned_app or window_id in assigned_window:
            continue
        app_to_window[app_idx] = window_id
        assigned_app.add(app_idx)
        assigned_window.add(window_id)

    decisions: list[MatchDecision] = []
    for app_idx, (ws_name, app_spec) in enumerate(apps):
        candidates = all_candidates[app_idx]
        wid = app_to_window.get(app_idx)
        tier = MatchTier.NONE
        reasons: list[str] = []

        if wid is not None:
            tier = next(MatchTier(c.tier) for c in candidates if c.window_id == wid)
            reasons.append(f"assigned window {wid} (tier {tier.name})")
        elif candidates:
            reasons.append(f"{len(candidates)} candidate(s) all claimed by higher-tier matches")
        else:
            reasons.append("no matching windows found")

        decisions.append(
            MatchDecision(
                app_name=app_spec.name,
                workspace_name=ws_name,
                assigned_window_id=wid,
                candidates=candidates,
                tier=tier,
                reasons=reasons,
            )
        )

    return decisions
