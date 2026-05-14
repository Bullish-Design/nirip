"""Full pipeline integration test: YAML -> apply result."""

import asyncio

from nirip.execution.executor import PlanExecutor
from nirip.execution.models import StepOutcome
from nirip.planning.compiler import compile_plan
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.loader import load_spec_from_string
from tests.conftest import Snap, Win, Ws

YAML_SPEC = """\
name: dev-session
options:
  stop_on_error: true
  default_startup_timeout_s: 10.0
workspaces:
  - name: code
    apps:
      - name: editor
        match:
          app_id: nvim
        spawn:
          command: ["nvim"]
      - name: terminal
        match:
          app_id: foot
        spawn:
          command: ["foot"]
  - name: browser
    apps:
      - name: firefox
        match:
          app_id: firefox
        spawn:
          command: ["firefox"]
"""


def test_full_pipeline_all_matched() -> None:
    spec = load_spec_from_string(YAML_SPEC)
    snap = Snap(
        windows={
            1: Win(1, "nvim", None, None, 10),
            2: Win(2, "foot", None, None, 10),
            3: Win(3, "firefox", None, None, 20),
        },
        workspaces={
            10: Ws(10, "code", None),
            20: Ws(20, "browser", None),
        },
    )
    normalized = normalize(spec)
    resolution = resolve(normalized, snap)
    plan = compile_plan(resolution)
    assert plan.is_empty
    assert resolution.fully_converged


def test_full_pipeline_missing_app() -> None:
    spec = load_spec_from_string(YAML_SPEC)
    snap = Snap(
        windows={
            1: Win(1, "nvim", None, None, 10),
            3: Win(3, "firefox", None, None, 20),
        },
        workspaces={
            10: Ws(10, "code", None),
            20: Ws(20, "browser", None),
        },
    )
    normalized = normalize(spec)
    resolution = resolve(normalized, snap)
    plan = compile_plan(resolution)
    assert not plan.is_empty
    assert plan.requires_spawn
    step_descriptions = [s.description for s in plan.steps]
    assert any("terminal" in d for d in step_descriptions)


def test_full_pipeline_execute_dry_run() -> None:
    spec = load_spec_from_string(YAML_SPEC)
    snap = Snap(
        windows={1: Win(1, "nvim", None, None, 10)},
        workspaces={10: Ws(10, "code", None), 20: Ws(20, "browser", None)},
    )
    normalized = normalize(spec)
    resolution = resolve(normalized, snap)
    plan = compile_plan(resolution)
    executor = PlanExecutor(client=None)
    result = asyncio.run(executor.execute(plan, snapshot=snap))
    assert result.success
    for step_result in result.steps:
        assert step_result.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED)


def test_full_pipeline_missing_workspace() -> None:
    spec = load_spec_from_string(YAML_SPEC)
    snap = Snap(
        windows={},
        workspaces={10: Ws(10, "code", None)},
    )
    normalized = normalize(spec)
    resolution = resolve(normalized, snap)
    plan = compile_plan(resolution)
    assert any("browser" in s.description and "workspace" in s.description.lower() for s in plan.steps)
