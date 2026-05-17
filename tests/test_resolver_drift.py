from nirip.resolve.models import DriftKind, ResolutionStatus
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec
from tests.conftest import FakeSnapshot, FakeWindow


def test_missing_workspace_causes_wrong_workspace_drift() -> None:
    app = AppSpec(name="a", match=MatchRule(app_id="x"))
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="target", apps=[app])],
    )
    normalized = normalize(spec)
    window = FakeWindow(
        id=1,
        app_id="x",
        title="",
        pid=None,
        workspace_id=99,
        is_floating=False,
        is_fullscreen=False,
        is_maximized=False,
    )
    snap = FakeSnapshot(
        windows={1: window},
        workspaces={},
    )
    result = resolve(normalized, snap)
    ar = result.workspace_resolutions[0].app_resolutions[0]
    assert ar.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_WORKSPACE for d in ar.drift)
