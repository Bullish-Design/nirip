"""Spec normalization: SessionSpec -> NormalizedSession."""
from __future__ import annotations

from nirip.resolve.models import NormalizedApp, NormalizedSession, NormalizedWorkspace
from nirip.spec.defaults import apply_defaults
from nirip.spec.models import SessionSpec


def normalize(spec: SessionSpec) -> NormalizedSession:
    """Transform a validated SessionSpec into a NormalizedSession."""

    with_defaults = apply_defaults(spec)
    workspaces: list[NormalizedWorkspace] = []
    apps: list[NormalizedApp] = []
    app_index: dict[str, NormalizedApp] = {}

    for ws in with_defaults.workspaces:
        app_names: list[str] = []
        for app in ws.apps:
            key = f"{ws.name}/{app.name}"
            normalized = NormalizedApp(
                name=app.name,
                workspace_name=ws.name,
                match=app.match,
                spawn=app.spawn,
                placement=app.placement,
                optional=app.optional,
                startup_timeout_s=app.startup_timeout_s,
                depends_on=app.depends_on,
            )
            app_names.append(app.name)
            apps.append(normalized)
            app_index[key] = normalized

        workspaces.append(
            NormalizedWorkspace(
                name=ws.name,
                output=ws.output,
                focus=ws.focus,
                app_names=app_names,
            )
        )

    return NormalizedSession(
        name=with_defaults.name,
        description=with_defaults.description,
        options=with_defaults.options,
        workspaces=workspaces,
        apps=apps,
        app_index=app_index,
    )
