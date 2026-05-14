"""Session specification models."""
from __future__ import annotations

import builtins
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MatchRule(BaseModel):
    """How to find an existing window that fills this role."""

    model_config = ConfigDict(populate_by_name=True)

    app_id: str | None = None
    app_id_regex: str | None = None
    title: str | None = None
    title_regex: str | None = None
    pid: int | None = None
    any_of: list[MatchRule] | None = Field(default=None, alias="any")
    not_rule: MatchRule | None = None

    @model_validator(mode="after")
    def validate_not_empty(self) -> Self:
        criteria = [
            self.app_id is not None,
            self.app_id_regex is not None,
            self.title is not None,
            self.title_regex is not None,
            self.pid is not None,
            self.any_of is not None,
            self.not_rule is not None,
        ]
        if not builtins.any(criteria):
            raise ValueError("MatchRule must have at least one matching criterion.")
        return self


class SpawnSpec(BaseModel):
    """How to launch a window if no match is found."""

    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False


class PlacementSpec(BaseModel):
    """Where and how a window should be placed."""

    floating: bool = False
    fullscreen: bool = False
    maximized: bool = False
    focus: bool = False
    column_width: float | str | None = None
    window_height: float | str | None = None

    @model_validator(mode="after")
    def validate_placement(self) -> Self:
        if self.floating and self.fullscreen:
            raise ValueError("floating and fullscreen are mutually exclusive")
        return self


class AppSpec(BaseModel):
    """A single window role within a workspace."""

    name: str
    match: MatchRule
    spawn: SpawnSpec | None = None
    placement: PlacementSpec = Field(default_factory=PlacementSpec)
    optional: bool = False
    startup_timeout_s: float = 20.0
    depends_on: list[str] = Field(default_factory=list)


class WorkspaceSpec(BaseModel):
    """A named workspace and desired window layout."""

    name: str
    output: str | None = None
    focus: bool = False
    apps: list[AppSpec] = Field(default_factory=list)


class SessionOptions(BaseModel):
    """Global options for session apply behavior."""

    mode: str = "reconcile"
    match_existing: bool = True
    launch_missing: bool = True
    stop_on_error: bool = True
    move_unmatched: bool = False
    default_startup_timeout_s: float = 20.0


class SessionSpec(BaseModel):
    """Top-level session declaration."""

    name: str
    description: str = ""
    options: SessionOptions = Field(default_factory=SessionOptions)
    workspaces: list[WorkspaceSpec]
