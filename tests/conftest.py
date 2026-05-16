"""Shared test fakes and fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeWindow:
    id: int
    app_id: str = ""
    title: str = ""
    pid: int | None = None
    workspace_id: int | None = None
    is_floating: bool = False
    is_fullscreen: bool = False
    is_maximized: bool = False


@dataclass
class FakeWorkspace:
    id: int
    name: str | None = None
    output: str = "DP-1"
    is_active: bool = False


@dataclass
class FakeSnapshot:
    windows: dict[int, Any] = field(default_factory=dict)
    workspaces: dict[int, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    focused_window_id: int | None = None
    focused_workspace_id: int | None = None


class RecordingClient:
    def __init__(self) -> None:
        self.requests: list[Any] = []
        self._closed = False

    async def request(self, req: Any, **kw: Any) -> Any:
        self.requests.append(req)
        return None

    async def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed
