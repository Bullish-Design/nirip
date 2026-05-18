from __future__ import annotations

from tests.conftest import FakeSnapshot, FakeWindow, FakeWorkspace

from nirip.plan import build_plan
from nirip.resolve import resolve
from nirip.spec import load_from_dict


def test_pipeline_load_resolve_plan() -> None:
    spec, report = load_from_dict(
        {
            "name": "dev",
            "workspaces": [
                {
                    "name": "web",
                    "apps": [
                        {
                            "name": "firefox",
                            "match": {"app_id": "org.mozilla.firefox"},
                        }
                    ],
                }
            ],
        }
    )
    assert report.valid
    snap = FakeSnapshot(
        windows={1: FakeWindow(id=1, app_id="org.mozilla.firefox", workspace_id=10)},
        workspaces={10: FakeWorkspace(id=10, name="web")},
    )
    resolution = resolve(spec, snap)  # type: ignore[arg-type]
    plan = build_plan(resolution, spec.options)
    assert plan.session_name == "dev"
