"""Plan compilation from resolution."""

from __future__ import annotations

from nirip.errors import PlanningError
from nirip.planning.builder import PlanBuilder
from nirip.planning.models import (
    Plan,
    SessionDiff,
)
from nirip.resolve.models import (
    AppResolution,
    DriftKind,
    Resolution,
    ResolutionStatus,
)
from nirip.spec.models import SessionOptions


def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
    """Policy: determine if this app resolution requires action."""
    match ar.status:
        case ResolutionStatus.MATCHED:
            return False
        case ResolutionStatus.OPTIONAL_MISSING:
            return False
        case ResolutionStatus.MISSING:
            return options.launch_missing
        case ResolutionStatus.DRIFTED:
            return True
        case ResolutionStatus.AMBIGUOUS:
            return False
        case _:
            raise ValueError(f"unhandled status: {ar.status}")


def compile_plan(resolution: Resolution, options: SessionOptions) -> Plan:
    """Compile resolution into ordered execution plan."""
    builder = PlanBuilder(parse_size=parse_size)

    for wr in resolution.workspace_resolutions:
        ensure_id = builder.ensure_workspace(wr)
        base_deps = [ensure_id] if ensure_id else []

        for ar in wr.app_resolutions:
            if not _should_act(ar, options):
                continue

            placement_deps = list(base_deps)

            if ar.status == ResolutionStatus.MISSING and ar.spec.spawn:
                placement_deps = builder.spawn_app(ar, wr.name, base_deps)

            builder.place_window(ar, wr, placement_deps)

    for wr in resolution.workspace_resolutions:
        if wr.focus:
            builder.focus_workspace(wr)

    builder.wire_app_dependencies(resolution)
    return Plan(session_name=resolution.session_name, steps=builder.build(), resolution=resolution)


def parse_size(value: float | str) -> tuple[float | None, int | None]:
    """Parse size value: float proportion or "px:<integer>" fixed pixels."""
    if isinstance(value, (int, float)):
        return (float(value), None)
    if isinstance(value, str):
        if value.startswith("px:"):
            try:
                return (None, int(value[3:]))
            except ValueError as e:
                raise PlanningError(f"invalid pixel size: {value!r} — expected 'px:<integer>'") from e
        try:
            return (float(value), None)
        except ValueError as e:
            raise PlanningError(f"invalid size value: {value!r}") from e
    raise PlanningError(f"unexpected size type: {type(value).__name__}")


def compile_diff(resolution: Resolution) -> SessionDiff:
    """Human-readable diff from resolution."""
    diff = SessionDiff(session_name=resolution.session_name, warnings=list(resolution.warnings))

    for wr in resolution.workspace_resolutions:
        if not wr.exists:
            diff.workspace_changes.append(f"workspace '{wr.name}' will be created")
        elif wr.desired_output and not wr.output_correct:
            diff.workspace_changes.append(
                f"workspace '{wr.name}' will move output {wr.current_output} -> {wr.desired_output}"
            )

        for ar in wr.app_resolutions:
            label = f"{wr.name}/{ar.app_name}"
            if ar.status == ResolutionStatus.MATCHED:
                diff.already_matched.append(label)
            elif ar.status == ResolutionStatus.OPTIONAL_MISSING:
                diff.optional_missing.append(label)
            elif ar.status == ResolutionStatus.MISSING:
                diff.will_spawn.append(label)
            elif ar.status == ResolutionStatus.DRIFTED:
                if ar.needs_move:
                    diff.will_move.append(label)
                if any(d.kind != DriftKind.WRONG_WORKSPACE for d in ar.drift):
                    diff.drifted.append(label)
            elif ar.status == ResolutionStatus.AMBIGUOUS:
                diff.errors.append(f"ambiguous match: {label}")

    return diff
