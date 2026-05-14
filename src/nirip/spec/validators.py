"""Aggressive session spec validation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from nirip.spec.models import AppSpec, MatchRule, SessionSpec


@dataclass(slots=True)
class ValidationResult:
    """Validation output."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0


def validate_session(spec: SessionSpec) -> ValidationResult:
    """Run all validation checks on a session spec."""

    result = ValidationResult()
    _check_unique_workspace_names(spec, result)
    _check_unique_app_names(spec, result)
    _check_depends_on_refs(spec, result)
    _check_regex_patterns(spec, result)
    _check_weak_matchers(spec, result)
    _check_inter_app_conflicts(spec, result)
    _check_spawn_commands(spec, result)
    return result


def _check_unique_workspace_names(spec: SessionSpec, result: ValidationResult) -> None:
    seen: set[str] = set()
    for ws in spec.workspaces:
        if ws.name in seen:
            result.errors.append(f"Duplicate workspace name: {ws.name}")
        seen.add(ws.name)


def _check_unique_app_names(spec: SessionSpec, result: ValidationResult) -> None:
    for ws in spec.workspaces:
        seen: set[str] = set()
        for app in ws.apps:
            if app.name in seen:
                result.errors.append(f"Duplicate app name '{app.name}' in workspace '{ws.name}'")
            seen.add(app.name)


def _dfs_cycle(
    name: str,
    *,
    app_map: dict[str, AppSpec],
    temporary: set[str],
    permanent: set[str],
    workspace_name: str,
    result: ValidationResult,
) -> None:
    if name in permanent:
        return
    if name in temporary:
        result.errors.append(f"Dependency cycle detected in workspace '{workspace_name}' at '{name}'")
        return

    temporary.add(name)
    app = app_map.get(name)
    if app is not None:
        for dep in app.depends_on:
            _dfs_cycle(
                dep,
                app_map=app_map,
                temporary=temporary,
                permanent=permanent,
                workspace_name=workspace_name,
                result=result,
            )
    temporary.remove(name)
    permanent.add(name)


def _check_depends_on_refs(spec: SessionSpec, result: ValidationResult) -> None:
    for ws in spec.workspaces:
        app_map = {app.name: app for app in ws.apps}
        for app in ws.apps:
            for dep in app.depends_on:
                if dep not in app_map:
                    result.errors.append(
                        f"depends_on reference '{dep}' missing for app '{app.name}' in workspace '{ws.name}'"
                    )

        temporary: set[str] = set()
        permanent: set[str] = set()
        for app in ws.apps:
            _dfs_cycle(
                app.name,
                app_map=app_map,
                temporary=temporary,
                permanent=permanent,
                workspace_name=ws.name,
                result=result,
            )


def _rules(rule: MatchRule) -> list[MatchRule]:
    nested: list[MatchRule] = [rule]
    if rule.any_of:
        for sub in rule.any_of:
            nested.extend(_rules(sub))
    if rule.not_rule:
        nested.extend(_rules(rule.not_rule))
    return nested


def _check_regex_patterns(spec: SessionSpec, result: ValidationResult) -> None:
    for ws in spec.workspaces:
        for app in ws.apps:
            for rule in _rules(app.match):
                for pattern in [rule.app_id_regex, rule.title_regex]:
                    if pattern is None:
                        continue
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        result.errors.append(
                            f"Invalid regex for app '{app.name}' in workspace '{ws.name}': {pattern!r} ({exc})"
                        )


def _check_weak_matchers(spec: SessionSpec, result: ValidationResult) -> None:
    for ws in spec.workspaces:
        for app in ws.apps:
            rule = app.match
            weak = rule.title_regex is not None and rule.app_id is None and rule.app_id_regex is None
            if weak and not app.optional:
                result.warnings.append(
                    f"App '{app.name}' in workspace '{ws.name}' uses title_regex-only matching; this is fragile"
                )


def _match_signature(app: AppSpec) -> tuple[str | None, str | None, str | None, str | None, int | None]:
    m = app.match
    return (m.app_id, m.app_id_regex, m.title, m.title_regex, m.pid)


def _check_inter_app_conflicts(spec: SessionSpec, result: ValidationResult) -> None:
    local: dict[tuple[str, tuple[str | None, str | None, str | None, str | None, int | None]], str] = {}
    global_map: dict[tuple[str | None, str | None, str | None, str | None, int | None], tuple[str, str]] = {}

    for ws in spec.workspaces:
        for app in ws.apps:
            sig = _match_signature(app)
            if app.match.app_id is None:
                continue
            key = (ws.name, sig)
            if key in local:
                result.errors.append(
                    f"Conflicting match criteria in workspace '{ws.name}' for apps '{local[key]}' and '{app.name}'"
                )
            else:
                local[key] = app.name

            if sig in global_map and global_map[sig][0] != ws.name:
                prev_ws, prev_app = global_map[sig]
                result.warnings.append(
                    f"Apps '{prev_app}' ({prev_ws}) and '{app.name}' ({ws.name}) share identical match criteria"
                )
            else:
                global_map[sig] = (ws.name, app.name)


def _check_spawn_commands(spec: SessionSpec, result: ValidationResult) -> None:
    for ws in spec.workspaces:
        for app in ws.apps:
            spawn = app.spawn
            if spawn is None:
                continue
            if isinstance(spawn.command, str):
                if not spawn.command.strip():
                    result.errors.append(f"Empty spawn command for app '{app.name}' in workspace '{ws.name}'")
            elif len(spawn.command) == 0:
                result.errors.append(f"Empty spawn command for app '{app.name}' in workspace '{ws.name}'")
