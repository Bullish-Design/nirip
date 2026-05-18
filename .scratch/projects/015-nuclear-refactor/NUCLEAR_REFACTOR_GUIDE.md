# Nuclear Refactor: Implementation Guide

**Goal:** Rewrite nirip from 41 files / 2,316 LOC to 7 files / ~1,500 LOC with zero functionality loss.

**Strategy:** Write v2 from scratch. No incremental migration. Delete old code, write new code, port tests.

---

## Current State (v1)

```
41 files, 2,316 LOC source + 988 LOC tests (22 test files)

src/nirip/
├── _base.py              (18)   ← NiripModel base class
├── config.py             (14)   ← NiripConfig (dead code)
├── errors.py             (43)   ← 7 exception classes
├── __init__.py           (63)   ← Public API + sync wrappers
├── __main__.py            (3)   ← CLI entry
├── spec/                        ← 4 files, 312 LOC
│   ├── __init__.py       (15)
│   ├── models.py         (93)
│   ├── loader.py         (44)
│   └── validators.py    (160)
├── resolve/                     ← 5 files, 448 LOC
│   ├── __init__.py        (7)
│   ├── models.py        (144)
│   ├── matcher.py       (139)
│   ├── assigner.py       (36)
│   └── resolver.py      (122)
├── planning/                    ← 5 files, 573 LOC
│   ├── __init__.py        (7)
│   ├── models.py        (157)
│   ├── builder.py       (258)
│   ├── compiler.py      (109)
│   └── ordering.py       (42)
├── execution/                   ← 7 files, 459 LOC
│   ├── __init__.py       (15)
│   ├── models.py         (59)
│   ├── hooks.py          (43)
│   ├── executor.py       (72)
│   ├── handlers.py      (221)
│   ├── runtime.py        (28)
│   ├── predicates.py     (36)
│   └── _checks.py        (15)
├── capture/                     ← 3 files, 73 LOC
│   ├── __init__.py        (5)
│   ├── capturer.py       (45)
│   └── inference.py      (23)
├── facade/                      ← 2 files, 82 LOC
│   ├── __init__.py        (5)
│   └── async_nirip.py    (77)
└── cli/                         ← 4 files, 198 LOC
    ├── __init__.py        (5)
    ├── main.py           (66)
    ├── commands.py       (66)
    └── formatting.py     (61)
```

## Target State (v2)

```
7 files, ~1,500 LOC source

src/nirip/
├── __init__.py      (~60 LOC)   Public API
├── spec.py         (~300 LOC)   Models + validation + YAML loading
├── resolve.py      (~300 LOC)   Matching + assignment + drift + resolution
├── plan.py         (~350 LOC)   Step generation + ordering
├── execute.py      (~300 LOC)   Async execution engine + hooks
├── capture.py       (~70 LOC)   Snapshot → spec template
└── cli.py          (~180 LOC)   Argparse + commands + formatting
```

Plus:
```
├── __main__.py        (3 LOC)   Unchanged
```

---

## What Gets Deleted (and why)

| Item | LOC | Why |
|------|-----|-----|
| `_base.py` (NiripModel) | 18 | `_FROZEN = ConfigDict(...)` module constant replaces it |
| `config.py` (NiripConfig) | 14 | Dead code — no field is ever read by any consumer |
| `errors.py` (5 of 7 classes) | 30 | Keep `NiripError` + `ValidationError` only; `SpecError`→`NiripError`, `PlanningError`→`NiripError`, `CycleError`→`NiripError(msg)`, `CaptureError` unused, `NiripConnectionError` unused |
| `WindowAssigner` protocol | 10 | One implementation, never swapped — inline the 15 lines |
| `GreedyAssigner` class | 36 | Becomes `_assign()` function in resolve.py |
| `MatchCandidate` model | 4 | Replaced by `(window_id, tier)` tuples in local scope |
| `MatchDecision` model | 20 | Fields absorbed into `AppResolution.window_id` + `.is_ambiguous` |
| `WorkspaceResolution` container | 8 | `Resolution.apps` becomes flat list; workspace facts in `WorkspaceState` |
| `SessionDiff` model | 26 | Formatting produces strings directly from Resolution |
| `CapturedSession` wrapper | 14 | `capture()` returns `SessionSpec` directly |
| `ValidatedSpec` wrapper | 4 | Return `tuple[SessionSpec, ValidationResult]` |
| `AsyncNirip` facade | 77 | CLI commands inline the try/finally lifecycle |
| 12 `__init__.py` re-exports | ~80 | No subpackages = no re-exports |
| `computed_field` decorators | ~40 | Replace with `@property` or inline calls |
| `compile_diff()` function | 28 | Logic moves to CLI `format_resolution()` |
| `SessionRuntime` + `AppRuntimeState` | 28 | Replaced by `dict[str, _AppState]` dataclass |
| `predicates.py` + `_checks.py` | 51 | Inlined as `_is_satisfied()` + `_STATE_CHECKS` dict |
| 9 PlanStep subclasses | ~80 | Single `PlanStep` + `StepKind` enum |
| `PlanBuilder` class | 258 | `build_plan()` function with `emit()` closure |
| `reasons` tracking in matcher | ~20 | Debug info never surfaced to users |

**Total deleted:** ~800+ lines of boilerplate/indirection.

---

## Implementation Steps

### Step 0: Preparation

**Branch and backup:**  (**COMPLETE**)
```bash
git checkout -b nuclear-refactor
# The old code stays on main — no risk
```

**Verify current tests pass:**  (**COMPLETE**)
```bash
uv run pytest
```

### Step 1: Write `src/nirip/spec.py` (~300 LOC)

A spec is a declarative description of what your desktop session should look like — which apps should be running, on which workspaces, in what arrangement.

This is the foundation — everything else depends on it.

**Source files being replaced:**
- `spec/models.py` (93 LOC) — copy models verbatim, replace `NiripModel` with local `_FROZEN`
- `spec/validators.py` (160 LOC) — copy all `_check_*` functions verbatim
- `spec/loader.py` (44 LOC) — copy loading functions, change error types
- `errors.py` (partial) — only `NiripError` + `ValidationError` survive

**Write this file with these sections:**

```python
"""Session specification: models, validation, and YAML loading."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Errors ──────────────────────────────────────────────────────────────────

class NiripError(Exception):
    """Base for all nirip errors."""

class ValidationError(NiripError):
    """Spec validation failed."""
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__(f"{len(errors)} error(s): {'; '.join(errors[:3])}")


# ─── Models ──────────────────────────────────────────────────────────────────

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class MatchRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    # ... (exact same fields as spec/models.py MatchRule)

class SpawnSpec(BaseModel):
    model_config = _FROZEN
    # ... (exact copy)

class PlacementSpec(BaseModel):
    model_config = _FROZEN
    # ... (exact copy including _validate_mutual_exclusion)

class AppSpec(BaseModel):
    model_config = _FROZEN
    # ... (exact copy)

class WorkspaceSpec(BaseModel):
    model_config = _FROZEN
    # ... (exact copy)

class SessionOptions(BaseModel):
    model_config = _FROZEN
    # ... (exact copy)

class SessionSpec(BaseModel):
    model_config = _FROZEN
    # ... (exact copy)


# ─── Validation ──────────────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    model_config = _FROZEN
    valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_session(spec: SessionSpec) -> ValidationResult:
    # ... (exact copy from validators.py, all 7 _check_* functions)


# ─── Loading ─────────────────────────────────────────────────────────────────

def load_from_file(path: str | Path) -> tuple[SessionSpec, ValidationResult]:
    # ... (adapted from loader.py, raises NiripError instead of SpecError)

def load_from_string(text: str, *, source: str = "<string>") -> tuple[SessionSpec, ValidationResult]:
    # ... (adapted)

def load_from_dict(data: dict[str, Any], *, source: str = "<dict>") -> tuple[SessionSpec, ValidationResult]:
    # ... (adapted, raises ValidationError on failure)
```

**Key changes from v1:**
1. Replace `NiripModel` base → `BaseModel` + `_FROZEN` config on each model
2. `SpecError` → `NiripError` (same usage, fewer types)
3. `SpecValidationError` → `ValidationError` (defined in this file, near its raise site)
4. `ValidatedSpec` wrapper deleted → return `tuple[SessionSpec, ValidationResult]`
5. All 7 `_check_*` functions copied verbatim (they're correct, just consolidating files)

**Exact copy sections (no logic changes):**
- All model classes from `spec/models.py` lines 10-93
- All validator functions from `spec/validators.py` lines 42-161
- Loading pipeline from `spec/loader.py` lines 15-44

**Changed signatures:**
```python
# OLD: load_spec_from_file(path) -> ValidatedSpec
# NEW: load_from_file(path) -> tuple[SessionSpec, ValidationResult]

# OLD: load_spec_from_string(text, source=) -> ValidatedSpec
# NEW: load_from_string(text, source=) -> tuple[SessionSpec, ValidationResult]

# OLD: load_spec_from_dict(data, source=) -> ValidatedSpec
# NEW: load_from_dict(data, source=) -> tuple[SessionSpec, ValidationResult]
```

---

### Step 2: Write `src/nirip/resolve.py` (~300 LOC)

**Source files being replaced:**
- `resolve/models.py` (144 LOC) — models simplified
- `resolve/matcher.py` (139 LOC) — `evaluate_rule` + assignment logic
- `resolve/assigner.py` (36 LOC) — inlined into `_assign()`
- `resolve/resolver.py` (122 LOC) — `resolve()` + `_detect_drift()`

**Write this file with these sections:**

```python
"""Window matching, assignment, and resolution against live state."""
from __future__ import annotations

import re
from collections.abc import Iterable
from enum import IntEnum, StrEnum
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field
from niri_pypc.types.generated.models import Window, Workspace
from niri_state import Snapshot

from nirip.spec import AppSpec, MatchRule, SessionSpec

_FROZEN = ConfigDict(extra="forbid", frozen=True)


# ─── Types ───────────────────────────────────────────────────────────────────

class MatchTier(IntEnum):
    NONE = 0; WEAK = 1; MODERATE = 2; STRONG = 3; EXACT = 4

class DriftKind(StrEnum):
    WRONG_WORKSPACE = "wrong_workspace"
    WRONG_FLOATING = "wrong_floating"
    WRONG_FULLSCREEN = "wrong_fullscreen"
    WRONG_MAXIMIZED = "wrong_maximized"

class DriftItem(BaseModel):
    model_config = _FROZEN
    kind: DriftKind
    current: str
    desired: str

class ResolutionStatus(StrEnum):
    MATCHED = "matched"
    DRIFTED = "drifted"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    OPTIONAL_MISSING = "optional_missing"

class AppResolution(BaseModel):
    model_config = _FROZEN
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    window_id: int | None = None          # was in MatchDecision
    is_ambiguous: bool = False            # was computed_field on MatchDecision
    drift: list[DriftItem]
    spec: AppSpec
    startup_timeout_s: float

    @property
    def needs_move(self) -> bool:
        return any(d.kind == DriftKind.WRONG_WORKSPACE for d in self.drift)

class WorkspaceState(BaseModel):
    model_config = _FROZEN
    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    focus: bool

class Resolution(BaseModel):
    model_config = _FROZEN
    session_name: str
    workspaces: list[WorkspaceState]
    apps: list[AppResolution]             # FLAT — not nested in workspace containers
    warnings: list[str] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        if any(not ws.exists or not ws.output_correct for ws in self.workspaces):
            return True
        return any(ar.status in (ResolutionStatus.DRIFTED, ResolutionStatus.MISSING) for ar in self.apps)

    @property
    def fully_converged(self) -> bool:
        return not self.has_drift and not any(ar.status == ResolutionStatus.AMBIGUOUS for ar in self.apps)

    def apps_in(self, workspace_name: str) -> list[AppResolution]:
        return [ar for ar in self.apps if ar.workspace_name == workspace_name]


# ─── Rule Evaluation ─────────────────────────────────────────────────────────

@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)

def evaluate_rule(rule: MatchRule, window: Window) -> tuple[bool, MatchTier]:
    # ... (simplified from matcher.py — drop `reasons` list)

# ─── Assignment ──────────────────────────────────────────────────────────────

def _assign(
    apps: list[tuple[str, AppSpec]],
    windows: Iterable[Window],
) -> list[tuple[int | None, bool]]:
    # ... (inlined GreedyAssigner + ambiguity detection)

# ─── Resolution ──────────────────────────────────────────────────────────────

def resolve(spec: SessionSpec, snapshot: Snapshot) -> Resolution:
    # ... (adapted from resolver.py — flat apps list, no WorkspaceResolution)

def _detect_drift(window, app_spec, ws_name, ws_by_name) -> list[DriftItem]:
    # ... (exact copy from resolver.py)
```

**Key changes from v1:**

1. **`evaluate_rule` return type:** `tuple[bool, MatchTier, list[str]]` → `tuple[bool, MatchTier]`
   - The `reasons` list was never surfaced to users — pure dead weight
   - Remove all `reasons.append(...)` lines from the function body

2. **`MatchDecision` deleted:** Its fields split into `AppResolution`:
   - `MatchDecision.assigned_window_id` → `AppResolution.window_id`
   - `MatchDecision.is_ambiguous` (computed) → `AppResolution.is_ambiguous` (plain bool)
   - `MatchDecision.candidates`, `.tier`, `.reasons` → deleted (debug-only)

3. **`MatchCandidate` deleted:** `_assign()` uses `(window_id, tier)` tuples internally

4. **`WindowAssigner` protocol + `GreedyAssigner` class → `_assign()` function:**
   - Same algorithm, just not wrapped in a class
   - Returns `list[tuple[int | None, bool]]` (window_id, is_ambiguous) per app

5. **`WorkspaceResolution` container deleted → `WorkspaceState` + flat `Resolution.apps`:**
   - `Resolution.workspace_resolutions` → `Resolution.workspaces` (just facts)
   - `Resolution.apps` is a flat list of all `AppResolution`s
   - Helper: `Resolution.apps_in(ws_name)` replaces manual nested iteration
   - `computed_field` → `@property` for `has_drift`, `fully_converged`
   - Delete `all_app_resolutions`, `unmatched_apps`, `ambiguous_apps` computed fields

6. **`resolve()` builds flat structure:**
   - Two passes: first build `WorkspaceState` list, then build flat `AppResolution` list
   - Uses `_assign()` instead of `assign_windows()` + `MatchDecision` construction

**Exact copy sections:**
- `MatchTier`, `DriftKind`, `DriftItem`, `ResolutionStatus` enums (verbatim)
- `_compile()` regex cache (verbatim)
- `_detect_drift()` function body (verbatim from resolver.py:98-122)
- `_PROPERTY_CHECKS` table (verbatim from resolver.py:91-95)

---

### Step 3: Write `src/nirip/plan.py` (~350 LOC)

**Source files being replaced:**
- `planning/models.py` (157 LOC) — 9 step classes → 1 PlanStep + enums
- `planning/builder.py` (258 LOC) — PlanBuilder class → build_plan() function
- `planning/compiler.py` (109 LOC) — compile_plan, compile_diff, parse_size
- `planning/ordering.py` (42 LOC) — topological_sort

**Write this file with these sections:**

```python
"""Plan step generation and ordering."""
from __future__ import annotations

from collections import defaultdict, deque
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from nirip.resolve import AppResolution, DriftKind, Resolution, ResolutionStatus, WorkspaceState
from nirip.spec import MatchRule, NiripError, SessionOptions

_FROZEN = ConfigDict(extra="forbid", frozen=True)


# ─── Types ───────────────────────────────────────────────────────────────────

class StepKind(StrEnum):
    CREATE_WORKSPACE = "create_workspace"
    MOVE_WORKSPACE_TO_OUTPUT = "move_workspace_to_output"
    SPAWN_WINDOW = "spawn_window"
    WAIT_FOR_WINDOW = "wait_for_window"
    MOVE_WINDOW = "move_window"
    SET_STATE = "set_state"
    RESIZE = "resize"
    FOCUS_WINDOW = "focus_window"
    FOCUS_WORKSPACE = "focus_workspace"

class WindowProperty(StrEnum):
    FLOATING = "floating"
    TILING = "tiling"
    FULLSCREEN = "fullscreen"
    MAXIMIZED = "maximized"

class ResizeAxis(StrEnum):
    WIDTH = "width"
    HEIGHT = "height"

class PlanStep(BaseModel):
    """Single execution step. Fields are sparse — only relevant ones populated per kind."""
    model_config = _FROZEN
    id: str
    kind: StepKind
    description: str
    depends_on: list[str] = Field(default_factory=list)
    # Context
    app_name: str | None = None
    workspace_name: str | None = None
    window_id: int | None = None
    # Spawn
    command: list[str] | str | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False
    # Wait
    match: MatchRule | None = None
    timeout_s: float | None = None
    # Workspace
    target_output: str | None = None
    # State
    property: WindowProperty | None = None
    value: bool = True
    # Resize
    axis: ResizeAxis | None = None
    proportion: float | None = None
    pixels: int | None = None

class Plan(BaseModel):
    model_config = _FROZEN
    session_name: str
    steps: list[PlanStep]
    resolution: Resolution

    @property
    def is_empty(self) -> bool:
        return not self.steps


# ─── Plan Building ───────────────────────────────────────────────────────────

def build_plan(resolution: Resolution, options: SessionOptions) -> Plan:
    # ... (see NUCLEAR_REFACTOR_CONCEPT.md for full implementation)

def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
    # ... (exact copy from compiler.py)

def _workspace_steps(ws: WorkspaceState, emit) -> list[str]:
    # ... (adapted from builder.ensure_workspace)

def _spawn_steps(ar: AppResolution, ws_name: str, base_deps: list[str], emit) -> list[str]:
    # ... (adapted from builder.spawn_app)

def _placement_steps(ar: AppResolution, ws_name: str, deps: list[str], emit) -> None:
    # ... (adapted from builder.place_window — uses data-driven _STATE_DRIFT_MAP)

def _wire_dependencies(steps, app_first, app_last, resolution) -> None:
    # ... (adapted from builder.wire_app_dependencies)

def _parse_size(value: float | str) -> tuple[float | None, int | None]:
    # ... (exact copy from compiler.py, raises NiripError instead of PlanningError)


# ─── Topological Sort ────────────────────────────────────────────────────────

def _topological_sort(steps: list[PlanStep]) -> list[PlanStep]:
    # ... (exact copy from ordering.py, raises NiripError instead of CycleError)
```

**Key changes from v1:**

1. **9 step classes → 1 `PlanStep` with `StepKind` enum:**
   - `CreateWorkspaceStep`, `MoveWorkspaceToOutputStep`, `SpawnWindowStep`, etc. all become one `PlanStep`
   - Fields are sparse: each step kind only populates the relevant fields
   - `StepKind` values simplified: `"move_window_to_workspace"` → `"move_window"`, `"set_window_state"` → `"set_state"`, `"resize_window"` → `"resize"`
   - `ResizeWindowStep._exactly_one_size` validator deleted (caller ensures correctness)
   - The discriminated union `PlanStep = Annotated[..., Discriminator("kind")]` is replaced by a single class

2. **`PlanBuilder` class → `build_plan()` function with `emit()` closure:**
   - `PlanBuilder.__init__`, `_next_id`, `_track` → `emit()` closure in `build_plan()`
   - `PlanBuilder.ensure_workspace()` → `_workspace_steps()`
   - `PlanBuilder.spawn_app()` → `_spawn_steps()`
   - `PlanBuilder.place_window()` → `_placement_steps()`
   - `PlanBuilder.focus_workspace()` → inline in `build_plan()` loop
   - `PlanBuilder.wire_app_dependencies()` → `_wire_dependencies()`
   - `PlanBuilder.build()` → `_topological_sort()` called directly

3. **`_emit_state_steps` repetition → data-driven `_STATE_DRIFT_MAP` table:**
   - Three nearly-identical if/emit blocks become a loop over a 3-row table
   - `_STATE_DRIFT_MAP = [(DriftKind.WRONG_FLOATING, "floating", WindowProperty.FLOATING, WindowProperty.TILING), ...]`

4. **`compile_plan()` + `PlanBuilder.build()` → single `build_plan()` function:**
   - The two-step pattern `builder = PlanBuilder(); ... ; Plan(steps=builder.build())` becomes one function

5. **`compile_diff()` deleted entirely:**
   - Formatting logic moves to `format_resolution()` in cli.py
   - `SessionDiff` model deleted — it was just a data shuttle between resolution and CLI

6. **`CycleError` → `NiripError` with message:**
   - `CycleError(cycle_ids)` → `NiripError(f"dependency cycle among steps: {cycle_ids}")`

7. **`Plan.requires_spawn`, `Plan.step_count` computed fields deleted:**
   - `is_empty` remains as `@property` instead of `computed_field`

**Exact copy sections:**
- `_should_act()` match logic (verbatim from compiler.py:20-34)
- `_parse_size()` body (verbatim from compiler.py:64-78, just rename error type)
- `_topological_sort()` body (verbatim from ordering.py:10-42, just rename error)

**The `emit()` pattern:**
```python
def build_plan(resolution: Resolution, options: SessionOptions) -> Plan:
    steps: list[PlanStep] = []
    counter = 0
    app_first: dict[str, str] = {}
    app_last: dict[str, str] = {}

    def emit(kind: StepKind, description: str, **kwargs) -> str:
        nonlocal counter
        counter += 1
        sid = f"{kind.value}-{counter}"
        step = PlanStep(id=sid, kind=kind, description=description, **kwargs)
        steps.append(step)
        key = f"{step.workspace_name}/{step.app_name}" if step.app_name and step.workspace_name else None
        if key:
            if key not in app_first:
                app_first[key] = sid
            app_last[key] = sid
        return sid

    # Phase 1: workspace setup + app steps
    for ws in resolution.workspaces:
        base_deps = _workspace_steps(ws, emit)
        for ar in resolution.apps_in(ws.name):
            if not _should_act(ar, options):
                continue
            placement_deps = list(base_deps)
            if ar.status == ResolutionStatus.MISSING and ar.spec.spawn:
                placement_deps = _spawn_steps(ar, ws.name, base_deps, emit)
            _placement_steps(ar, ws.name, placement_deps, emit)

    # Phase 2: workspace focus (always last)
    for ws in resolution.workspaces:
        if ws.focus:
            emit(StepKind.FOCUS_WORKSPACE, f"focus workspace '{ws.name}'", workspace_name=ws.name)

    # Phase 3: wire inter-app depends_on
    _wire_dependencies(steps, app_first, app_last, resolution)

    return Plan(
        session_name=resolution.session_name,
        steps=_topological_sort(steps),
        resolution=resolution,
    )
```

---

### Step 4: Write `src/nirip/execute.py` (~300 LOC)

**Source files being replaced:**
- `execution/models.py` (59 LOC) — StepOutcome, StepResult, ApplyResult, SessionPorts
- `execution/hooks.py` (43 LOC) — ExecutionHook protocol, NullHook, LoggingHook
- `execution/executor.py` (72 LOC) — execute_plan + _init_runtime
- `execution/handlers.py` (221 LOC) — execute_step + all handlers
- `execution/runtime.py` (28 LOC) — SessionRuntime, AppRuntimeState
- `execution/predicates.py` (36 LOC) — is_already_satisfied
- `execution/_checks.py` (15 LOC) — STATE_CHECKS dict

**Write this file with these sections:**

```python
"""Async plan execution engine."""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from niri_pypc import NiriClient, actions
from niri_state import NiriState, Snapshot, WaitTimeoutError
from niri_state.api.config import NiriStateConfig
from niri_state.api.waiters import wait_until

from nirip.plan import PlanStep, Plan, StepKind, WindowProperty, ResizeAxis
from nirip.resolve import evaluate_rule
from nirip.spec import SessionOptions

_FROZEN = ConfigDict(extra="forbid", frozen=True)
_WAIT_CONFIG = NiriStateConfig()


# ─── Types ───────────────────────────────────────────────────────────────────

class StepOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"

class StepResult(BaseModel):
    model_config = _FROZEN
    step: PlanStep
    outcome: StepOutcome
    message: str
    window_id: int | None = None
    spawn_pid: int | None = None
    duration_s: float = 0.0

class ApplyResult(BaseModel):
    model_config = _FROZEN
    session_name: str
    success: bool
    steps: list[StepResult]
    total_duration_s: float

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.COMPLETED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.SKIPPED)

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT)]

@dataclass
class SessionPorts:
    state: NiriState
    client: NiriClient


# ─── Hook Protocol ───────────────────────────────────────────────────────────

class ExecutionHook(Protocol):
    def on_step_start(self, step: PlanStep) -> None: ...
    def on_step_complete(self, step: PlanStep, result: StepResult) -> None: ...
    def on_plan_complete(self, result: ApplyResult) -> None: ...

class _NullHook:
    def on_step_start(self, step): pass
    def on_step_complete(self, step, result): pass
    def on_plan_complete(self, result): pass


# ─── Runtime State ───────────────────────────────────────────────────────────

@dataclass
class _AppState:
    matched_window_id: int | None = None
    spawn_process: Any = None


# ─── Execution Engine ────────────────────────────────────────────────────────

_STATE_ACTIONS: dict[WindowProperty, Callable[[int], Any]] = {
    WindowProperty.FLOATING: actions.move_window_to_floating,
    WindowProperty.TILING: actions.move_window_to_tiling,
    WindowProperty.FULLSCREEN: actions.fullscreen_window,
    WindowProperty.MAXIMIZED: actions.maximize_window_to_edges,
}

_STATE_CHECKS: dict[WindowProperty, Callable[[Any], bool]] = {
    WindowProperty.FLOATING: lambda w: w.is_floating,
    WindowProperty.TILING: lambda w: not w.is_floating,
    WindowProperty.FULLSCREEN: lambda w: getattr(w, "is_fullscreen", False),
    WindowProperty.MAXIMIZED: lambda w: getattr(w, "is_maximized", False),
}

async def execute_plan(...) -> ApplyResult:
    # ... (adapted from executor.py — uses dict[str, _AppState] instead of SessionRuntime)

async def _execute_step(step: PlanStep, ports: SessionPorts, apps: dict[str, _AppState]) -> StepResult:
    # ... (adapted from handlers.py — matches on step.kind enum instead of step class types)

def _resolve_wid(step: PlanStep, apps: dict[str, _AppState]) -> int | None:
    # ... (simplified from handlers._resolve_window_id)

def _is_satisfied(step: PlanStep, snapshot: Snapshot) -> bool:
    # ... (inlined from predicates.py — matches on step.kind instead of step types)

async def _request(client, req) -> None:
    # ... (exact copy from handlers.py)

async def _wait(state, predicate, timeout) -> Snapshot:
    # ... (exact copy from handlers.py)
```

**Key changes from v1:**

1. **`SessionRuntime` + `AppRuntimeState` → `dict[str, _AppState]`:**
   - `SessionRuntime` had `session_name`, `started_at`, `apps` — only `apps` was ever used
   - `AppRuntimeState` had 7 fields — only `matched_window_id` and `spawn_process` are ever read after being set
   - Replace with: `apps: dict[str, _AppState]` where `_AppState` is a 2-field dataclass

2. **Step handler dispatch: type matching → `StepKind` matching:**
   ```python
   # OLD (handlers.py):
   match step:
       case CreateWorkspaceStep(): ...
       case SpawnWindowStep(): ...

   # NEW:
   match step.kind:
       case StepKind.CREATE_WORKSPACE: ...
       case StepKind.SPAWN_WINDOW: ...
   ```

3. **`is_already_satisfied` + `STATE_CHECKS` inlined:**
   - `predicates.py` and `_checks.py` become `_is_satisfied()` and `_STATE_CHECKS` in same file
   - Same logic, same dispatch — matches on `step.kind` instead of step type

4. **`NullHook` → `_NullHook` (private, 3-line):**
   - No need for the `del step` lines — just `pass`

5. **`LoggingHook` moves to `cli.py`:**
   - It's only used by CLI commands, so it belongs there

6. **`execute_plan` simplified init:**
   ```python
   # OLD:
   runtime = _init_runtime(plan)  # builds SessionRuntime with AppRuntimeState per app

   # NEW:
   apps: dict[str, _AppState] = {
       step.app_name: _AppState() for step in plan.steps if step.app_name
   }
   ```

7. **`_resolve_window_id` simplified:**
   ```python
   # OLD: uses getattr(step, "window_id", None) because not all step types have it
   # NEW: step.window_id is always available (it's an optional field on PlanStep)
   def _resolve_wid(step: PlanStep, apps: dict[str, _AppState]) -> int | None:
       if step.window_id is not None:
           return step.window_id
       if step.app_name and step.app_name in apps:
           return apps[step.app_name].matched_window_id
       return None
   ```

**Exact copy sections:**
- `_STATE_ACTIONS` dict (verbatim from handlers.py:44-49)
- `_STATE_CHECKS` dict (verbatim from _checks.py:10-15)
- `_request()` helper (verbatim from handlers.py:36-39)
- `_wait()` helper (verbatim from handlers.py:51-52)
- All handler logic bodies (same operations, same niri_pypc actions)
- Error handling in `execute_plan` (WaitTimeoutError, ConnectionError, OSError)

---

### Step 5: Write `src/nirip/capture.py` (~70 LOC)

**Source files being replaced:**
- `capture/capturer.py` (45 LOC)
- `capture/inference.py` (23 LOC)

**Write this file:**

```python
"""Capture current compositor state as a session spec template."""
from __future__ import annotations

from niri_state import Snapshot
from niri_state.api.selectors import windows, workspaces

from nirip.spec import AppSpec, MatchRule, SessionSpec, WorkspaceSpec


def capture(snapshot: Snapshot, *, name: str | None = None) -> SessionSpec:
    """Export live state as a session spec template."""
    workspace_specs = []
    for ws in workspaces.list_workspaces(snapshot):
        if ws.name is None:
            continue
        apps = []
        for w in windows.list_windows_on_workspace(snapshot, ws.id):
            apps.append(AppSpec(name=_infer_name(w), match=_infer_match(w)))
        workspace_specs.append(WorkspaceSpec(name=ws.name, output=ws.output, apps=apps))
    return SessionSpec(name=name or "captured", workspaces=workspace_specs)


def _infer_name(window) -> str:
    if window.app_id:
        return window.app_id.rsplit(".", 1)[-1].lower().replace(" ", "-")
    if window.title:
        return window.title.lower().replace(" ", "-")[:30]
    return f"app-{window.id}"


def _infer_match(window) -> MatchRule:
    if window.app_id:
        return MatchRule(app_id=window.app_id)
    if window.title:
        return MatchRule(title=window.title)
    return MatchRule(title=f"window-{window.id}")
```

**Key changes from v1:**

1. **`CapturedSession` wrapper deleted → return `SessionSpec` directly:**
   - `CapturedSession.spec` was always immediately unwrapped by callers
   - `CapturedSession.notes` was only used in capturer.py itself (the hints are static strings)
   - `CapturedSession.app_count` / `workspace_count` computed fields never used externally

2. **`capture_from_snapshot()` → `capture()`:**
   - Shorter name, same behavior minus the `notes` generation

3. **`inference.py` inlined:**
   - `infer_app_name()` → `_infer_name()` (private, 5 lines)
   - `infer_match_rule()` → `_infer_match()` (private, 5 lines)

---

### Step 6: Write `src/nirip/cli.py` (~180 LOC)

**Source files being replaced:**
- `cli/main.py` (66 LOC) — argparse, main()
- `cli/commands.py` (66 LOC) — cmd_apply, cmd_diff, cmd_plan, cmd_capture
- `cli/formatting.py` (61 LOC) — format_diff, format_plan, format_result
- `facade/async_nirip.py` (77 LOC) — AsyncNirip (inlined into commands)
- `execution/hooks.py` (partial) — LoggingHook moves here

**Write this file with these sections:**

```python
"""CLI entry point, commands, and formatting."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

from nirip.execute import ApplyResult, ExecutionHook, SessionPorts, StepOutcome, execute_plan
from nirip.plan import Plan, StepKind, build_plan
from nirip.resolve import Resolution, ResolutionStatus, resolve
from nirip.spec import NiripError, SessionSpec, load_from_file


# ─── Formatting ──────────────────────────────────────────────────────────────

def format_resolution(resolution: Resolution) -> str:
    """Human-readable summary of what would change."""
    # ... (adapted from formatting.format_diff — operates on Resolution directly
    #      instead of SessionDiff intermediate; inline the categorization logic
    #      from compile_diff)

def format_plan(plan: Plan) -> str:
    # ... (exact copy from formatting.py)

def format_result(result: ApplyResult) -> str:
    # ... (exact copy from formatting.py)


# ─── Logging Hook ────────────────────────────────────────────────────────────

class LoggingHook:
    def on_step_start(self, step):
        print(f"  -> {step.description}...", file=sys.stderr, flush=True)
    def on_step_complete(self, step, result):
        print(f"     {result.outcome} ({result.duration_s:.1f}s)", file=sys.stderr, flush=True)
    def on_plan_complete(self, result):
        status = "OK" if result.success else "FAILED"
        print(f"  Plan {status} in {result.total_duration_s:.1f}s", file=sys.stderr, flush=True)


# ─── Commands ────────────────────────────────────────────────────────────────

async def cmd_apply(session_file, *, yes=False, dry_run=False, quiet=False) -> str:
    spec, validation = load_from_file(session_file)
    for w in validation.warnings:
        print(f"  warning: {w}", file=sys.stderr)

    from niri_pypc import NiriClient
    from niri_state import NiriState

    state = await NiriState.open()
    client = NiriClient.create()
    ports = SessionPorts(state=state, client=client)
    try:
        resolution = resolve(spec, state.snapshot)
        if dry_run:
            plan = build_plan(resolution, spec.options)
            return format_plan(plan)
        if not yes and resolution.has_drift:
            print(format_resolution(resolution), file=sys.stderr)
            answer = await asyncio.to_thread(input, "Apply? [y/N] ")
            if answer.lower() != "y":
                return "Aborted."
        plan = build_plan(resolution, spec.options)
        if plan.is_empty:
            return "Nothing to do."
        hook = None if quiet else LoggingHook()
        result = await execute_plan(plan, ports, spec.options, hook=hook)
        return format_result(result)
    finally:
        await state.close()
        await client.close()


async def cmd_diff(session_file) -> str:
    spec, _ = load_from_file(session_file)
    from niri_state import NiriState
    state = await NiriState.open()
    try:
        resolution = resolve(spec, state.snapshot)
        return format_resolution(resolution)
    finally:
        await state.close()


async def cmd_plan(session_file) -> str:
    spec, _ = load_from_file(session_file)
    from niri_state import NiriState
    state = await NiriState.open()
    try:
        resolution = resolve(spec, state.snapshot)
        plan = build_plan(resolution, spec.options)
        return format_plan(plan)
    finally:
        await state.close()


async def cmd_capture(*, name=None, output=None) -> str:
    from nirip.capture import capture
    from niri_state import NiriState
    state = await NiriState.open()
    try:
        spec = capture(state.snapshot, name=name)
        text = yaml.dump(spec.model_dump(), default_flow_style=False)
        if output:
            Path(output).write_text(text, encoding="utf-8")
        return text
    finally:
        await state.close()


# ─── Entry Point ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    # ... (exact copy from main.py)

def main(argv=None) -> int:
    # ... (adapted from main.py — uses match/case instead of if/elif)
```

**Key changes from v1:**

1. **`AsyncNirip` facade deleted → commands manage lifecycle directly:**
   - `AsyncNirip.open()` context manager was just `NiriState.open()` + `NiriClient.create()` + try/finally
   - Each command now does this inline — same safety, no indirection
   - No `NiripConfig` parameter (it was never used)

2. **`format_diff(SessionDiff)` → `format_resolution(Resolution)`:**
   - `compile_diff()` built a `SessionDiff` from `Resolution`, then `format_diff()` formatted it
   - Now `format_resolution()` categorizes + formats in one pass directly from `Resolution`
   - Uses `Resolution.apps` flat list and `Resolution.workspaces` for workspace facts
   - The categorization logic from `compile_diff()` (compiler.py:81-109) moves here:
     ```python
     def format_resolution(resolution: Resolution) -> str:
         if resolution.fully_converged:
             return "No changes needed — session is converged."
         lines = []
         matched = [ar for ar in resolution.apps if ar.status == ResolutionStatus.MATCHED]
         if matched:
             lines.append(f"Matched: {len(matched)} app(s)")
         will_spawn = [ar for ar in resolution.apps if ar.status == ResolutionStatus.MISSING]
         if will_spawn:
             lines.append("Will spawn:")
             for ar in will_spawn:
                 lines.append(f"  + {ar.workspace_name}/{ar.app_name}")
         # ... (same pattern for will_move, drifted, optional, workspace_changes, errors)
         return "\n".join(lines)
     ```

3. **`LoggingHook` moves here from `execution/hooks.py`:**
   - It's only used by CLI commands — belongs with its consumer

4. **`main()` uses `match/case` instead of `if/elif`:**
   - Cleaner dispatch, same behavior

---

### Step 7: Write `src/nirip/__init__.py` (~60 LOC)

**Source files being replaced:**
- Current `__init__.py` (63 LOC) — public API + sync wrappers

```python
"""nirip: Declarative session reconciler for Niri."""
from __future__ import annotations

import asyncio
from pathlib import Path

from nirip.spec import SessionSpec, load_from_file, NiripError, ValidationError
from nirip.resolve import Resolution, resolve
from nirip.plan import Plan, build_plan
from nirip.execute import ApplyResult, execute_plan, SessionPorts

__all__ = [
    "NiripError",
    "ValidationError",
    "SessionSpec",
    "Resolution",
    "Plan",
    "ApplyResult",
    "load_from_file",
    "resolve",
    "build_plan",
    "execute_plan",
    "apply_session",
]


def apply_session(path: str | Path) -> ApplyResult:
    """One-shot sync: load → resolve → plan → execute."""
    from niri_pypc import NiriClient
    from niri_state import NiriState

    spec, _ = load_from_file(path)

    async def _run():
        state = await NiriState.open()
        client = NiriClient.create()
        try:
            resolution = resolve(spec, state.snapshot)
            plan = build_plan(resolution, spec.options)
            if plan.is_empty:
                return ApplyResult(session_name=spec.name, success=True, steps=[], total_duration_s=0.0)
            ports = SessionPorts(state=state, client=client)
            return await execute_plan(plan, ports, spec.options)
        finally:
            await state.close()
            await client.close()

    return asyncio.run(_run())
```

**Key changes from v1:**

1. **Exports simplified:**
   - Remove: `AsyncNirip`, `NiripConfig`, `SessionDiff`, `ValidatedSpec`
   - Remove: `load_spec_from_string`, `load_spec_from_dict`, `load_session`
   - Remove: `plan_session`, `diff_session` sync wrappers (power users compose the pipeline)
   - Keep: `apply_session` as the one sync convenience function
   - Export the 4 pipeline functions: `load_from_file`, `resolve`, `build_plan`, `execute_plan`

2. **No `AsyncNirip` to export:**
   - Power users compose `resolve` + `build_plan` + `execute_plan` directly

---

### Step 8: Keep `src/nirip/__main__.py` (unchanged)

```python
from nirip.cli import main
raise SystemExit(main())
```

Verify: the import `from nirip.cli import main` needs `cli.py` to expose `main` — which it does.

---

### Step 9: Delete old code

After all new files are written and working:

```bash
# Delete old subpackages
rm -rf src/nirip/spec/
rm -rf src/nirip/resolve/
rm -rf src/nirip/planning/
rm -rf src/nirip/execution/
rm -rf src/nirip/capture/
rm -rf src/nirip/facade/
rm -rf src/nirip/cli/

# Delete old root files
rm src/nirip/_base.py
rm src/nirip/config.py
rm src/nirip/errors.py
```

---

### Step 10: Port tests

**Test mapping (old → new):**

| Old test file | New test file | Notes |
|--------------|--------------|-------|
| `test_base.py` (24) | DELETE | NiripModel no longer exists |
| `test_config.py` (17) | DELETE | NiripConfig no longer exists |
| `test_errors.py` (18) | Fold into `test_spec.py` | Only NiripError + ValidationError remain |
| `test_spec_models.py` (19) | `test_spec.py` | Same assertions, different imports |
| `test_spec_defaults.py` (18) | `test_spec.py` | Same |
| `test_spec_loader.py` (14) | `test_spec.py` | Adapt for tuple return |
| `test_spec_validators.py` (77) | `test_spec.py` | Same assertions, different imports |
| `test_matcher.py` (76) | `test_resolve.py` | Drop `reasons` from assertions |
| `test_resolver_drift.py` (30) | `test_resolve.py` | Adapt for flat Resolution |
| `test_matcher_resolver_planning.py` (17) | `test_resolve.py` or `test_plan.py` | Adapt |
| `test_planning_models.py` (30) | `test_plan.py` | Adapt for single PlanStep |
| `test_plan_builder.py` (69) | `test_plan.py` | Test build_plan() function |
| `test_compiler.py` (59) | `test_plan.py` | Merge with builder tests |
| `test_compiler_spawn_placement.py` (126) | `test_plan.py` | Same logic, new API |
| `test_compiler_depends_on.py` (78) | `test_plan.py` | Same |
| `test_ordering.py` (19) | `test_plan.py` | Same |
| `test_executor.py` (156) | `test_execute.py` | Adapt for new types |
| `test_capturer.py` (15) | `test_capture.py` | Adapt for SessionSpec return |
| `test_cli_formatting.py` (35) | `test_cli.py` | Adapt for format_resolution |
| `test_integration.py` (44) | `test_integration.py` | Full pipeline test |

**Target test structure:**
```
tests/
├── conftest.py           # FakeWindow, FakeWorkspace, FakeSnapshot (keep as-is)
├── __init__.py
├── test_spec.py          # ~130 LOC (merged from 4 test files)
├── test_resolve.py       # ~120 LOC (merged from 3 test files)
├── test_plan.py          # ~350 LOC (merged from 6 test files)
├── test_execute.py       # ~160 LOC (from test_executor.py)
├── test_capture.py       # ~15 LOC (from test_capturer.py)
├── test_cli.py           # ~35 LOC (from test_cli_formatting.py)
└── test_integration.py   # ~50 LOC (from test_integration.py)
```

**Import changes for every test file:**
```python
# OLD:
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, ...
from nirip.spec.validators import validate_session, ValidationResult
from nirip.spec.loader import load_spec_from_file
from nirip.resolve.models import MatchTier, Resolution, AppResolution, ...
from nirip.resolve.matcher import evaluate_rule, assign_windows
from nirip.resolve.resolver import resolve
from nirip.planning.models import Plan, PlanStep, CreateWorkspaceStep, ...
from nirip.planning.compiler import compile_plan, compile_diff, parse_size
from nirip.planning.builder import PlanBuilder
from nirip.planning.ordering import topological_sort
from nirip.execution.models import ApplyResult, StepResult, StepOutcome, SessionPorts
from nirip.execution.hooks import ExecutionHook, LoggingHook
from nirip.execution.executor import execute_plan
from nirip.errors import NiripError, SpecError, CycleError, ...

# NEW:
from nirip.spec import AppSpec, MatchRule, SessionSpec, ..., NiripError, ValidationError
from nirip.spec import validate_session, ValidationResult, load_from_file
from nirip.resolve import MatchTier, Resolution, AppResolution, ..., evaluate_rule, resolve
from nirip.plan import Plan, PlanStep, StepKind, build_plan
from nirip.execute import ApplyResult, StepResult, StepOutcome, SessionPorts, execute_plan
```

**Key test adaptations:**

1. **`evaluate_rule` returns `(bool, MatchTier)` not `(bool, MatchTier, list[str])`:**
   ```python
   # OLD:
   matched, tier, reasons = evaluate_rule(rule, window)
   assert "app_id exact" in reasons[0]

   # NEW:
   matched, tier = evaluate_rule(rule, window)
   # (no reasons to check)
   ```

2. **`load_from_file` returns `tuple` not `ValidatedSpec`:**
   ```python
   # OLD:
   validated = load_spec_from_file(path)
   spec = validated.spec

   # NEW:
   spec, validation = load_from_file(path)
   ```

3. **Resolution is flat, not nested:**
   ```python
   # OLD:
   resolution.workspace_resolutions[0].app_resolutions[0].match_decision.assigned_window_id

   # NEW:
   resolution.apps[0].window_id
   ```

4. **PlanStep is one type with `kind` field:**
   ```python
   # OLD:
   assert isinstance(step, CreateWorkspaceStep)
   assert step.target_output == "DP-1"

   # NEW:
   assert step.kind == StepKind.CREATE_WORKSPACE
   assert step.target_output == "DP-1"
   ```

5. **`compile_diff` tests → `format_resolution` tests:**
   ```python
   # OLD:
   diff = compile_diff(resolution)
   assert "firefox" in diff.will_spawn

   # NEW:
   output = format_resolution(resolution)
   assert "firefox" in output
   ```

6. **Error types simplified:**
   ```python
   # OLD:
   with pytest.raises(SpecError):
   with pytest.raises(CycleError):

   # NEW:
   with pytest.raises(NiripError):
   with pytest.raises(NiripError, match="dependency cycle"):
   ```

---

### Step 11: Update `pyproject.toml`

No changes needed to `pyproject.toml` — the package structure under `src/nirip/` is still the same root, and hatch will pick up the new flat files. The CLI entry point in `__main__.py` still works.

Consider bumping the version:
```toml
version = "1.0.0"  # nuclear refactor = major version
```

---

### Step 12: Final validation

```bash
# Run all tests
uv run pytest -v

# Check imports resolve correctly
uv run python -c "from nirip import apply_session, resolve, build_plan, execute_plan; print('OK')"

# Check CLI works
uv run python -m nirip --help

# Type check
uv run ty check

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Verify line counts match targets
find src/nirip -name '*.py' -exec wc -l {} + | sort -n
```

---

## Cross-Reference: Import Dependency Graph (v2)

```
spec.py          → (no nirip imports)
resolve.py       → spec
plan.py          → resolve, spec
execute.py       → plan, resolve, spec
capture.py       → spec
cli.py           → execute, plan, resolve, spec
__init__.py      → spec, resolve, plan, execute
```

Every module imports only from modules above it. No cycles. Any operation traces through at most 2 files.

---

## Cross-Reference: Symbol Migration Map

### Models

| v1 Location | v1 Name | v2 Location | v2 Name | Change |
|---|---|---|---|---|
| `_base.py` | `NiripModel` | — | DELETED | Use `BaseModel` + `_FROZEN` |
| `config.py` | `NiripConfig` | — | DELETED | Dead code |
| `errors.py` | `NiripError` | `spec.py` | `NiripError` | Moved |
| `errors.py` | `SpecError` | — | DELETED | Use `NiripError` |
| `errors.py` | `SpecValidationError` | `spec.py` | `ValidationError` | Renamed + moved |
| `errors.py` | `PlanningError` | — | DELETED | Use `NiripError` |
| `errors.py` | `CycleError` | — | DELETED | Use `NiripError(msg)` |
| `errors.py` | `CaptureError` | — | DELETED | Unused |
| `errors.py` | `NiripConnectionError` | — | DELETED | Unused |
| `spec/models.py` | `MatchRule` | `spec.py` | `MatchRule` | Same |
| `spec/models.py` | `SpawnSpec` | `spec.py` | `SpawnSpec` | Same |
| `spec/models.py` | `PlacementSpec` | `spec.py` | `PlacementSpec` | Same |
| `spec/models.py` | `AppSpec` | `spec.py` | `AppSpec` | Same |
| `spec/models.py` | `WorkspaceSpec` | `spec.py` | `WorkspaceSpec` | Same |
| `spec/models.py` | `SessionOptions` | `spec.py` | `SessionOptions` | Same |
| `spec/models.py` | `SessionSpec` | `spec.py` | `SessionSpec` | Same |
| `spec/validators.py` | `ValidationResult` | `spec.py` | `ValidationResult` | Same |
| `spec/validators.py` | `ValidatedSpec` | — | DELETED | Return tuple |
| `resolve/models.py` | `MatchTier` | `resolve.py` | `MatchTier` | Same |
| `resolve/models.py` | `MatchCandidate` | — | DELETED | Local tuples |
| `resolve/models.py` | `WindowAssigner` | — | DELETED | One impl, never swapped |
| `resolve/models.py` | `MatchDecision` | — | DELETED | Fields in AppResolution |
| `resolve/models.py` | `ResolutionStatus` | `resolve.py` | `ResolutionStatus` | Same |
| `resolve/models.py` | `DriftKind` | `resolve.py` | `DriftKind` | Same |
| `resolve/models.py` | `DriftItem` | `resolve.py` | `DriftItem` | Same |
| `resolve/models.py` | `AppResolution` | `resolve.py` | `AppResolution` | window_id + is_ambiguous promoted |
| `resolve/models.py` | `WorkspaceResolution` | `resolve.py` | `WorkspaceState` | Renamed, no app_resolutions field |
| `resolve/models.py` | `Resolution` | `resolve.py` | `Resolution` | Flat apps list |
| `planning/models.py` | 9 step classes | `plan.py` | `PlanStep` | Unified |
| `planning/models.py` | `PlanStep` (union) | `plan.py` | `PlanStep` (class) | Single class |
| `planning/models.py` | `Plan` | `plan.py` | `Plan` | Simplified |
| `planning/models.py` | `SessionDiff` | — | DELETED | Inline in CLI |
| `planning/models.py` | `WindowProperty` | `plan.py` | `WindowProperty` | Same |
| `planning/models.py` | `ResizeAxis` | `plan.py` | `ResizeAxis` | Same |
| `execution/models.py` | `StepOutcome` | `execute.py` | `StepOutcome` | Same |
| `execution/models.py` | `StepResult` | `execute.py` | `StepResult` | Same |
| `execution/models.py` | `ApplyResult` | `execute.py` | `ApplyResult` | @property not computed_field |
| `execution/models.py` | `SessionPorts` | `execute.py` | `SessionPorts` | Same |
| `execution/hooks.py` | `ExecutionHook` | `execute.py` | `ExecutionHook` | Same |
| `execution/hooks.py` | `NullHook` | `execute.py` | `_NullHook` | Private |
| `execution/hooks.py` | `LoggingHook` | `cli.py` | `LoggingHook` | Moved to consumer |
| `capture/capturer.py` | `CapturedSession` | — | DELETED | Return SessionSpec |
| `facade/async_nirip.py` | `AsyncNirip` | — | DELETED | Inline in CLI |

### Functions

| v1 Location | v1 Name | v2 Location | v2 Name | Change |
|---|---|---|---|---|
| `spec/loader.py` | `load_spec_from_file` | `spec.py` | `load_from_file` | Renamed, returns tuple |
| `spec/loader.py` | `load_spec_from_string` | `spec.py` | `load_from_string` | Renamed, returns tuple |
| `spec/loader.py` | `load_spec_from_dict` | `spec.py` | `load_from_dict` | Renamed, returns tuple |
| `spec/validators.py` | `validate_session` | `spec.py` | `validate_session` | Same |
| `resolve/matcher.py` | `evaluate_rule` | `resolve.py` | `evaluate_rule` | Drop reasons return |
| `resolve/matcher.py` | `assign_windows` | `resolve.py` | `_assign` | Private, different return type |
| `resolve/resolver.py` | `resolve` | `resolve.py` | `resolve` | Flat output |
| `planning/compiler.py` | `compile_plan` | `plan.py` | `build_plan` | Renamed |
| `planning/compiler.py` | `compile_diff` | — | DELETED | Logic in cli.format_resolution |
| `planning/compiler.py` | `parse_size` | `plan.py` | `_parse_size` | Private |
| `planning/ordering.py` | `topological_sort` | `plan.py` | `_topological_sort` | Private |
| `execution/executor.py` | `execute_plan` | `execute.py` | `execute_plan` | Same |
| `execution/handlers.py` | `execute_step` | `execute.py` | `_execute_step` | Private |
| `execution/predicates.py` | `is_already_satisfied` | `execute.py` | `_is_satisfied` | Private |
| `capture/capturer.py` | `capture_from_snapshot` | `capture.py` | `capture` | Renamed, returns SessionSpec |
| `capture/inference.py` | `infer_app_name` | `capture.py` | `_infer_name` | Private |
| `capture/inference.py` | `infer_match_rule` | `capture.py` | `_infer_match` | Private |
| `__init__.py` | `load_session` | — | DELETED | Use load_from_file |
| `__init__.py` | `apply_session` | `__init__.py` | `apply_session` | Same, uses new internals |
| `__init__.py` | `plan_session` | — | DELETED | Compose pipeline |
| `__init__.py` | `diff_session` | — | DELETED | Compose pipeline |

---

## Execution Order Summary

| Step | File | LOC | Depends On | Risk |
|------|------|-----|------------|------|
| 1 | `spec.py` | ~300 | nothing | Zero — models + validation are pure |
| 2 | `resolve.py` | ~300 | spec.py | Low — mostly structural flattening |
| 3 | `plan.py` | ~350 | resolve.py, spec.py | Medium — Builder→function rewrite |
| 4 | `execute.py` | ~300 | plan.py, resolve.py, spec.py | Medium — type dispatch changes |
| 5 | `capture.py` | ~70 | spec.py | Zero — trivial merge |
| 6 | `cli.py` | ~180 | execute, plan, resolve, spec | Low — mostly glue |
| 7 | `__init__.py` | ~60 | everything | Zero — just re-exports |
| 8 | Delete old code | — | everything passes | Zero — old code unused |
| 9 | Port tests | ~860 | everything passes | Medium — import/API changes |
| 10 | Final validation | — | tests pass | — |

Write files in dependency order (1→7), run tests at each step to catch issues early. Steps 1-2 can be validated with unit tests immediately. Steps 3-4 require the full pipeline for integration tests. Steps 5-7 are quick wins after the core is solid.
