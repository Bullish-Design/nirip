from typing import cast

from niri_pypc.types.generated.models import Window

from nirip.resolve.assigner import GreedyAssigner
from nirip.resolve.matcher import assign_windows, evaluate_rule
from nirip.resolve.models import MatchCandidate, MatchTier
from nirip.spec.models import AppSpec, MatchRule


class W:
    def __init__(self, wid: int, app_id: str, title: str = "") -> None:
        self.id = wid
        self.app_id = app_id
        self.title = title
        self.pid = None


def win(wid: int, app_id: str, title: str = "") -> Window:
    return cast(Window, W(wid, app_id, title))


def test_evaluate_rule() -> None:
    matched, tier, _ = evaluate_rule(MatchRule(app_id="x"), win(1, "x"))
    assert matched and tier == MatchTier.EXACT


def test_assign_windows_unique() -> None:
    apps = [
        ("w", AppSpec(name="a", match=MatchRule(app_id="x"))),
        ("w", AppSpec(name="b", match=MatchRule(app_id="y"))),
    ]
    decisions = assign_windows(apps, [win(1, "x"), win(2, "y")])
    ids = [d.assigned_window_id for d in decisions if d.assigned_window_id is not None]
    assert len(ids) == len(set(ids))


def test_greedy_assigner_competing_candidates() -> None:
    assigner = GreedyAssigner()
    apps = [
        ("w", AppSpec(name="a", match=MatchRule(app_id="a"))),
        ("w", AppSpec(name="b", match=MatchRule(app_id="b"))),
    ]
    candidates = [
        [
            MatchCandidate(window_id=10, tier=MatchTier.STRONG, reasons=["a->10"]),
            MatchCandidate(window_id=11, tier=MatchTier.WEAK, reasons=["a->11"]),
        ],
        [
            MatchCandidate(window_id=10, tier=MatchTier.EXACT, reasons=["b->10"]),
        ],
    ]
    # Greedy picks highest tier first, then enforces 1:1 uniqueness.
    assert assigner.assign(apps, candidates) == {1: 10, 0: 11}


def test_negation_only_rule_matches_non_target() -> None:
    rule = MatchRule(not_rule=MatchRule(app_id="firefox"))
    matched, tier, reasons = evaluate_rule(rule, win(1, "alacritty", "Terminal"))
    assert matched is True
    assert tier == MatchTier.WEAK
    assert any("not_rule satisfied" in r for r in reasons)


def test_negation_only_rule_rejects_target() -> None:
    rule = MatchRule(not_rule=MatchRule(app_id="firefox"))
    matched, tier, _reasons = evaluate_rule(rule, win(2, "firefox", "Firefox"))
    assert matched is False
    assert tier == MatchTier.NONE


def test_negation_combined_with_positive() -> None:
    rule = MatchRule(app_id="alacritty", not_rule=MatchRule(title="restricted"))
    matched, tier, _reasons = evaluate_rule(rule, win(3, "alacritty", "Terminal"))
    assert matched is True
    assert tier == MatchTier.EXACT
