from nirip.resolve.matcher import assign_windows, evaluate_rule
from nirip.spec.models import MatchRule


class W:
    def __init__(self, wid: int, app_id: str, title: str = "") -> None:
        self.id = wid
        self.app_id = app_id
        self.title = title
        self.pid = None


class A:
    def __init__(self, name: str, rule: MatchRule) -> None:
        self.name = name
        self.workspace_name = "w"
        self.match = rule


def test_evaluate_rule() -> None:
    matched, conf, _ = evaluate_rule(MatchRule(app_id="x"), W(1, "x"))
    assert matched and conf == 1.0


def test_assign_windows_unique() -> None:
    apps = [A("a", MatchRule(app_id="x")), A("b", MatchRule(app_id="y"))]
    decisions = assign_windows(apps, [W(1, "x"), W(2, "y")])
    ids = [d.assigned_window_id for d in decisions if d.assigned_window_id is not None]
    assert len(ids) == len(set(ids))
