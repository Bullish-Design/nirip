"""Match rule evaluation against live windows."""
from __future__ import annotations

import re
from typing import Protocol

from nirip.resolve.models import MatchCandidate, MatchDecision
from nirip.spec.models import MatchRule


class WindowLike(Protocol):
    """Structural window type."""

    @property
    def id(self) -> int: ...

    @property
    def app_id(self) -> str | None: ...

    @property
    def title(self) -> str | None: ...

    @property
    def pid(self) -> int | None: ...

    @property
    def workspace_id(self) -> int | None: ...

    @property
    def is_floating(self) -> bool: ...

    @property
    def is_fullscreen(self) -> bool: ...

    @property
    def is_maximized(self) -> bool: ...


def evaluate_rule(rule: MatchRule, window: WindowLike) -> tuple[bool, float, list[str]]:
    """Evaluate a MatchRule against a single window."""

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
        if window.pid == rule.pid:
            scores.append(1.0)
            reasons.append(f"pid exact match: {rule.pid}")
        else:
            failed = True
            reasons.append(f"pid mismatch: wanted {rule.pid}, got {window.pid}")

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


def match_app(app_name: str, workspace_name: str, rule: MatchRule, windows: list[WindowLike]) -> MatchDecision:
    """Match an app's rule against all candidate windows."""

    candidates: list[MatchCandidate] = []
    matched: list[MatchCandidate] = []

    for window in windows:
        is_match, confidence, reasons = evaluate_rule(rule, window)
        candidate = MatchCandidate(window_id=window.id, confidence=confidence, reasons=reasons)
        candidates.append(candidate)
        if is_match:
            matched.append(candidate)

    matched.sort(key=lambda c: (-c.confidence, c.window_id))
    if not matched:
        return MatchDecision(
            app_name=app_name,
            workspace_name=workspace_name,
            best=None,
            candidates=candidates,
            confidence=0.0,
            rationale=["no matching candidates"],
        )

    best = matched[0]
    return MatchDecision(
        app_name=app_name,
        workspace_name=workspace_name,
        best=best.window_id,
        candidates=candidates,
        confidence=best.confidence,
        rationale=[f"selected window {best.window_id} with confidence {best.confidence:.2f}"],
    )
