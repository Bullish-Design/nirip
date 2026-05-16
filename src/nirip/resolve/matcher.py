"""Window matching: rule evaluation and global assignment."""

from __future__ import annotations

import re
from collections.abc import Iterable

from niri_pypc.types.generated.models import Window

from nirip.resolve.models import MatchCandidate, MatchDecision, NormalizedApp
from nirip.spec.models import MatchRule


def evaluate_rule(rule: MatchRule, window: Window) -> tuple[bool, float, list[str]]:
    """Evaluate a match rule against a window. Returns (matched, confidence, reasons)."""
    scores: list[float] = []
    reasons: list[str] = []
    failed = False

    if rule.app_id is not None:
        if window.app_id == rule.app_id:
            scores.append(1.0)
            reasons.append(f"app_id exact match: {rule.app_id}")
        else:
            failed = True
            reasons.append(f"app_id mismatch: wanted {rule.app_id}, got {window.app_id}")

    if rule.app_id_regex is not None:
        if window.app_id and re.search(rule.app_id_regex, window.app_id):
            scores.append(0.9)
            reasons.append(f"app_id_regex match: {rule.app_id_regex}")
        else:
            failed = True
            reasons.append(f"app_id_regex no match: {rule.app_id_regex}")

    if rule.title is not None:
        if window.title == rule.title:
            scores.append(0.8)
            reasons.append(f"title exact match: {rule.title}")
        else:
            failed = True
            reasons.append(f"title mismatch: wanted {rule.title}, got {window.title}")

    if rule.title_regex is not None:
        if window.title and re.search(rule.title_regex, window.title):
            scores.append(0.7)
            reasons.append(f"title_regex match: {rule.title_regex}")
        else:
            failed = True
            reasons.append(f"title_regex no match: {rule.title_regex}")

    if rule.pid is not None:
        if getattr(window, "pid", None) == rule.pid:
            scores.append(1.0)
            reasons.append(f"pid exact match: {rule.pid}")
        else:
            failed = True
            reasons.append(f"pid mismatch: wanted {rule.pid}, got {getattr(window, 'pid', None)}")

    if rule.any_of:
        any_results = [evaluate_rule(sub, window) for sub in rule.any_of]
        any_match = [r for r in any_results if r[0]]
        if any_match:
            scores.append(max(r[1] for r in any_match))
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
        return False, 0.0, reasons
    if not scores:
        return False, 0.0, reasons

    confidence = min(scores) if len(scores) > 1 else scores[0]
    return True, confidence, reasons


def assign_windows(apps: list[NormalizedApp], windows: Iterable[Window]) -> list[MatchDecision]:
    """Globally consistent 1:1 app-to-window assignment."""
    window_list = list(windows)

    all_candidates: list[list[MatchCandidate]] = []
    for app in apps:
        candidates = []
        for w in window_list:
            matched, conf, reasons = evaluate_rule(app.match, w)
            if matched:
                candidates.append(MatchCandidate(window_id=w.id, confidence=conf, reasons=reasons))
        all_candidates.append(candidates)

    triples: list[tuple[int, int, float]] = []
    for app_idx, candidates in enumerate(all_candidates):
        for c in candidates:
            triples.append((app_idx, c.window_id, c.confidence))
    triples.sort(key=lambda t: t[2], reverse=True)

    assigned_app: set[int] = set()
    assigned_window: set[int] = set()
    app_to_window: dict[int, int] = {}

    for app_idx, window_id, _confidence in triples:
        if app_idx in assigned_app or window_id in assigned_window:
            continue
        app_to_window[app_idx] = window_id
        assigned_app.add(app_idx)
        assigned_window.add(window_id)

    decisions: list[MatchDecision] = []
    for app_idx, app in enumerate(apps):
        candidates = all_candidates[app_idx]
        wid = app_to_window.get(app_idx)
        conf = 0.0
        rationale: list[str] = []

        if wid is not None:
            conf = next(c.confidence for c in candidates if c.window_id == wid)
            rationale.append(f"assigned window {wid} (confidence {conf:.2f})")
        elif candidates:
            rationale.append(f"{len(candidates)} candidate(s) all claimed by higher-confidence matches")
        else:
            rationale.append("no matching windows found")

        decisions.append(
            MatchDecision(
                app_name=app.name,
                workspace_name=app.workspace_name,
                assigned_window_id=wid,
                candidates=candidates,
                confidence=conf,
                rationale=rationale,
            )
        )

    return decisions
