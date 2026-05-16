from types import SimpleNamespace

from nirip.capture.capturer import capture_from_snapshot


def test_capture_from_snapshot(monkeypatch) -> None:
    ws = SimpleNamespace(id=1, name="w", output="DP-1")
    w = SimpleNamespace(id=10, app_id="org.x", title="x")

    monkeypatch.setattr("nirip.capture.capturer.workspaces.list_workspaces", lambda _s: [ws])
    monkeypatch.setattr("nirip.capture.capturer.windows.list_windows_on_workspace", lambda _s, _id: [w])

    captured = capture_from_snapshot(SimpleNamespace(), name="c")
    assert captured.spec.name == "c"
    assert captured.workspace_count == 1
