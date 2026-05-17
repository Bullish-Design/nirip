import pytest

from nirip.spec.models import MatchRule, SessionOptions


def test_match_rule_aliases() -> None:
    r = MatchRule.model_validate({"any": [{"app_id": "a"}]})
    assert r.any_of is not None


def test_match_rule_non_empty() -> None:
    with pytest.raises(ValueError):
        MatchRule()


def test_options_defaults() -> None:
    opts = SessionOptions()
    assert opts.launch_missing is True
    assert opts.stop_on_error is True
