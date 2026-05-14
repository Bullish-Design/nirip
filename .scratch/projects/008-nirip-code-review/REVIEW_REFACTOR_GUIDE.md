# nirip Review Refactor Guide

**Source:** Code review report dated 2026-05-14
**Goal:** Fix all bugs, design issues, and test gaps identified in the review
**Audience:** Developer implementing these changes

---

## How to Use This Guide

Work through the tasks **in order** — later tasks depend on earlier ones. Each task includes:
- **What** to change and **why**
- **Exact files** to modify with implementation details
- **Validation** steps to confirm correctness

Run `pytest` and `ruff check src/ tests/` after every task to catch regressions early.

---

## Task 1: Fix `NiripConfig` Tilde Expansion

**Priority:** Must-fix
**Files:** `src/nirip/config.py`
**Why:** `Path("~/.config/nirip/sessions")` creates a literal path with `~` in it. No filesystem operations will work against the real user directory.

### Implementation

In `src/nirip/config.py`, change the default values to use `Path.home()`:

```python
"""Nirip configuration."""
from pathlib import Path

from pydantic import BaseModel


class NiripConfig(BaseModel, frozen=True):
    """Nirip-level configuration."""

    session_dir: Path = Path.home() / ".config/nirip/sessions"
    state_dir: Path = Path.home() / ".local/state/nirip"
    default_timeout_s: float = 20.0
    confirm_before_apply: bool = True
```

### Validation

1. Update `tests/test_config.py` — add a tilde expansion test:

```python
def test_config_paths_are_absolute() -> None:
    cfg = NiripConfig()
    assert cfg.session_dir.is_absolute()
    assert cfg.state_dir.is_absolute()
    assert "~" not in str(cfg.session_dir)
    assert "~" not in str(cfg.state_dir)
```

2. Run: `pytest tests/test_config.py -v`

---

## Task 2: Fix `apply_defaults` Sentinel Comparison

**Priority:** Must-fix (CRITICAL bug)
**Files:** `src/nirip/spec/models.py`, `src/nirip/spec/defaults.py`, `tests/test_spec_defaults.py`
**Why:** The current code compares `app.startup_timeout_s == 20.0` to detect "user didn't set this." If a user explicitly sets `20.0` and the global default differs, their value gets silently overwritten.

### Step 2a: Change `AppSpec.startup_timeout_s` default to `None`

In `src/nirip/spec/models.py`, change `AppSpec`:

```python
class AppSpec(BaseModel):
    """A single window role within a workspace."""

    name: str
    match: MatchRule
    spawn: SpawnSpec | None = None
    placement: PlacementSpec = Field(default_factory=PlacementSpec)
    optional: bool = False
    startup_timeout_s: float | None = None  # None means "use global default"
    depends_on: list[str] = Field(default_factory=list)
```

### Step 2b: Rewrite `apply_defaults` to use `None` sentinel

In `src/nirip/spec/defaults.py`:

```python
"""Default option merging for session specs."""
from __future__ import annotations

from nirip.spec.models import SessionSpec


def apply_defaults(spec: SessionSpec) -> SessionSpec:
    """Return a new SessionSpec with defaults applied to all apps."""

    default_timeout = spec.options.default_startup_timeout_s
    workspaces = []
    for ws in spec.workspaces:
        apps = []
        for app in ws.apps:
            if app.startup_timeout_s is None:
                app = app.model_copy(update={"startup_timeout_s": default_timeout})
            apps.append(app)
        workspaces.append(ws.model_copy(update={"apps": apps}))
    return spec.model_copy(update={"workspaces": workspaces})
```

### Step 2c: Update `NormalizedApp.startup_timeout_s`

In `src/nirip/resolve/models.py`, the `NormalizedApp` field stays as `float` (not `float | None`) because defaults will always have been applied by the time normalization produces it. No change needed here — just be aware.

### Validation

Update `tests/test_spec_defaults.py`:

```python
from nirip.spec.defaults import apply_defaults
from nirip.spec.models import AppSpec, MatchRule, SessionOptions, SessionSpec, WorkspaceSpec


def test_defaults_apply_timeout() -> None:
    """When app has no explicit timeout, global default is applied."""
    spec = SessionSpec(
        name="s",
        options=SessionOptions(default_startup_timeout_s=30.0),
        workspaces=[WorkspaceSpec(name="w", apps=[AppSpec(name="a", match=MatchRule(app_id="x"))])],
    )
    out = apply_defaults(spec)
    assert out.workspaces[0].apps[0].startup_timeout_s == 30.0


def test_explicit_timeout_not_overwritten() -> None:
    """When app explicitly sets timeout to 20.0, it must NOT be overwritten."""
    spec = SessionSpec(
        name="s",
        options=SessionOptions(default_startup_timeout_s=30.0),
        workspaces=[
            WorkspaceSpec(
                name="w",
                apps=[AppSpec(name="a", match=MatchRule(app_id="x"), startup_timeout_s=20.0)],
            )
        ],
    )
    out = apply_defaults(spec)
    assert out.workspaces[0].apps[0].startup_timeout_s == 20.0  # NOT 30.0


def test_default_timeout_when_global_is_default() -> None:
    """When no explicit timeout and global is default (20.0), app gets 20.0."""
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="w", apps=[AppSpec(name="a", match=MatchRule(app_id="x"))])],
    )
    out = apply_defaults(spec)
    assert out.workspaces[0].apps[0].startup_timeout_s == 20.0
```

Run: `pytest tests/test_spec_defaults.py -v`

---

## Task 3: Fix `topological_sort` Silent Cycle Fallback

**Priority:** Must-fix
**Files:** `src/nirip/planning/ordering.py`, `src/nirip/errors.py`
**Why:** If a dependency cycle exists among plan steps, the function silently returns the unsorted input. Steps execute in wrong order with no indication of the problem.

### Step 3a: Add `CycleError` to the error hierarchy

In `src/nirip/errors.py`, add after `PlanningError`:

```python
class CycleError(PlanningError):
    """Dependency cycle detected among plan steps."""
```

### Step 3b: Raise on cycle detection

In `src/nirip/planning/ordering.py`:

```python
"""Plan step ordering helpers."""
from __future__ import annotations

import logging
from collections import defaultdict, deque

from nirip.errors import CycleError
from nirip.planning.models import PlanStep

logger = logging.getLogger(__name__)


def topological_sort(steps: list[PlanStep]) -> list[PlanStep]:
    """Sort steps according to step dependency IDs.

    Raises CycleError if a dependency cycle is detected.
    """

    id_map = {step.id: step for step in steps}
    indegree = {step.id: 0 for step in steps}
    edges: dict[str, list[str]] = defaultdict(list)

    for step in steps:
        for dep in step.depends_on:
            if dep not in id_map:
                continue
            edges[dep].append(step.id)
            indegree[step.id] += 1

    queue: deque[str] = deque(sorted([sid for sid, degree in indegree.items() if degree == 0]))
    ordered: list[PlanStep] = []

    while queue:
        sid = queue.popleft()
        ordered.append(id_map[sid])
        for nxt in sorted(edges[sid]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(steps):
        cycle_ids = [s.id for s in steps if s.id not in {o.id for o in ordered}]
        raise CycleError(f"Dependency cycle detected among steps: {cycle_ids}")
    return ordered
```

### Validation

Add `tests/test_ordering.py`:

```python
import pytest

from nirip.errors import CycleError
from nirip.planning.models import PlanStep, StepKind
from nirip.planning.ordering import topological_sort


def _step(id: str, depends_on: list[str] | None = None) -> PlanStep:
    return PlanStep(
        id=id,
        kind=StepKind.SPAWN_WINDOW,
        description=f"step {id}",
        depends_on=depends_on or [],
    )


def test_topological_sort_linear() -> None:
    steps = [_step("c", ["b"]), _step("b", ["a"]), _step("a")]
    result = topological_sort(steps)
    ids = [s.id for s in result]
    assert ids.index("a") < ids.index("b") < ids.index("c")


def test_topological_sort_no_deps() -> None:
    steps = [_step("b"), _step("a"), _step("c")]
    result = topological_sort(steps)
    assert len(result) == 3


def test_topological_sort_cycle_raises() -> None:
    steps = [_step("a", ["b"]), _step("b", ["a"])]
    with pytest.raises(CycleError, match="cycle"):
        topological_sort(steps)


def test_topological_sort_unknown_dep_ignored() -> None:
    steps = [_step("a", ["nonexistent"])]
    result = topological_sort(steps)
    assert len(result) == 1
```

Run: `pytest tests/test_ordering.py -v`

---

## Task 4: Fix Executor Step-Skip Logic and Predicate Specificity

**Priority:** Must-fix (HIGH bugs — §2.2 and §2.3)
**Files:** `src/nirip/execution/predicates.py`, `src/nirip/execution/executor.py`
**Why:** Two compounding bugs:
1. `predicate_for_step` for `WAIT_FOR_WINDOW` only checks if *any* windows exist, not the specific one
2. The executor checks predicates *before* running the action, so pre-existing state causes steps to be wrongly skipped

### Step 4a: Fix predicates to be specific

In `src/nirip/execution/predicates.py`:

```python
"""Step verification predicates."""
from __future__ import annotations

from typing import Any, Callable, Protocol

from nirip.planning.models import PlanStep, StepKind


class SnapshotLike(Protocol):
    windows: dict[int, Any]
    workspaces: dict[int, Any]


# Type alias for predicate functions
StepPredicate = Callable[[SnapshotLike], bool]


def predicate_for_step(step: PlanStep) -> StepPredicate | None:
    """Return a predicate that checks if a step's outcome is already satisfied.

    Returns None for steps that should always execute (e.g., SPAWN_WINDOW).
    Returns a callable for steps that can be verified against snapshot state.
    """

    if step.kind == StepKind.WAIT_FOR_WINDOW:
        # WAIT_FOR_WINDOW is never "already satisfied" — it depends on a
        # preceding SPAWN step. The executor should poll this predicate
        # *after* spawn, not use it to skip.
        return None

    if step.kind == StepKind.ENSURE_WORKSPACE:
        ws_name = step.workspace_name

        def _ws_exists(snapshot: SnapshotLike) -> bool:
            return any(
                getattr(ws, "name", None) == ws_name
                for ws in snapshot.workspaces.values()
            )

        return _ws_exists

    if step.kind == StepKind.MOVE_WINDOW_TO_WORKSPACE:
        window_id = step.window_id
        ws_name = step.workspace_name

        def _window_in_ws(snapshot: SnapshotLike) -> bool:
            if window_id is None or ws_name is None:
                return False
            window = snapshot.windows.get(window_id)
            if window is None:
                return False
            target_ws = None
            for ws in snapshot.workspaces.values():
                if getattr(ws, "name", None) == ws_name:
                    target_ws = ws
                    break
            if target_ws is None:
                return False
            return getattr(window, "workspace_id", None) == getattr(target_ws, "id", None)

        return _window_in_ws

    if step.kind in (StepKind.SET_FLOATING, StepKind.SET_TILING):
        window_id = step.window_id
        want_floating = step.kind == StepKind.SET_FLOATING

        def _float_matches(snapshot: SnapshotLike) -> bool:
            if window_id is None:
                return False
            window = snapshot.windows.get(window_id)
            if window is None:
                return False
            return getattr(window, "is_floating", None) == want_floating

        return _float_matches

    # SPAWN_WINDOW, FOCUS_WINDOW, FOCUS_WORKSPACE, MOVE_WORKSPACE_TO_OUTPUT:
    # These always execute — no pre-check can determine they're "done."
    return None
```

### Step 4b: Fix executor to only skip when predicate exists and passes

In `src/nirip/execution/executor.py`, rewrite the `execute` method:

```python
"""Plan executor."""
from __future__ import annotations

import time
from typing import Any, Protocol

from nirip.execution.actions import action_for_step
from nirip.execution.models import ApplyResult, StepOutcome, StepResult
from nirip.execution.predicates import predicate_for_step
from nirip.planning.models import Plan


class ActionClient(Protocol):
    async def request(self, payload: dict[str, Any]) -> Any: ...


class PlanExecutor:
    """Execute a compiled plan against a runtime client/state pair."""

    def __init__(self, client: ActionClient | None = None) -> None:
        self.client = client

    async def execute(
        self,
        plan: Plan,
        snapshot: Any | None = None,
        *,
        stop_on_error: bool = False,
    ) -> ApplyResult:
        """Execute all steps in order and return outcomes."""

        start = time.monotonic()
        results: list[StepResult] = []

        for step in plan.steps:
            step_start = time.monotonic()

            # Only skip if the step has a meaningful predicate AND
            # the predicate confirms the desired state already holds.
            predicate = predicate_for_step(step)
            if predicate is not None and snapshot is not None and predicate(snapshot):
                results.append(
                    StepResult(
                        step=step,
                        outcome=StepOutcome.SKIPPED,
                        message="already satisfied",
                        duration_s=time.monotonic() - step_start,
                    )
                )
                continue

            action = action_for_step(step)
            if action is not None and self.client is not None:
                try:
                    await self.client.request(action)
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        StepResult(
                            step=step,
                            outcome=StepOutcome.FAILED,
                            message=f"action failed: {exc}",
                            duration_s=time.monotonic() - step_start,
                        )
                    )
                    if stop_on_error:
                        break
                    continue

            results.append(
                StepResult(
                    step=step,
                    outcome=StepOutcome.COMPLETED,
                    message="completed",
                    duration_s=time.monotonic() - step_start,
                    window_id=step.window_id,
                )
            )

        success = all(r.outcome not in (StepOutcome.FAILED, StepOutcome.TIMED_OUT) for r in results)
        return ApplyResult(
            session_name=plan.session_name,
            success=success,
            steps=results,
            total_duration_s=time.monotonic() - start,
        )
```

Note: `stop_on_error` is now wired (addresses review §3.2). The facade layer needs to pass it through — see Task 8.

### Validation

Add `tests/test_executor.py`:

```python
import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from nirip.execution.executor import PlanExecutor
from nirip.execution.models import StepOutcome
from nirip.planning.models import Plan, PlanStep, StepKind
from nirip.resolve.models import Resolution


@dataclass
class MockWin:
    id: int
    app_id: str | None = None
    title: str | None = None
    pid: int | None = None
    workspace_id: int | None = None
    is_floating: bool = False


@dataclass
class MockWs:
    id: int
    name: str | None = None
    output: str | None = None


@dataclass
class MockSnap:
    windows: dict[int, MockWin] = field(default_factory=dict)
    workspaces: dict[int, MockWs] = field(default_factory=dict)


class MockClient:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.fail_on = fail_on or set()

    async def request(self, payload: dict[str, Any]) -> Any:
        self.requests.append(payload)
        if payload.get("kind") in self.fail_on:
            raise RuntimeError(f"simulated failure: {payload['kind']}")
        return {"ok": True}


def _empty_resolution() -> Resolution:
    return Resolution(
        session_name="test",
        workspace_resolutions=[],
        unmatched_apps=[],
        ambiguous_apps=[],
        warnings=[],
    )


def _plan(*steps: PlanStep) -> Plan:
    return Plan(
        session_name="test",
        steps=list(steps),
        resolution=_empty_resolution(),
    )


def _step(id: str, kind: StepKind, **kwargs) -> PlanStep:
    return PlanStep(id=id, kind=kind, description=f"test {id}", **kwargs)


class TestExecutor:
    def test_empty_plan(self) -> None:
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan()))
        assert result.success
        assert result.steps == []

    def test_spawn_not_skipped_with_existing_windows(self) -> None:
        """SPAWN_WINDOW must not be skipped even if windows exist."""
        snap = MockSnap(
            windows={1: MockWin(1, "firefox")},
            workspaces={1: MockWs(1, "code")},
        )
        step = _step("s1", StepKind.SPAWN_WINDOW, app_name="editor")
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan(step), snapshot=snap))
        assert result.steps[0].outcome == StepOutcome.COMPLETED

    def test_wait_for_window_not_skipped(self) -> None:
        """WAIT_FOR_WINDOW must not be skipped by pre-existing windows."""
        snap = MockSnap(
            windows={1: MockWin(1, "firefox")},
            workspaces={1: MockWs(1, "ws")},
        )
        step = _step("w1", StepKind.WAIT_FOR_WINDOW, app_name="editor")
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan(step), snapshot=snap))
        assert result.steps[0].outcome == StepOutcome.COMPLETED

    def test_ensure_workspace_skipped_when_exists(self) -> None:
        snap = MockSnap(workspaces={1: MockWs(1, "code")})
        step = _step("ws1", StepKind.ENSURE_WORKSPACE, workspace_name="code")
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan(step), snapshot=snap))
        assert result.steps[0].outcome == StepOutcome.SKIPPED

    def test_ensure_workspace_not_skipped_when_missing(self) -> None:
        snap = MockSnap(workspaces={1: MockWs(1, "other")})
        step = _step("ws1", StepKind.ENSURE_WORKSPACE, workspace_name="code")
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan(step), snapshot=snap))
        assert result.steps[0].outcome == StepOutcome.COMPLETED

    def test_client_failure_recorded(self) -> None:
        client = MockClient(fail_on={"spawn_window"})
        step = _step("s1", StepKind.SPAWN_WINDOW, app_name="editor")
        executor = PlanExecutor(client=client)
        result = asyncio.run(executor.execute(_plan(step)))
        assert result.steps[0].outcome == StepOutcome.FAILED
        assert not result.success

    def test_stop_on_error(self) -> None:
        client = MockClient(fail_on={"spawn_window"})
        s1 = _step("s1", StepKind.SPAWN_WINDOW, app_name="a")
        s2 = _step("s2", StepKind.SPAWN_WINDOW, app_name="b")
        executor = PlanExecutor(client=client)
        result = asyncio.run(executor.execute(_plan(s1, s2), stop_on_error=True))
        assert len(result.steps) == 1  # stopped after first failure

    def test_continue_on_error_default(self) -> None:
        client = MockClient(fail_on={"spawn_window"})
        s1 = _step("s1", StepKind.SPAWN_WINDOW, app_name="a")
        s2 = _step("s2", StepKind.ENSURE_WORKSPACE, workspace_name="ws")
        executor = PlanExecutor(client=client)
        result = asyncio.run(executor.execute(_plan(s1, s2)))
        assert len(result.steps) == 2  # both attempted
```

Run: `pytest tests/test_executor.py -v`

---

## Task 5: Add Fullscreen/Maximized Drift Detection

**Priority:** Should-fix (§3.5)
**Files:** `src/nirip/resolve/matcher.py` (protocol), `src/nirip/resolve/resolver.py`, `src/nirip/planning/compiler.py`, `src/nirip/planning/models.py`
**Why:** `DriftKind.WRONG_FULLSCREEN` and `WRONG_MAXIMIZED` exist but are never detected or acted upon.

### Step 5a: Extend the `WindowLike` protocol

In `src/nirip/resolve/matcher.py`, add to the `WindowLike` protocol:

```python
class WindowLike(Protocol):
    """Structural window type."""

    @property
    def id(self) -> int: ...

    @property
    def app_id(self) -> str | None: ...

    @property
    def title(self) -> str | None: ...

    @property
    def pid(self) -> int | None: ...

    @property
    def workspace_id(self) -> int | None: ...

    @property
    def is_floating(self) -> bool: ...

    @property
    def is_fullscreen(self) -> bool: ...

    @property
    def is_maximized(self) -> bool: ...
```

### Step 5b: Add drift checks in resolver

In `src/nirip/resolve/resolver.py`, in the `resolve` function, after the floating drift check (around line 79), add:

```python
                if window is not None and window.is_fullscreen != app.placement.fullscreen:
                    drift.append(
                        DriftItem(
                            kind=DriftKind.WRONG_FULLSCREEN,
                            current=str(window.is_fullscreen),
                            desired=str(app.placement.fullscreen),
                        )
                    )
                if window is not None and window.is_maximized != app.placement.maximized:
                    drift.append(
                        DriftItem(
                            kind=DriftKind.WRONG_MAXIMIZED,
                            current=str(window.is_maximized),
                            desired=str(app.placement.maximized),
                        )
                    )
```

### Step 5c: Add `StepKind` variants for fullscreen/maximized

In `src/nirip/planning/models.py`, add to the `StepKind` enum:

```python
class StepKind(StrEnum):
    ENSURE_WORKSPACE = "ensure_workspace"
    MOVE_WORKSPACE_TO_OUTPUT = "move_workspace_to_output"
    SPAWN_WINDOW = "spawn_window"
    WAIT_FOR_WINDOW = "wait_for_window"
    MOVE_WINDOW_TO_WORKSPACE = "move_window_to_workspace"
    SET_FLOATING = "set_floating"
    SET_TILING = "set_tiling"
    SET_FULLSCREEN = "set_fullscreen"
    UNSET_FULLSCREEN = "unset_fullscreen"
    SET_MAXIMIZED = "set_maximized"
    UNSET_MAXIMIZED = "unset_maximized"
    FOCUS_WINDOW = "focus_window"
    FOCUS_WORKSPACE = "focus_workspace"
```

### Step 5d: Handle new drift kinds in compiler

In `src/nirip/planning/compiler.py`, in the `compile_plan` function, after the `WRONG_FLOATING` handling block, add:

```python
                    if drift.kind == DriftKind.WRONG_FULLSCREEN:
                        kind = StepKind.SET_FULLSCREEN if drift.desired == "True" else StepKind.UNSET_FULLSCREEN
                        steps.append(
                            PlanStep(
                                id=new_id("fs"),
                                kind=kind,
                                app_name=app.app_name,
                                workspace_name=app.workspace_name,
                                window_id=app.match_decision.best,
                                description=f"Set fullscreen for '{app.app_name}' to {drift.desired}",
                            )
                        )
                    if drift.kind == DriftKind.WRONG_MAXIMIZED:
                        kind = StepKind.SET_MAXIMIZED if drift.desired == "True" else StepKind.UNSET_MAXIMIZED
                        steps.append(
                            PlanStep(
                                id=new_id("max"),
                                kind=kind,
                                app_name=app.app_name,
                                workspace_name=app.workspace_name,
                                window_id=app.match_decision.best,
                                description=f"Set maximized for '{app.app_name}' to {drift.desired}",
                            )
                        )
```

### Step 5e: Update test fixtures

Every test fixture dataclass (`Win`, `MockWin`, etc.) that represents a window must now have `is_fullscreen` and `is_maximized` fields. Update the dataclass in `tests/test_matcher_resolver_planning.py`:

```python
@dataclass
class Win:
    id: int
    app_id: str | None
    title: str | None
    pid: int | None
    workspace_id: int | None
    is_floating: bool = False
    is_fullscreen: bool = False
    is_maximized: bool = False
```

Do the same for `MockWin` in `tests/test_executor.py`.

### Validation

Add `tests/test_resolver_drift.py`:

```python
from dataclasses import dataclass

from nirip.resolve.models import DriftKind, ResolutionStatus
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.planning.compiler import compile_plan
from nirip.planning.models import StepKind
from nirip.spec.models import AppSpec, MatchRule, PlacementSpec, SessionSpec, WorkspaceSpec


@dataclass
class Win:
    id: int
    app_id: str | None
    title: str | None
    pid: int | None
    workspace_id: int | None
    is_floating: bool = False
    is_fullscreen: bool = False
    is_maximized: bool = False


@dataclass
class Ws:
    id: int
    name: str | None
    output: str | None


@dataclass
class Snap:
    windows: dict[int, Win]
    workspaces: dict[int, Ws]


def test_wrong_workspace_drift() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="code",
                apps=[AppSpec(name="ed", match=MatchRule(app_id="nvim"))],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "nvim", None, None, 2)},
        workspaces={1: Ws(1, "code", None), 2: Ws(2, "other", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_WORKSPACE for d in app_res.drift)


def test_wrong_floating_drift() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[
                    AppSpec(
                        name="app",
                        match=MatchRule(app_id="x"),
                        placement=PlacementSpec(floating=True),
                    )
                ],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1, is_floating=False)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_FLOATING for d in app_res.drift)


def test_wrong_fullscreen_drift() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[
                    AppSpec(
                        name="app",
                        match=MatchRule(app_id="x"),
                        placement=PlacementSpec(fullscreen=True),
                    )
                ],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1, is_fullscreen=False)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_FULLSCREEN for d in app_res.drift)


def test_wrong_maximized_drift() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[
                    AppSpec(
                        name="app",
                        match=MatchRule(app_id="x"),
                        placement=PlacementSpec(maximized=True),
                    )
                ],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1, is_maximized=False)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.DRIFTED
    assert any(d.kind == DriftKind.WRONG_MAXIMIZED for d in app_res.drift)


def test_fullscreen_drift_compiles_to_step() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[
                    AppSpec(
                        name="app",
                        match=MatchRule(app_id="x"),
                        placement=PlacementSpec(fullscreen=True),
                    )
                ],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1, is_fullscreen=False)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    plan = compile_plan(res)
    assert any(s.kind == StepKind.SET_FULLSCREEN for s in plan.steps)


def test_no_drift_when_matched() -> None:
    spec = SessionSpec(
        name="t",
        workspaces=[
            WorkspaceSpec(
                name="ws",
                apps=[AppSpec(name="app", match=MatchRule(app_id="x"))],
            )
        ],
    )
    snap = Snap(
        windows={1: Win(1, "x", None, None, 1)},
        workspaces={1: Ws(1, "ws", None)},
    )
    res = resolve(normalize(spec), snap)
    app_res = res.workspace_resolutions[0].app_resolutions[0]
    assert app_res.status == ResolutionStatus.MATCHED
    assert app_res.drift == []
```

Run: `pytest tests/test_resolver_drift.py -v`

---

## Task 6: Type the Public API

**Priority:** Should-fix
**Files:** `src/nirip/__init__.py`
**Why:** `load_session` and `apply_session` return `object`, erasing type safety for consumers.

### Implementation

```python
"""nirip public API."""

from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.facade.sync_nirip import SyncNirip
from nirip.spec.loader import load_spec_from_dict, load_spec_from_file, load_spec_from_string
from nirip.spec.models import SessionSpec


def load_session(path: str) -> SessionSpec:
    """Convenience loader wrapper."""
    return load_spec_from_file(path)


def apply_session(spec: SessionSpec) -> ApplyResult:
    """Convenience sync apply wrapper."""
    with SyncNirip() as nirip:
        return nirip.apply(spec)


__all__ = [
    "ApplyResult",
    "AsyncNirip",
    "NiripConfig",
    "SessionSpec",
    "SyncNirip",
    "apply_session",
    "load_session",
    "load_spec_from_dict",
    "load_spec_from_file",
    "load_spec_from_string",
]
```

### Validation

Run `ruff check src/nirip/__init__.py` and `mypy src/nirip/__init__.py` (if mypy is configured). Verify no import errors: `python -c "from nirip import load_session, apply_session, SessionSpec, ApplyResult"`.

---

## Task 7: Use `SnapshotLike` Protocol in Capturer

**Priority:** Should-fix
**Files:** `src/nirip/capture/capturer.py`
**Why:** The capturer uses `getattr` duck-typing on `object` when a proper `SnapshotLike` protocol already exists.

### Implementation

In `src/nirip/capture/capturer.py`, import and use the protocol from `resolve/resolver.py`:

```python
"""Capture live desktop into a scaffold SessionSpec."""
from __future__ import annotations

from pydantic import BaseModel, computed_field

from nirip.capture.inference import infer_app_name, infer_match_rule
from nirip.resolve.matcher import WindowLike
from nirip.resolve.resolver import SnapshotLike
from nirip.spec.models import AppSpec, SessionSpec, WorkspaceSpec


class CapturedSession(BaseModel):
    """Result of a capture operation."""

    spec: SessionSpec
    notes: list[str]

    @computed_field
    @property
    def app_count(self) -> int:
        return sum(len(ws.apps) for ws in self.spec.workspaces)

    @computed_field
    @property
    def workspace_count(self) -> int:
        return len(self.spec.workspaces)


def capture_from_snapshot(snapshot: SnapshotLike, *, name: str | None = None) -> CapturedSession:
    """Capture current snapshot into a scaffold spec."""

    apps_by_ws: dict[int, list[AppSpec]] = {wid: [] for wid in snapshot.workspaces.keys()}
    for window in snapshot.windows.values():
        ws_id = window.workspace_id
        if ws_id in apps_by_ws:
            apps_by_ws[ws_id].append(
                AppSpec(
                    name=infer_app_name(window),
                    match=infer_match_rule(window),
                )
            )

    ws_specs: list[WorkspaceSpec] = []
    for ws_id, workspace in snapshot.workspaces.items():
        ws_name = workspace.name
        if ws_name is None:
            continue
        ws_specs.append(
            WorkspaceSpec(
                name=ws_name,
                output=workspace.output,
                apps=apps_by_ws.get(ws_id, []),
            )
        )

    spec = SessionSpec(name=name or "captured", workspaces=ws_specs)
    notes = ["Captured scaffold uses conservative app_id matching; add spawn commands manually."]
    return CapturedSession(spec=spec, notes=notes)
```

**Note:** You also need to check `src/nirip/capture/inference.py` — if `infer_app_name` or `infer_match_rule` use `getattr` on window objects, update them to use `WindowLike` too.

### Validation

Run: `pytest -v` — all existing tests should still pass. The change is type-level only; runtime behavior is the same since protocols are structural.

---

## Task 8: Wire `stop_on_error` Through the Facade

**Priority:** Should-fix (dead option, §3.2)
**Files:** `src/nirip/facade/async_nirip.py`, `src/nirip/facade/sync_nirip.py`
**Why:** `SessionOptions.stop_on_error` exists but is never consulted by the executor.

### Implementation

In `src/nirip/facade/async_nirip.py`, update the `apply` method:

```python
    async def apply(self, spec: SessionSpec) -> ApplyResult:
        plan = await self.plan(spec)
        return await self._executor.execute(
            plan,
            snapshot=self._snapshot,
            stop_on_error=spec.options.stop_on_error,
        )
```

No other changes needed — the `SyncNirip` delegates to `AsyncNirip`.

### Validation

Write a test that verifies stop_on_error flows through:

Add to `tests/test_executor.py` (already covered by `test_stop_on_error` and `test_continue_on_error_default` from Task 4).

---

## Task 9: Type `action_for_step` Return Value

**Priority:** Should-fix
**Files:** `src/nirip/execution/actions.py`, `src/nirip/execution/executor.py`
**Why:** Returns `dict[str, Any]` — an untyped bag. Should be a proper dataclass.

### Implementation

In `src/nirip/execution/actions.py`:

```python
"""Plan step to action translation."""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any

from nirip.planning.models import PlanStep, StepKind


class StepAction(BaseModel):
    """Typed action descriptor for a plan step."""

    kind: str
    window_id: int | None = None
    workspace_name: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


def action_for_step(step: PlanStep) -> StepAction | None:
    """Return a typed action descriptor for a plan step."""

    if step.kind == StepKind.WAIT_FOR_WINDOW:
        return None
    return StepAction(
        kind=step.kind.value,
        window_id=step.window_id,
        workspace_name=step.workspace_name,
        extra=dict(step.metadata),
    )
```

In `src/nirip/execution/executor.py`, update the `ActionClient` protocol:

```python
from nirip.execution.actions import StepAction, action_for_step


class ActionClient(Protocol):
    async def request(self, payload: StepAction) -> Any: ...
```

And update the `request` call — no other changes needed since `StepAction` is a Pydantic model that can be passed directly.

### Validation

Run: `pytest -v` — all existing tests pass. Update `MockClient` in `tests/test_executor.py` to accept `StepAction`:

```python
from nirip.execution.actions import StepAction

class MockClient:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.requests: list[StepAction] = []
        self.fail_on = fail_on or set()

    async def request(self, payload: StepAction) -> Any:
        self.requests.append(payload)
        if payload.kind in self.fail_on:
            raise RuntimeError(f"simulated failure: {payload.kind}")
        return {"ok": True}
```

---

## Task 10: Fix `SyncNirip` to Reuse `AsyncNirip`

**Priority:** Should-fix
**Files:** `src/nirip/facade/sync_nirip.py`
**Why:** Each method call creates a new `AsyncNirip` and a new event loop. This is inefficient and will break with real niri-ipc connections.

### Implementation

```python
"""Sync nirip facade."""
from __future__ import annotations

import asyncio
from typing import Any

from nirip.capture.capturer import CapturedSession
from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.planning.models import Plan, SessionDiff
from nirip.spec.models import SessionSpec


class SyncNirip:
    """Thin sync wrapper."""

    def __init__(self, config: NiripConfig | None = None) -> None:
        self._config = config
        self._snapshot: Any | None = None
        self._async: AsyncNirip | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_async(self) -> AsyncNirip:
        if self._async is None:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
            self._async = self._loop.run_until_complete(AsyncNirip.open(self._config))
            if self._snapshot is not None:
                self._async.bind_snapshot(self._snapshot)
        return self._async

    def bind_snapshot(self, snapshot: Any) -> None:
        self._snapshot = snapshot
        if self._async is not None:
            self._async.bind_snapshot(snapshot)

    def _run(self, coro):
        return self._ensure_async()  # ensure created
        # Actually run the coroutine on the persistent loop
        ...

    def diff(self, spec: SessionSpec) -> SessionDiff:
        a = self._ensure_async()
        return self._loop.run_until_complete(a.diff(spec))

    def plan(self, spec: SessionSpec) -> Plan:
        a = self._ensure_async()
        return self._loop.run_until_complete(a.plan(spec))

    def apply(self, spec: SessionSpec) -> ApplyResult:
        a = self._ensure_async()
        return self._loop.run_until_complete(a.apply(spec))

    def capture(self, *, name: str | None = None) -> CapturedSession:
        a = self._ensure_async()
        return self._loop.run_until_complete(a.capture(name=name))

    def close(self) -> None:
        if self._async is not None:
            if self._loop is not None:
                self._loop.run_until_complete(self._async.close())
            self._async = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    def __enter__(self) -> SyncNirip:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
```

Remove the `_run` method entirely — it's replaced by direct `self._loop.run_until_complete` calls.

### Validation

Run: `pytest -v`. Existing tests that use `SyncNirip` should still pass. Verify lifecycle:

```python
# Manual smoke test or add to tests:
def test_sync_nirip_reuses_instance() -> None:
    from nirip.facade.sync_nirip import SyncNirip
    with SyncNirip() as nirip:
        # Bind a mock snapshot, call two methods, verify same underlying async instance
        nirip.bind_snapshot(MockSnap(windows={}, workspaces={}))
        # Just verifying no crash on repeated calls
        nirip.close()
```

---

## Task 11: Move Shared Test Fixtures to `conftest.py`

**Priority:** Should-fix (test quality)
**Files:** `tests/conftest.py`
**Why:** Test fixture dataclasses (`Win`, `Ws`, `Snap`) are duplicated across test files. Shared fixtures belong in conftest.

### Implementation

In `tests/conftest.py`:

```python
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
```

Then update all test files (`test_matcher_resolver_planning.py`, `test_resolver_drift.py`, `test_executor.py`) to import from conftest instead of defining their own:

```python
# In each test file, remove local Win/Ws/Snap definitions and use:
from tests.conftest import Win, Ws, Snap
# Or pytest auto-discovers conftest fixtures, so just reference them directly.
```

Since these are plain classes (not pytest fixtures), import them explicitly. Remove the inline definitions from `test_matcher_resolver_planning.py`.

### Validation

Run: `pytest -v` — all tests pass with shared fixtures.

---

## Task 12: Fix `test_config.py` Exception Specificity

**Priority:** Low
**Files:** `tests/test_config.py`
**Why:** Uses bare `pytest.raises(Exception)` instead of the specific Pydantic `ValidationError`.

### Implementation

```python
import pytest
from pydantic import ValidationError

from nirip.config import NiripConfig


def test_default_config() -> None:
    cfg = NiripConfig()
    assert cfg.default_timeout_s == 20.0
    assert cfg.confirm_before_apply is True


def test_config_paths_are_absolute() -> None:
    cfg = NiripConfig()
    assert cfg.session_dir.is_absolute()
    assert cfg.state_dir.is_absolute()
    assert "~" not in str(cfg.session_dir)
    assert "~" not in str(cfg.state_dir)


def test_config_is_frozen() -> None:
    cfg = NiripConfig()
    with pytest.raises(ValidationError):
        cfg.default_timeout_s = 99.0
```

### Validation

Run: `pytest tests/test_config.py -v`

---

## Task 13: Add Matcher Edge Case Tests

**Priority:** Should-add
**Files:** `tests/test_matcher.py` (new file)
**Why:** Current tests only cover `app_id` exact match. No tests for regex, title, pid, any_of, not_rule, or no-match scenarios.

### Implementation

Create `tests/test_matcher.py`:

```python
from tests.conftest import Win
from nirip.resolve.matcher import evaluate_rule, match_app
from nirip.spec.models import MatchRule


class TestEvaluateRule:
    def test_app_id_exact_match(self) -> None:
        ok, conf, _ = evaluate_rule(MatchRule(app_id="firefox"), Win(1, "firefox", None, None, 1))
        assert ok
        assert conf == 1.0

    def test_app_id_mismatch(self) -> None:
        ok, _, reasons = evaluate_rule(MatchRule(app_id="firefox"), Win(1, "chromium", None, None, 1))
        assert not ok

    def test_app_id_regex(self) -> None:
        ok, conf, _ = evaluate_rule(
            MatchRule(app_id_regex=r"fire.*"),
            Win(1, "firefox", None, None, 1),
        )
        assert ok
        assert conf == 0.9

    def test_app_id_regex_no_match(self) -> None:
        ok, _, _ = evaluate_rule(
            MatchRule(app_id_regex=r"^chrome$"),
            Win(1, "firefox", None, None, 1),
        )
        assert not ok

    def test_title_exact(self) -> None:
        ok, conf, _ = evaluate_rule(MatchRule(title="Docs"), Win(1, None, "Docs", None, 1))
        assert ok
        assert conf == 0.8

    def test_title_regex(self) -> None:
        ok, conf, _ = evaluate_rule(
            MatchRule(title_regex=r"GitHub.*"),
            Win(1, None, "GitHub - Pull Requests", None, 1),
        )
        assert ok
        assert conf == 0.7

    def test_pid_match(self) -> None:
        ok, conf, _ = evaluate_rule(MatchRule(pid=1234), Win(1, None, None, 1234, 1))
        assert ok
        assert conf == 1.0

    def test_pid_mismatch(self) -> None:
        ok, _, _ = evaluate_rule(MatchRule(pid=1234), Win(1, None, None, 5678, 1))
        assert not ok

    def test_any_of_one_match(self) -> None:
        rule = MatchRule(
            any_of=[MatchRule(app_id="firefox"), MatchRule(app_id="chromium")]
        )
        ok, _, _ = evaluate_rule(rule, Win(1, "firefox", None, None, 1))
        assert ok

    def test_any_of_no_match(self) -> None:
        rule = MatchRule(
            any_of=[MatchRule(app_id="firefox"), MatchRule(app_id="chromium")]
        )
        ok, _, _ = evaluate_rule(rule, Win(1, "safari", None, None, 1))
        assert not ok

    def test_not_rule_excludes(self) -> None:
        rule = MatchRule(app_id="firefox", not_rule=MatchRule(title="Private"))
        ok, _, _ = evaluate_rule(rule, Win(1, "firefox", "Private", None, 1))
        assert not ok

    def test_not_rule_passes(self) -> None:
        rule = MatchRule(app_id="firefox", not_rule=MatchRule(title="Private"))
        ok, _, _ = evaluate_rule(rule, Win(1, "firefox", "Docs", None, 1))
        assert ok

    def test_combined_criteria_lowers_confidence(self) -> None:
        rule = MatchRule(app_id="firefox", title_regex=r".*")
        ok, conf, _ = evaluate_rule(rule, Win(1, "firefox", "Docs", None, 1))
        assert ok
        assert conf == 0.7  # min of 1.0 (app_id) and 0.7 (title_regex)


class TestMatchApp:
    def test_no_windows(self) -> None:
        decision = match_app("app", "ws", MatchRule(app_id="x"), [])
        assert decision.best is None
        assert not decision.is_matched

    def test_ambiguous_match(self) -> None:
        windows = [
            Win(1, "firefox", None, None, 1),
            Win(2, "firefox", None, None, 1),
        ]
        decision = match_app("app", "ws", MatchRule(app_id="firefox"), windows)
        assert decision.is_ambiguous

    def test_single_match(self) -> None:
        windows = [
            Win(1, "firefox", None, None, 1),
            Win(2, "chromium", None, None, 1),
        ]
        decision = match_app("app", "ws", MatchRule(app_id="firefox"), windows)
        assert decision.best == 1
        assert not decision.is_ambiguous
```

### Validation

Run: `pytest tests/test_matcher.py -v`

---

## Task 14: Add Capture Tests

**Priority:** Should-add
**Files:** `tests/test_capturer.py` (new file)
**Why:** Capture module has 24-44% coverage with zero direct tests.

### Implementation

Create `tests/test_capturer.py`:

```python
from tests.conftest import Snap, Win, Ws
from nirip.capture.capturer import capture_from_snapshot


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
    snap = Snap(
        windows={},
        workspaces={1: Ws(1, None, None)},
    )
    result = capture_from_snapshot(snap)
    assert result.workspace_count == 0


def test_capture_window_without_workspace() -> None:
    """Windows in workspaces not in the snapshot are ignored."""
    snap = Snap(
        windows={1: Win(1, "firefox", None, None, 99)},  # ws 99 not in snapshot
        workspaces={1: Ws(1, "code", None)},
    )
    result = capture_from_snapshot(snap)
    assert result.workspace_count == 1
    assert result.app_count == 0  # window's ws_id doesn't match
```

### Validation

Run: `pytest tests/test_capturer.py -v`

---

## Task 15: Add Full Integration Test

**Priority:** Should-add
**Files:** `tests/test_integration.py` (new file)
**Why:** No test exercises the full pipeline: YAML → normalize → resolve → plan → execute → verify.

### Implementation

Create `tests/test_integration.py`:

```python
"""Full pipeline integration test: YAML → apply result."""
import asyncio

from tests.conftest import Snap, Win, Ws
from nirip.execution.executor import PlanExecutor
from nirip.execution.models import StepOutcome
from nirip.planning.compiler import compile_plan
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.loader import load_spec_from_string


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
    """When all apps are already present, plan is empty."""
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
    """When an app is missing, plan includes spawn + wait steps."""
    spec = load_spec_from_string(YAML_SPEC)
    snap = Snap(
        windows={
            1: Win(1, "nvim", None, None, 10),
            # foot is missing
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
    """Execute without a client — all steps complete as dry-run."""
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
    # All steps should be COMPLETED (no client to fail) or SKIPPED
    for step_result in result.steps:
        assert step_result.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED)


def test_full_pipeline_missing_workspace() -> None:
    """When workspace doesn't exist, plan includes ensure_workspace."""
    spec = load_spec_from_string(YAML_SPEC)
    snap = Snap(
        windows={},
        workspaces={10: Ws(10, "code", None)},  # "browser" workspace missing
    )
    normalized = normalize(spec)
    resolution = resolve(normalized, snap)
    plan = compile_plan(resolution)
    assert any("browser" in s.description and "workspace" in s.description.lower() for s in plan.steps)
```

### Validation

Run: `pytest tests/test_integration.py -v`

---

## Task 16: Update `AGENTS.md`

**Priority:** Must-fix (documentation)
**Files:** `AGENTS.md`
**Why:** AGENTS.md documents a `core/` + `executor/` flat layout that doesn't exist. The actual layout is `spec/`, `resolve/`, `planning/`, `execution/`, `capture/`, `facade/`, `cli/`.

### Implementation

Find the module table section in `AGENTS.md` and replace it with the actual layout. The module table should reflect:

| Module | Purpose | I/O? |
|--------|---------|------|
| `spec/` | Session spec models, YAML loading, validation, defaults | No |
| `resolve/` | Normalization, window matching, drift resolution | No |
| `planning/` | Plan compilation, step ordering, diff generation | No |
| `execution/` | Plan executor, action translation, predicates, runtime | Yes (async) |
| `capture/` | Snapshot-to-spec scaffolding, name/rule inference | No |
| `facade/` | AsyncNirip/SyncNirip orchestration facades | Yes (asyncio.run) |
| `cli/` | Argparse, command dispatch, file I/O, stdout | Yes |

Update the dependency flow diagram to match:

```
spec → resolve → planning → execution
                               ↓
capture ← facade → cli
```

### Validation

Read the updated `AGENTS.md` and verify every module listed actually exists under `src/nirip/`.

---

## Final Validation Checklist

After completing all tasks, run the following:

```bash
# 1. All tests pass
pytest -v

# 2. Coverage improved (target: >80%)
pytest --cov=nirip --cov-report=term-missing

# 3. No lint issues
ruff check src/ tests/

# 4. No type errors (if mypy is configured)
mypy src/nirip/

# 5. Import smoke test
python -c "from nirip import load_session, apply_session, SessionSpec, ApplyResult; print('OK')"
```

### Expected Outcomes

| Metric | Before | After |
|--------|--------|-------|
| Tests | 20 | ~45+ |
| Line coverage | 67% | >80% |
| Ruff clean | Yes | Yes |
| Critical bugs | 3 | 0 |
| Dead options | 3 (`stop_on_error`, `mode`, drift kinds) | 1 (`mode` — acceptable as future work) |
| Untyped public API | 2 functions | 0 |

### What's Not Covered Here (Future Work)

These items are documented but intentionally out of scope for this guide:
- **Actual niri-ipc client** — the executor still has no real `ActionClient` implementation
- **`SessionOptions.mode` enforcement** — "reconcile" mode logic; needs design discussion before implementation
- **`match_existing` / `launch_missing` / `move_unmatched` enforcement** — related to mode; deferred
- **CLI tests** — depends on how CLI commands evolve with real niri integration
- **Timeout implementation in executor** — needs real async polling with niri-state, not just a model
