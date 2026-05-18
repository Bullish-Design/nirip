from __future__ import annotations

from tests.conftest import FakeSnapshot, FakeWindow, FakeWorkspace

from nirip.resolve import MatchTier, ResolutionStatus, _assign, _detect_drift, evaluate_rule, resolve
from nirip.spec import MatchRule, SessionSpec


def test_evaluate_rule_exact_and_failed() -> None:
    w = FakeWindow(id=1, app_id="org.mozilla.firefox", title="Firefox")
    matched, tier = evaluate_rule(MatchRule(app_id="org.mozilla.firefox"), w)  # type: ignore[arg-type]
    assert matched is True
    assert tier == MatchTier.EXACT


def test_resolve_flat_apps_and_drift() -> None:
    spec = SessionSpec.model_validate(
        {
            "name": "dev",
            "workspaces": [
                {
                    "name": "code",
                    "output": "DP-1",
                    "apps": [
                        {
                            "name": "term",
                            "match": {"app_id": "alacritty"},
                            "placement": {"floating": True},
                        }
                    ],
                }
            ],
        }
    )
    snap = FakeSnapshot(
        windows={1: FakeWindow(id=1, app_id="alacritty", workspace_id=2, is_floating=False)},
        workspaces={2: FakeWorkspace(id=2, name="other", output="DP-2")},
    )
    res = resolve(spec, snap)  # type: ignore[arg-type]
    assert len(res.workspaces) == 1
    assert len(res.apps) == 1
    assert res.apps[0].status == ResolutionStatus.DRIFTED
    assert res.apps[0].needs_move is True


def test_resolve_optional_missing() -> None:
    spec = SessionSpec.model_validate(
        {
            "name": "dev",
            "workspaces": [{"name": "code", "apps": [{"name": "x", "match": {"app_id": "x"}, "optional": True}]}],
        }
    )
    snap = FakeSnapshot(windows={}, workspaces={1: FakeWorkspace(id=1, name="code")})
    res = resolve(spec, snap)  # type: ignore[arg-type]
    assert res.apps[0].status == ResolutionStatus.OPTIONAL_MISSING


def test_evaluate_rule_composite_any_and_not() -> None:
    w = FakeWindow(id=1, app_id="org.mozilla.firefox", title="Firefox")
    rule = MatchRule.model_validate(
        {"any": [{"app_id": "org.mozilla.firefox"}, {"title": "Nope"}], "not": {"title": "Chrome"}}
    )
    matched, tier = evaluate_rule(rule, w)  # type: ignore[arg-type]
    assert matched is True
    assert tier == MatchTier.EXACT


def test_assign_marks_ambiguous_top_tier() -> None:
    apps = [("code", type("A", (), {"match": MatchRule(app_id_regex="fire")})())]
    wins = [
        FakeWindow(id=1, app_id="firefox"),
        FakeWindow(id=2, app_id="firebird"),
    ]
    assignments = _assign(apps, wins)  # type: ignore[arg-type]
    assert assignments[0].window_id in {1, 2}
    assert assignments[0].is_ambiguous is True


def test_detect_drift_flags_state_and_workspace() -> None:
    win = FakeWindow(id=1, workspace_id=2, is_floating=False, is_fullscreen=False, is_maximized=False)
    app = type(
        "AR",
        (),
        {"placement": type("P", (), {"floating": True, "fullscreen": False, "maximized": False})()},
    )()
    ws_by_name = {"code": FakeWorkspace(id=1, name="code")}
    drift = _detect_drift(win, app, "code", ws_by_name)  # type: ignore[arg-type]
    kinds = {d.kind.value for d in drift}
    assert "wrong_workspace" in kinds
    assert "wrong_floating" in kinds
