"""Infer match rules and app names from live windows."""

from __future__ import annotations

from niri_pypc.types.generated.models import Window

from nirip.spec.models import MatchRule


def infer_app_name(window: Window, fallback_prefix: str = "app") -> str:
    if window.app_id:
        return window.app_id.rsplit(".", 1)[-1].lower().replace(" ", "-")
    if window.title:
        return window.title.lower().replace(" ", "-")[:30]
    return f"{fallback_prefix}-{window.id}"


def infer_match_rule(window: Window) -> MatchRule:
    if window.app_id:
        return MatchRule(app_id=window.app_id)
    if window.title:
        return MatchRule(title=window.title)
    return MatchRule(title=f"window-{window.id}")
