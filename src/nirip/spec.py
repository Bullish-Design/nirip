"""Session specification: models, validation, and YAML loading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)


class NiripError(Exception):
    """Base for all nirip errors."""


class SpecValidationError(NiripError):
    """Spec validation failed."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None) -> None:
        self.errors = errors
        self.warnings = warnings or []
        super().__init__(f"{len(errors)} error(s): {'; '.join(errors[:3])}")


_FROZEN = ConfigDict(extra="forbid", frozen=True)


class MatchRule(BaseModel):
    """Window matching rule with boolean composition."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

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


class SpawnSpec(BaseModel):
    model_config = _FROZEN

    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False


class PlacementSpec(BaseModel):
    model_config = _FROZEN

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


class AppSpec(BaseModel):
    model_config = _FROZEN

    name: str
    match: MatchRule
    spawn: SpawnSpec | None = None
    placement: PlacementSpec = Field(default_factory=PlacementSpec)
    optional: bool = False
    startup_timeout_s: float | None = None
    depends_on: list[str] = Field(default_factory=list)


class WorkspaceSpec(BaseModel):
    model_config = _FROZEN

    name: str
    output: str | None = None
    focus: bool = False
    apps: list[AppSpec] = Field(default_factory=list)


class SessionOptions(BaseModel):
    model_config = _FROZEN

    launch_missing: bool = True
    stop_on_error: bool = True
    default_startup_timeout_s: float = 20.0


class SessionSpec(BaseModel):
    model_config = _FROZEN

    name: str
    description: str = ""
    options: SessionOptions = Field(default_factory=SessionOptions)
    workspaces: list[WorkspaceSpec]


class ValidationResult(BaseModel):
    model_config = _FROZEN

    valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_session(spec: SessionSpec) -> ValidationResult:
    """Run all validation checks. Never raises - all problems in result."""
    errors: list[str] = []
    warnings: list[str] = []

    _check_unique_workspace_names(spec, errors)
    _check_unique_app_names(spec, errors)
    _check_depends_on_refs(spec, errors)
    _check_regex_patterns(spec, errors)
    _check_weak_matchers(spec, warnings)
    _check_inter_app_conflicts(spec, warnings)
    _check_spawn_commands(spec, errors)

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _check_unique_workspace_names(spec: SessionSpec, errors: list[str]) -> None:
    seen: set[str] = set()
    for ws in spec.workspaces:
        if ws.name in seen:
            errors.append(f"duplicate workspace name: {ws.name}")
        seen.add(ws.name)


def _check_unique_app_names(spec: SessionSpec, errors: list[str]) -> None:
    for ws in spec.workspaces:
        seen: set[str] = set()
        for app in ws.apps:
            if app.name in seen:
                errors.append(f"duplicate app name in workspace {ws.name}: {app.name}")
            seen.add(app.name)


def _check_depends_on_refs(spec: SessionSpec, errors: list[str]) -> None:
    """Validate depends_on references and check for cycles."""
    ws_apps: dict[str, set[str]] = {ws.name: {a.name for a in ws.apps} for ws in spec.workspaces}
    has_dangling = False

    for ws in spec.workspaces:
        for app in ws.apps:
            for dep in app.depends_on:
                if dep not in ws_apps[ws.name]:
                    errors.append(
                        f"{ws.name}/{app.name} depends on '{dep}' which does not exist "
                        f"in workspace '{ws.name}' (cross-workspace dependencies are not supported)"
                    )
                    has_dangling = True

    if has_dangling:
        return

    graph: dict[str, list[str]] = {}
    for ws in spec.workspaces:
        for app in ws.apps:
            key = f"{ws.name}/{app.name}"
            graph[key] = [f"{ws.name}/{dep}" for dep in app.depends_on]

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        if node in visiting:
            i = path.index(node)
            cycle = path[i:] + [node]
            errors.append(f"dependency cycle: {' -> '.join(cycle)}")
            return
        if node in visited:
            return
        visiting.add(node)
        path.append(node)
        for nxt in graph.get(node, []):
            dfs(nxt, path)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        dfs(node, [])


def _check_regex_patterns(spec: SessionSpec, errors: list[str]) -> None:
    def validate_rule(rule: MatchRule, prefix: str) -> None:
        for field_name, pattern in (("app_id_regex", rule.app_id_regex), ("title_regex", rule.title_regex)):
            if pattern is None:
                continue
            try:
                re.compile(pattern)
            except re.error as e:
                errors.append(f"{prefix}.{field_name} invalid regex '{pattern}': {e}")
        if rule.any_of:
            for i, sub in enumerate(rule.any_of):
                validate_rule(sub, f"{prefix}.any[{i}]")
        if rule.not_rule:
            validate_rule(rule.not_rule, f"{prefix}.not")

    for ws in spec.workspaces:
        for app in ws.apps:
            validate_rule(app.match, f"{ws.name}/{app.name}.match")


def _check_weak_matchers(spec: SessionSpec, warnings: list[str]) -> None:
    for ws in spec.workspaces:
        for app in ws.apps:
            m = app.match
            has_strong = any([m.app_id, m.app_id_regex, m.pid])
            if (m.title or m.title_regex) and not has_strong:
                kind = "title-only" if m.title and not m.title_regex else "title_regex-only"
                warnings.append(f"weak matcher in {ws.name}/{app.name}: {kind} rules can be unstable")


def _check_inter_app_conflicts(spec: SessionSpec, warnings: list[str]) -> None:
    signatures: dict[tuple[str, str, str, str, int | None], list[str]] = {}
    for ws in spec.workspaces:
        for app in ws.apps:
            m = app.match
            key = (m.app_id or "", m.app_id_regex or "", m.title or "", m.title_regex or "", m.pid)
            signatures.setdefault(key, []).append(f"{ws.name}/{app.name}")

    for key, owners in signatures.items():
        if len(owners) > 1 and key != ("", "", "", "", None):
            warnings.append(f"potential matcher conflict: {', '.join(owners)}")


def _check_spawn_commands(spec: SessionSpec, errors: list[str]) -> None:
    for ws in spec.workspaces:
        for app in ws.apps:
            if app.spawn is None:
                continue
            cmd = app.spawn.command
            if isinstance(cmd, str):
                if not cmd.strip():
                    errors.append(f"empty spawn command for {ws.name}/{app.name}")
            elif isinstance(cmd, list):
                if not cmd or not all(part.strip() for part in cmd):
                    errors.append(f"empty spawn command for {ws.name}/{app.name}")


def load_from_file(path: str | Path) -> tuple[SessionSpec, ValidationResult]:
    p = Path(path)
    if not p.exists():
        raise NiripError(f"file not found: {p}")
    text = p.read_text(encoding="utf-8")
    return load_from_string(text, source=str(p))


def load_from_string(text: str, *, source: str = "<string>") -> tuple[SessionSpec, ValidationResult]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise NiripError(f"YAML parse error in {source}: {e}") from e
    if not isinstance(data, dict):
        raise NiripError(f"expected mapping in {source}, got {type(data).__name__}")
    return load_from_dict(data, source=source)


def load_from_dict(data: dict[str, Any], *, source: str = "<dict>") -> tuple[SessionSpec, ValidationResult]:
    try:
        spec = SessionSpec.model_validate(data)
    except PydanticValidationError as e:
        raise NiripError(f"spec parse error in {source}: {e}") from e

    validation = validate_session(spec)

    if not validation.valid:
        raise SpecValidationError(validation.errors, validation.warnings)

    return spec, validation
