"""Human-readable CLI output formatters."""

from __future__ import annotations

from nirip.execution.models import ApplyResult
from nirip.planning.models import Plan, SessionDiff


def format_diff(diff: SessionDiff) -> str:
    lines: list[str] = []
    if not diff.has_drift:
        return "No changes needed — session is converged."

    if diff.already_matched:
        lines.append(f"Matched: {len(diff.already_matched)} app(s)")
    if diff.will_spawn:
        lines.append("Will spawn:")
        for app in diff.will_spawn:
            lines.append(f"  + {app}")
    if diff.will_move:
        lines.append("Will move:")
        for app in diff.will_move:
            lines.append(f"  ~ {app}")
    if diff.drifted:
        lines.append("Drifted:")
        for app in diff.drifted:
            lines.append(f"  * {app}")
    if diff.workspace_changes:
        lines.append("Workspace changes:")
        for change in diff.workspace_changes:
            lines.append(f"  {change}")
    if diff.errors:
        lines.append("Errors:")
        for err in diff.errors:
            lines.append(f"  ! {err}")
    return "\n".join(lines)


def format_plan(plan: Plan) -> str:
    if plan.is_empty:
        return "Empty plan — nothing to do."
    lines = [f"Plan: {plan.step_count} step(s)"]
    for i, step in enumerate(plan.steps, 1):
        deps = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
        lines.append(f"  {i}. [{step.kind}] {step.description}{deps}")
    return "\n".join(lines)


def format_result(result: ApplyResult) -> str:
    status = "SUCCESS" if result.success else "FAILED"
    lines = [f"Result: {status} ({result.total_duration_s:.1f}s)"]
    lines.append(f"  Completed: {result.completed_count}, Skipped: {result.skipped_count}")
    if result.failed_steps:
        lines.append("  Failed steps:")
        for fs in result.failed_steps:
            lines.append(f"    - {fs.step.description}: {fs.message}")
    return "\n".join(lines)
