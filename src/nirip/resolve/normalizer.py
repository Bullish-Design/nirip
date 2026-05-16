"""Spec normalization."""

from __future__ import annotations

from nirip.resolve.models import NormalizedApp, NormalizedSession, NormalizedWorkspace
from nirip.spec.models import SessionSpec


def normalize(spec: SessionSpec) -> NormalizedSession:
    apps: list[NormalizedApp] = []
    workspaces: list[NormalizedWorkspace] = []
    app_index: dict[str, NormalizedApp] = {}

    for ws in spec.workspaces:
        app_names: list[str] = []
        for app_spec in ws.apps:
            na = NormalizedApp(
                name=app_spec.name,
                workspace_name=ws.name,
                match=app_spec.match,
                spawn=app_spec.spawn,
                placement=app_spec.placement,
                optional=app_spec.optional,
                startup_timeout_s=(app_spec.startup_timeout_s or spec.options.default_startup_timeout_s),
                depends_on=app_spec.depends_on,
            )
            apps.append(na)
            app_names.append(app_spec.name)
            app_index[f"{ws.name}/{app_spec.name}"] = na

        workspaces.append(
            NormalizedWorkspace(name=ws.name, output=ws.output, focus=ws.focus, app_names=app_names)
        )

    return NormalizedSession(
        name=spec.name,
        description=spec.description,
        options=spec.options,
        workspaces=workspaces,
        apps=apps,
        app_index=app_index,
    )
