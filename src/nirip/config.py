"""Nirip configuration."""
from pathlib import Path

from pydantic import BaseModel


class NiripConfig(BaseModel, frozen=True):
    """Nirip-level configuration."""

    session_dir: Path = Path("~/.config/nirip/sessions")
    state_dir: Path = Path("~/.local/state/nirip")
    default_timeout_s: float = 20.0
    confirm_before_apply: bool = True
