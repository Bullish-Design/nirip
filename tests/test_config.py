import pytest

from nirip.config import NiripConfig


def test_default_config() -> None:
    cfg = NiripConfig()
    assert cfg.default_timeout_s == 20.0
    assert cfg.confirm_before_apply is True


def test_config_is_frozen() -> None:
    cfg = NiripConfig()
    with pytest.raises(Exception):  # noqa: B017
        cfg.default_timeout_s = 99.0


def test_config_paths_are_absolute() -> None:
    cfg = NiripConfig()
    assert cfg.session_dir.is_absolute()
    assert cfg.state_dir.is_absolute()
    assert "~" not in str(cfg.session_dir)
    assert "~" not in str(cfg.state_dir)
