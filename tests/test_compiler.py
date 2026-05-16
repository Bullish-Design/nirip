from types import SimpleNamespace

from nirip.planning.compiler import compile_plan
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
