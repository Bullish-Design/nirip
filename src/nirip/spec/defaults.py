"""Default merging for session specs."""

from __future__ import annotations

from nirip.spec.models import SessionSpec


def apply_defaults(spec: SessionSpec) -> SessionSpec:
    """Return new SessionSpec with defaults applied to all apps.

    Note: Creates O(workspaces * apps) frozen copies. Fine at current scale
    but would need rethinking for multi-session orchestration.
    """
    default_timeout = spec.options.default_startup_timeout_s
    new_workspaces = []
    for ws in spec.workspaces:
        new_apps = []
        for app in ws.apps:
            if app.startup_timeout_s is None:
                app = app.model_copy(update={"startup_timeout_s": default_timeout})
            new_apps.append(app)
        new_workspaces.append(ws.model_copy(update={"apps": new_apps}))
    return spec.model_copy(update={"workspaces": new_workspaces})
