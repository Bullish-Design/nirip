"""Match-rule inference from live windows."""
from __future__ import annotations

from nirip.spec.models import MatchRule


def infer_app_name(window: object, fallback_prefix: str = "app") -> str:
    """Infer a stable app role name from a window."""

    app_id = getattr(window, "app_id", None)
    if app_id:
        return str(app_id).replace(" ", "-").lower()
    title = getattr(window, "title", None)
    if title:
        return str(title).split(" ", maxsplit=1)[0].replace(" ", "-").lower()
    window_id = getattr(window, "id", 0)
    return f"{fallback_prefix}-{window_id}"


def infer_match_rule(window: object) -> MatchRule:
    """Infer a conservative match rule from a window."""

    app_id = getattr(window, "app_id", None)
    if app_id:
        return MatchRule(app_id=str(app_id))
    title = getattr(window, "title", None)
    return MatchRule(title=str(title) if title else f"window-{getattr(window, 'id', 0)}")
