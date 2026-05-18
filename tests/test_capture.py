from __future__ import annotations

from unittest.mock import Mock

from tests.conftest import FakeSnapshot, FakeWindow, FakeWorkspace

from nirip.capture import capture


def test_capture_builds_session_spec(monkeypatch) -> None:
    snap = FakeSnapshot(
        windows={1: FakeWindow(id=1, app_id="org.mozilla.firefox", title="Firefox", workspace_id=10)},
        workspaces={10: FakeWorkspace(id=10, name="web", output="DP-1")},
    )
    monkeypatch.setattr("nirip.capture.workspaces.list_workspaces", Mock(return_value=tuple(snap.workspaces.values())))
    monkeypatch.setattr(
        "nirip.capture.windows.list_windows_on_workspace", Mock(return_value=tuple(snap.windows.values()))
    )
    spec = capture(snap, name="captured")  # type: ignore[arg-type]
    assert spec.name == "captured"
    assert spec.workspaces[0].name == "web"
    assert spec.workspaces[0].apps[0].match.app_id == "org.mozilla.firefox"
