from nirip.planning.compiler import compile_plan
from nirip.planning.models import StepKind
from nirip.resolve.models import DriftKind, ResolutionStatus
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.models import AppSpec, MatchRule, PlacementSpec, SessionSpec, WorkspaceSpec
from tests.conftest import Snap, Win, Ws


def test_wrong_workspace_drift() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[WorkspaceSpec(name="code", apps=[AppSpec(name="ed", match=MatchRule(app_id="nvim"))])],
    )
    snap = Snap(
        windows={1: Win(1, "nvim", None, None, 2)},
        workspaces={1: Ws(1, "code", None), 2: Ws(2, "other", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_WORKSPACE for d in app_res.drift)


def test_wrong_floating_drift() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[AppSpec(name="app", match=MatchRule(app_id="x"), placement=PlacementSpec(floating=True))],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1, is_floating=False)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_FLOATING for d in app_res.drift)


def test_wrong_fullscreen_drift() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[AppSpec(name="app", match=MatchRule(app_id="x"), placement=PlacementSpec(fullscreen=True))],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1, is_fullscreen=False)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_FULLSCREEN for d in app_res.drift)


def test_wrong_maximized_drift() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[AppSpec(name="app", match=MatchRule(app_id="x"), placement=PlacementSpec(maximized=True))],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1, is_maximized=False)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_MAXIMIZED for d in app_res.drift)


def test_fullscreen_drift_compiles_to_step() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[AppSpec(name="app", match=MatchRule(app_id="x"), placement=PlacementSpec(fullscreen=True))],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1, is_fullscreen=False)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    plan = compile_plan(res)
    assert any(s.kind == StepKind.SET_FULLSCREEN for s in plan.steps)


def test_no_drift_when_matched() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[WorkspaceSpec(name="ws", apps=[AppSpec(name="app", match=MatchRule(app_id="x"))])],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.MATCHED
    assert app_res.drift == []
