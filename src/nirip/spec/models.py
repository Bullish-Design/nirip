"""Session specification models."""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator

from nirip._base import NiripModel


class MatchRule(NiripModel):
    """Window matching rule with boolean composition."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    app_id: str | None = None
    app_id_regex: str | None = None
    title: str | None = None
    title_regex: str | None = None
    pid: int | None = None
    any_of: list[MatchRule] | None = Field(None, validation_alias="any")
    not_rule: MatchRule | None = Field(None, validation_alias="not")

    @model_validator(mode="after")
    def _validate_not_empty(self) -> MatchRule:
        has_leaf = any(
            [
                self.app_id,
                self.app_id_regex,
                self.title,
                self.title_regex,
                self.pid is not None,
            ]
        )
        has_composite = self.any_of is not None or self.not_rule is not None
        if not has_leaf and not has_composite:
            raise ValueError("MatchRule must have at least one criterion")
        return self


class SpawnSpec(NiripModel):
    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False


class PlacementSpec(NiripModel):
    floating: bool = False
    fullscreen: bool = False
    maximized: bool = False
    focus: bool = False
    column_width: float | str | None = None
    window_height: float | str | None = None

    @model_validator(mode="after")
    def _validate_mutual_exclusion(self) -> PlacementSpec:
        if self.floating and self.fullscreen:
            raise ValueError("floating and fullscreen are mutually exclusive")
        return self


class AppSpec(NiripModel):
    name: str
    match: MatchRule
    spawn: SpawnSpec | None = None
    placement: PlacementSpec = Field(default_factory=PlacementSpec)
    optional: bool = False
    startup_timeout_s: float | None = None
    depends_on: list[str] = Field(default_factory=list)


class WorkspaceSpec(NiripModel):
    name: str
    output: str | None = None
    focus: bool = False
    apps: list[AppSpec] = Field(default_factory=list)


class SessionOptions(NiripModel):
    launch_missing: bool = True
    stop_on_error: bool = True
    default_startup_timeout_s: float = 20.0


class SessionSpec(NiripModel):
    name: str
    description: str = ""
    options: SessionOptions = Field(default_factory=SessionOptions)
    workspaces: list[WorkspaceSpec]
