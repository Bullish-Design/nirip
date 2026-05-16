from pydantic import ValidationError

from nirip.config import NiripConfig


def test_defaults() -> None:
    c = NiripConfig()
    assert c.default_timeout_s == 20.0
    assert c.confirm_before_apply is True


def test_forbid_unknown() -> None:
    try:
        NiripConfig(other=True)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        assert True
