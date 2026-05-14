"""CLI command handlers."""
from __future__ import annotations

from pathlib import Path

import yaml

from nirip.facade.sync_nirip import SyncNirip
from nirip.spec.loader import load_spec_from_file


def cmd_diff(session_file: str) -> str:
    spec = load_spec_from_file(session_file)
    with SyncNirip() as nirip:
        diff = nirip.diff(spec)
    return yaml.safe_dump(diff.model_dump(mode="json"), sort_keys=False)


def cmd_plan(session_file: str) -> str:
    spec = load_spec_from_file(session_file)
    with SyncNirip() as nirip:
        plan = nirip.plan(spec)
    return yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False)


def cmd_apply(session_file: str) -> str:
    spec = load_spec_from_file(session_file)
    with SyncNirip() as nirip:
        result = nirip.apply(spec)
    return yaml.safe_dump(result.model_dump(mode="json"), sort_keys=False)


def cmd_capture(output: str | None = None) -> str:
    with SyncNirip() as nirip:
        captured = nirip.capture(name="captured")
    text = yaml.safe_dump(captured.spec.model_dump(mode="json", by_alias=True), sort_keys=False)
    if output:
        Path(output).write_text(text, encoding="utf-8")
    return text
