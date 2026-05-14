from nirip.capture.capturer import capture_from_snapshot
from tests.conftest import Snap, Win, Ws


def test_capture_empty_snapshot() -> None:
    snap = Snap()
    result = capture_from_snapshot(snap, name="empty")
    assert result.spec.name == "empty"
    assert result.workspace_count == 0
    assert result.app_count == 0


def test_capture_single_workspace_single_window() -> None:
    snap = Snap(
        windows={1: Win(1, "firefox", "Docs", None, 10)},
        workspaces={10: Ws(10, "code", "DP-1")},
    )
    result = capture_from_snapshot(snap, name="test")
    assert result.workspace_count == 1
    assert result.app_count == 1
    ws = result.spec.workspaces[0]
    assert ws.name == "code"
    assert ws.output == "DP-1"


def test_capture_default_name() -> None:
    snap = Snap(workspaces={1: Ws(1, "ws", None)})
    result = capture_from_snapshot(snap)
    assert result.spec.name == "captured"


def test_capture_skips_unnamed_workspaces() -> None:
    snap = Snap(windows={}, workspaces={1: Ws(1, None, None)})
    result = capture_from_snapshot(snap)
    assert result.workspace_count == 0


def test_capture_window_without_workspace() -> None:
    snap = Snap(
        windows={1: Win(1, "firefox", None, None, 99)},
        workspaces={1: Ws(1, "code", None)},
    )
    result = capture_from_snapshot(snap)
    assert result.workspace_count == 1
    assert result.app_count == 0
