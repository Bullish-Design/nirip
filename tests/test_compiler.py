from types import SimpleNamespace
from typing import cast

import pytest
from niri_state import Snapshot

from nirip.errors import PlanningError
from nirip.planning.compiler import compile_plan, parse_size
from nirip.resolve.resolver import resolve
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, SpawnSpec, WorkspaceSpec


def test_compiler_propagates_spawn_and_wait_data() -> None:
    app = AppSpec(
        name="a",
        match=MatchRule(app_id="x"),
        spawn=SpawnSpec(command=["xterm"], cwd="/tmp", env={"A": "1"}, shell=False),
    )
    spec = SessionSpec(
        name="s",
        workspaces=[
            WorkspaceSpec(
                name="w",
                apps=[app],
            )
        ],
    )
    snap = cast(Snapshot, SimpleNamespace(windows={}, workspaces={}))
    resolution = resolve(spec, snap)
    plan = compile_plan(resolution, spec.options)
    kinds = [s.kind for s in plan.steps]
    assert "spawn_window" in kinds
    assert "wait_for_window" in kinds


def test_parse_size_float() -> None:
    assert parse_size(0.5) == (0.5, None)


def test_parse_size_int() -> None:
    assert parse_size(800) == (800.0, None)


def test_parse_size_px_valid() -> None:
    assert parse_size("px:1200") == (None, 1200)


def test_parse_size_px_invalid() -> None:
    with pytest.raises(PlanningError, match="invalid pixel size"):
        parse_size("px:abc")


def test_parse_size_string_proportion() -> None:
    assert parse_size("0.75") == (0.75, None)


def test_parse_size_garbage_string() -> None:
    with pytest.raises(PlanningError, match="invalid size value"):
        parse_size("garbage")
