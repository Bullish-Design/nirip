from __future__ import annotations

from tests.conftest import FakeSnapshot, FakeWindow, FakeWorkspace

from nirip.resolve import MatchTier, ResolutionStatus, evaluate_rule, resolve
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
