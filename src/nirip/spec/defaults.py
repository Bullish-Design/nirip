"""Default option merging for session specs."""
from __future__ import annotations

from nirip.spec.models import SessionSpec


def apply_defaults(spec: SessionSpec) -> SessionSpec:
    """Return a new SessionSpec with defaults applied to all apps."""

    default_timeout = spec.options.default_startup_timeout_s
    workspaces = []
    for ws in spec.workspaces:
        apps = []
        for app in ws.apps:
            if app.startup_timeout_s == 20.0 and default_timeout != 20.0:
                app = app.model_copy(update={"startup_timeout_s": default_timeout})
            apps.append(app)
        workspaces.append(ws.model_copy(update={"apps": apps}))
    return spec.model_copy(update={"workspaces": workspaces})
