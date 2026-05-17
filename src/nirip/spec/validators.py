"""Session spec validation."""

from __future__ import annotations

import re

from pydantic import Field

from nirip._base import NiripModel
from nirip.spec.models import MatchRule, SessionSpec


class ValidationResult(NiripModel):
    valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ValidatedSpec(NiripModel):
    """A spec that passed parsing, bundled with its validation report."""

    spec: SessionSpec
    validation: ValidationResult


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
            if m.title_regex and not any([m.app_id, m.app_id_regex, m.title, m.pid]):
                warnings.append(
                    f"weak matcher in {ws.name}/{app.name}: title_regex-only rules can be unstable"
                )


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
