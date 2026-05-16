"""Ephemeral execution tracking state."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AppRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    app_name: str
    workspace_name: str
    matched_window_id: int | None = None
    spawned: bool = False
    spawn_pid: int | None = None
    completed: bool = False
    error: str | None = None


class SessionRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    session_name: str
    apps: dict[str, AppRuntimeState] = Field(default_factory=dict)
    started_at: float | None = None
