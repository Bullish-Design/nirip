"""Nirip configuration."""

from __future__ import annotations

from pathlib import Path

from nirip._base import NiripModel


class NiripConfig(NiripModel):
    session_dir: Path = Path("~/.config/nirip/sessions")
    state_dir: Path = Path("~/.local/state/nirip")
    default_timeout_s: float = 20.0
    confirm_before_apply: bool = True
