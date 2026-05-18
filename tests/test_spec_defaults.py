from types import SimpleNamespace
from typing import cast

from niri_state import Snapshot

from nirip.resolve.resolver import resolve
from nirip.spec.models import AppSpec, MatchRule, SessionOptions, SessionSpec, WorkspaceSpec


def test_default_timeout_is_applied_during_resolution() -> None:
    spec = SessionSpec(
        name="s",
        options=SessionOptions(default_startup_timeout_s=7.0),
        workspaces=[WorkspaceSpec(name="w", apps=[AppSpec(name="a", match=MatchRule(app_id="x"))])],
    )
    snapshot = cast(Snapshot, SimpleNamespace(windows={}, workspaces={}))
    resolution = resolve(spec, snapshot)
    assert resolution.workspace_resolutions[0].app_resolutions[0].startup_timeout_s == 7.0
