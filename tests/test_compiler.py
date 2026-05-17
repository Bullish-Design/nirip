import pytest
from types import SimpleNamespace

from nirip.errors import PlanningError
from nirip.planning.compiler import _parse_size, compile_plan
from nirip.resolve.normalizer import normalize
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
    normalized = normalize(spec)
    snap = SimpleNamespace(windows={}, workspaces={})
    resolution = resolve(normalized, snap)
    plan = compile_plan(resolution, normalized)
    kinds = [s.kind for s in plan.steps]
    assert "spawn_window" in kinds
    assert "wait_for_window" in kinds


def test_parse_size_float() -> None:
    assert _parse_size(0.5) == (0.5, None)


def test_parse_size_int() -> None:
    assert _parse_size(800) == (800.0, None)


def test_parse_size_px_valid() -> None:
    assert _parse_size("px:1200") == (None, 1200)


def test_parse_size_px_invalid() -> None:
    with pytest.raises(PlanningError, match="invalid pixel size"):
        _parse_size("px:abc")


def test_parse_size_string_proportion() -> None:
    assert _parse_size("0.75") == (0.75, None)


def test_parse_size_garbage_string() -> None:
    with pytest.raises(PlanningError, match="invalid size value"):
        _parse_size("garbage")
