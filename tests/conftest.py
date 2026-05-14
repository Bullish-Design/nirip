"""Shared test fixtures."""

from dataclasses import dataclass, field


@dataclass
class Win:
    """Mock window for testing."""

    id: int
    app_id: str | None = None
    title: str | None = None
    pid: int | None = None
    workspace_id: int | None = None
    is_floating: bool = False
    is_fullscreen: bool = False
    is_maximized: bool = False


@dataclass
class Ws:
    """Mock workspace for testing."""

    id: int
    name: str | None = None
    output: str | None = None


@dataclass
class Snap:
    """Mock snapshot for testing."""

    windows: dict[int, Win] = field(default_factory=dict)
    workspaces: dict[int, Ws] = field(default_factory=dict)
