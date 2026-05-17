from nirip.resolve.matcher import assign_windows, evaluate_rule
from nirip.spec.models import AppSpec, MatchRule


class W:
    def __init__(self, wid: int, app_id: str, title: str = "") -> None:
        self.id = wid
        self.app_id = app_id
        self.title = title
        self.pid = None


def test_evaluate_rule() -> None:
    matched, conf, _ = evaluate_rule(MatchRule(app_id="x"), W(1, "x"))
    assert matched and conf == 1.0


def test_assign_windows_unique() -> None:
    apps = [
        ("w", AppSpec(name="a", match=MatchRule(app_id="x"))),
        ("w", AppSpec(name="b", match=MatchRule(app_id="y"))),
    ]
    decisions = assign_windows(apps, [W(1, "x"), W(2, "y")])
    ids = [d.assigned_window_id for d in decisions if d.assigned_window_id is not None]
    assert len(ids) == len(set(ids))


def test_negation_only_rule_matches_non_target() -> None:
    rule = MatchRule(not_rule=MatchRule(app_id="firefox"))
    matched, confidence, reasons = evaluate_rule(rule, W(1, "alacritty", "Terminal"))
    assert matched is True
    assert confidence == 0.4
    assert any("not_rule satisfied" in r for r in reasons)


def test_negation_only_rule_rejects_target() -> None:
    rule = MatchRule(not_rule=MatchRule(app_id="firefox"))
    matched, confidence, _reasons = evaluate_rule(rule, W(2, "firefox", "Firefox"))
    assert matched is False
    assert confidence == 0.0


def test_negation_combined_with_positive() -> None:
    rule = MatchRule(app_id="alacritty", not_rule=MatchRule(title="restricted"))
    matched, confidence, _reasons = evaluate_rule(rule, W(3, "alacritty", "Terminal"))
    assert matched is True
    assert confidence == 1.0
