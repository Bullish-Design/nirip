from nirip.resolve.matcher import evaluate_rule, match_app
from nirip.spec.models import MatchRule
from tests.conftest import Win


class TestEvaluateRule:
    def test_app_id_exact_match(self) -> None:
        ok, conf, _ = evaluate_rule(MatchRule(app_id="firefox"), Win(1, "firefox", None, None, 1))
        assert ok
        assert conf == 1.0

    def test_app_id_mismatch(self) -> None:
        ok, _, _ = evaluate_rule(MatchRule(app_id="firefox"), Win(1, "chromium", None, None, 1))
        assert not ok

    def test_app_id_regex(self) -> None:
        ok, conf, _ = evaluate_rule(
            MatchRule(app_id_regex=r"fire.*"),
            Win(1, "firefox", None, None, 1),
        )
        assert ok
        assert conf == 0.9

    def test_app_id_regex_no_match(self) -> None:
        ok, _, _ = evaluate_rule(
            MatchRule(app_id_regex=r"^chrome$"),
            Win(1, "firefox", None, None, 1),
        )
        assert not ok

    def test_title_exact(self) -> None:
        ok, conf, _ = evaluate_rule(MatchRule(title="Docs"), Win(1, None, "Docs", None, 1))
        assert ok
        assert conf == 0.8

    def test_title_regex(self) -> None:
        ok, conf, _ = evaluate_rule(
            MatchRule(title_regex=r"GitHub.*"),
            Win(1, None, "GitHub - Pull Requests", None, 1),
        )
        assert ok
        assert conf == 0.7

    def test_pid_match(self) -> None:
        ok, conf, _ = evaluate_rule(MatchRule(pid=1234), Win(1, None, None, 1234, 1))
        assert ok
        assert conf == 1.0

    def test_pid_mismatch(self) -> None:
        ok, _, _ = evaluate_rule(MatchRule(pid=1234), Win(1, None, None, 5678, 1))
        assert not ok

    def test_any_of_one_match(self) -> None:
        rule = MatchRule(any_of=[MatchRule(app_id="firefox"), MatchRule(app_id="chromium")])
        ok, _, _ = evaluate_rule(rule, Win(1, "firefox", None, None, 1))
        assert ok

    def test_any_of_no_match(self) -> None:
        rule = MatchRule(any_of=[MatchRule(app_id="firefox"), MatchRule(app_id="chromium")])
        ok, _, _ = evaluate_rule(rule, Win(1, "safari", None, None, 1))
        assert not ok

    def test_not_rule_excludes(self) -> None:
        rule = MatchRule(app_id="firefox", not_rule=MatchRule(title="Private"))
        ok, _, _ = evaluate_rule(rule, Win(1, "firefox", "Private", None, 1))
        assert not ok

    def test_not_rule_passes(self) -> None:
        rule = MatchRule(app_id="firefox", not_rule=MatchRule(title="Private"))
        ok, _, _ = evaluate_rule(rule, Win(1, "firefox", "Docs", None, 1))
        assert ok

    def test_combined_criteria_lowers_confidence(self) -> None:
        rule = MatchRule(app_id="firefox", title_regex=r".*")
        ok, conf, _ = evaluate_rule(rule, Win(1, "firefox", "Docs", None, 1))
        assert ok
        assert conf == 0.7


class TestMatchApp:
    def test_no_windows(self) -> None:
        decision = match_app("app", "ws", MatchRule(app_id="x"), [])
        assert decision.best is None
        assert not decision.is_matched

    def test_ambiguous_match(self) -> None:
        windows = [
            Win(1, "firefox", None, None, 1),
            Win(2, "firefox", None, None, 1),
        ]
        decision = match_app("app", "ws", MatchRule(app_id="firefox"), windows)
        assert decision.is_ambiguous

    def test_single_match(self) -> None:
        windows = [
            Win(1, "firefox", None, None, 1),
            Win(2, "chromium", None, None, 1),
        ]
        decision = match_app("app", "ws", MatchRule(app_id="firefox"), windows)
        assert decision.best == 1
        assert not decision.is_ambiguous
