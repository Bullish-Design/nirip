"""Execution runtime state."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AppRuntimeState(BaseModel):
    """Ephemeral state for one app during a single apply."""

    app_name: str
    workspace_name: str
    matched_window_id: int | None = None
    spawned: bool = False
    spawn_pid: int | None = None
    completed: bool = False
    error: str | None = None


class SessionRuntime(BaseModel):
    """Ephemeral state during a single apply operation."""

    session_name: str
    apps: dict[str, AppRuntimeState] = Field(default_factory=dict)
    started_at: float | None = None
