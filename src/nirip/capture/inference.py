"""Match-rule inference from live windows."""
from __future__ import annotations

from nirip.resolve.matcher import WindowLike
from nirip.spec.models import MatchRule


def infer_app_name(window: WindowLike, fallback_prefix: str = "app") -> str:
    """Infer a stable app role name from a window."""

    app_id = window.app_id
    if app_id:
        return str(app_id).replace(" ", "-").lower()
    title = window.title
    if title:
        return str(title).split(" ", maxsplit=1)[0].replace(" ", "-").lower()
    return f"{fallback_prefix}-{window.id}"


def infer_match_rule(window: WindowLike) -> MatchRule:
    """Infer a conservative match rule from a window."""

    app_id = window.app_id
    if app_id:
        return MatchRule(app_id=str(app_id))
    title = window.title
    return MatchRule(title=str(title) if title else f"window-{window.id}")
