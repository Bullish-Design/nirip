# Nirip Refined Concept — Implementation Guide

A file-by-file implementation guide for the complete nirip rewrite, based on the refined concept document.

---

## Table of Contents

1. [Prerequisites and Conventions](#1-prerequisites-and-conventions)
2. [Phase 1: Foundation](#2-phase-1-foundation)
   - 2.1 `src/nirip/_base.py` — NiripModel base class
   - 2.2 `src/nirip/errors.py` — Error hierarchy
   - 2.3 `src/nirip/config.py` — NiripConfig
3. [Phase 2: Spec Layer](#3-phase-2-spec-layer)
   - 3.1 `src/nirip/spec/models.py` — Session spec models
   - 3.2 `src/nirip/spec/validators.py` — Validation engine
   - 3.3 `src/nirip/spec/defaults.py` — Default merging
   - 3.4 `src/nirip/spec/loader.py` — YAML loading
4. [Phase 3: Resolve Layer](#4-phase-3-resolve-layer)
   - 4.1 `src/nirip/resolve/models.py` — Resolution models
   - 4.2 `src/nirip/resolve/normalizer.py` — Spec normalization
   - 4.3 `src/nirip/resolve/matcher.py` — Rule evaluation + global assignment
   - 4.4 `src/nirip/resolve/resolver.py` — Full resolution
5. [Phase 4: Planning Layer](#5-phase-4-planning-layer)
   - 5.1 `src/nirip/planning/models.py` — Typed plan steps + Plan + SessionDiff
   - 5.2 `src/nirip/planning/ordering.py` — Topological sort
   - 5.3 `src/nirip/planning/compiler.py` — Resolution to Plan/Diff
6. [Phase 5: Execution Layer](#6-phase-5-execution-layer)
   - 6.1 `src/nirip/execution/models.py` — StepResult, ApplyResult, SessionPorts
   - 6.2 `src/nirip/execution/runtime.py` — SessionRuntime, AppRuntimeState
   - 6.3 `src/nirip/execution/predicates.py` — Skip-check predicates
   - 6.4 `src/nirip/execution/handlers.py` — Per-step-type execution
   - 6.5 `src/nirip/execution/executor.py` — Plan executor
7. [Phase 6: Capture Layer](#7-phase-6-capture-layer)
   - 7.1 `src/nirip/capture/inference.py` — Match rule inference
   - 7.2 `src/nirip/capture/capturer.py` — Snapshot to scaffold
8. [Phase 7: Facade Layer](#8-phase-7-facade-layer)
   - 8.1 `src/nirip/facade/async_nirip.py` — AsyncNirip
   - 8.2 `src/nirip/facade/sync_nirip.py` — SyncNirip
9. [Phase 8: CLI Layer](#9-phase-8-cli-layer)
   - 9.1 `src/nirip/cli/main.py` — CLI entrypoint
   - 9.2 `src/nirip/cli/commands.py` — Command handlers
10. [Phase 9: Package Exports](#10-phase-9-package-exports)
    - 10.1 `src/nirip/__init__.py` — Public API
    - 10.2 `src/nirip/__main__.py` — Module entrypoint
    - 10.3 Subpackage `__init__.py` files
11. [Phase 10: Tests](#11-phase-10-tests)
12. [Files to Delete](#12-files-to-delete)
13. [Dependency Import Map](#13-dependency-import-map)

---

*Sections follow below. Each section specifies the exact file path, every import, every class/function with full signatures, field definitions, and implementation notes.*

---

## 1. Prerequisites and Conventions

### External dependencies consumed by nirip

```python
# From niri-pypc (all from niri_pypc package)
from niri_pypc import NiriClient, NiriConfig as NiriPypcConfig
from niri_pypc import actions                        # 110+ action builders
from niri_pypc.types.generated.models import Window, Workspace, Output
from niri_pypc.types.generated.request import ActionRequest

# From niri-state (all from niri_state package)
from niri_state import (
    NiriState,
    NiriStateConfig,
    Snapshot,
    HealthState,
    WaitTimeoutError,
)
from niri_state.api.waiters import wait_until, wait_for_selector, watch
from niri_state.api.selectors import windows, workspaces, outputs, focus

# From stdlib
import asyncio  # create_subprocess_exec for spawning
```

### Conventions

- **Every model** inherits from `NiripModel` (section 2.1) unless explicitly noted.
- **No protocol abstractions** (`SnapshotLike`, `WindowLike`, `ActionClient`) in production code. Use concrete types from dependencies.
- **Imports are absolute** — `from nirip._base import NiripModel`, not relative.
- **`__init__.py` files** in subpackages are minimal — re-export key symbols only.
- **Tests** use fake/mock implementations injected via constructor parameters.
- **Type annotations** on every function signature and class field.

### niri-pypc action builder signatures used by nirip

These are the specific builders nirip calls. All return `ActionRequest`:

```python
actions.focus_workspace(reference: int | str | WorkspaceReferenceArg) -> ActionRequest
actions.focus_window(id: int) -> ActionRequest
actions.move_window_to_workspace(reference, focus=True, window_id=None) -> ActionRequest
actions.move_window_to_floating(id=None) -> ActionRequest
actions.move_window_to_tiling(id=None) -> ActionRequest
actions.fullscreen_window(id=None) -> ActionRequest        # toggle
actions.maximize_window_to_edges(id=None) -> ActionRequest  # toggle
actions.set_column_width(change: SizeChange) -> ActionRequest
actions.set_window_height(change: SizeChange, id=None) -> ActionRequest
actions.move_workspace_to_monitor(output, reference=None) -> ActionRequest
actions.workspace_by_name(name: str) -> WorkspaceReferenceArg
actions.size_set_proportion(value: float) -> SizeChange
actions.size_set_fixed(value: int) -> SizeChange
```

### niri-state API signatures used by nirip

```python
# NiriState lifecycle
NiriState.open(config=None) -> NiriState             # classmethod, async
state.snapshot -> Snapshot                             # property
state.health() -> HealthState
state.subscribe() -> AsyncIterator[PublishedState]
state.close() -> None                                  # async

# Snapshot fields
snapshot.windows: MappingProxyType[int, Window]
snapshot.workspaces: MappingProxyType[int, Workspace]
snapshot.outputs: MappingProxyType[str, Output]
snapshot.focused_window_id: int | None
snapshot.focused_workspace_id: int | None
snapshot.windows_by_workspace: MappingProxyType[int, tuple[int, ...]]

# Selectors
windows.list_windows(snapshot) -> tuple[Window, ...]
windows.list_windows_on_workspace(snapshot, ws_id) -> tuple[Window, ...]
windows.get_window(snapshot, window_id) -> Window | None
workspaces.list_workspaces(snapshot) -> tuple[Workspace, ...]
workspaces.get_workspace(snapshot, ws_id) -> Workspace | None
outputs.list_outputs(snapshot) -> tuple[Output, ...]
focus.get_focused_window(snapshot) -> Window | None
focus.get_focused_workspace(snapshot) -> Workspace | None

# Waiters
wait_until(state, predicate, *, config, timeout=None) -> Snapshot
wait_for_selector(state, selector, *, predicate=None, config, timeout=None) -> T
```

### Window / Workspace / Output field access

These are niri-pypc generated models. Key fields used by nirip:

```python
# Window fields (from niri_pypc.types.generated.models.Window)
window.id: int
window.app_id: str
window.title: str
window.pid: int | None        # Note: may need to check actual field name
window.workspace_id: int | None
window.is_floating: bool
window.is_fullscreen: bool
window.is_maximized: bool      # Note: verify field name — may be different

# Workspace fields
workspace.id: int
workspace.name: str | None
workspace.output: str
workspace.is_active: bool

# Output fields
output.name: str
```

**Important:** Before implementing, verify the exact field names on the generated `Window`, `Workspace`, and `Output` models by reading the niri-pypc generated types. The field names above are based on the code review but may differ slightly (e.g., `is_maximized` vs a different name, `pid` availability).

---

## 2. Phase 1: Foundation

### 2.1 `src/nirip/_base.py`

**Purpose:** Single shared base model for all nirip Pydantic models.

```python
"""Shared base model for all nirip types."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NiripModel(BaseModel):
    """Base for all nirip models.

    Rejects unknown fields and is immutable by default.
    Subclasses that need mutability override model_config explicitly.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=True,
    )
```

**Changes from current:** This file is new. Currently no shared base model exists — every model inherits directly from `BaseModel` with no `extra` or `frozen` configuration.

**Tests:** `tests/test_base.py`
- Verify `extra="forbid"` rejects unknown fields.
- Verify `frozen=True` prevents attribute mutation.
- Verify a subclass inherits these settings by default.

---

### 2.2 `src/nirip/errors.py`

**Purpose:** Complete error hierarchy. Slimmed down — operational failures are `StepResult` outcomes, not exceptions.

```python
"""Error hierarchy for nirip."""

from __future__ import annotations


class NiripError(Exception):
    """Base for all nirip errors."""


class SpecError(NiripError):
    """Invalid session spec (parse or structural error)."""


class SpecValidationError(SpecError):
    """Spec validation failed with one or more errors."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None) -> None:
        self.errors = errors
        self.warnings = warnings or []
        msg = f"{len(errors)} validation error(s): {'; '.join(errors[:3])}"
        if len(errors) > 3:
            msg += f" ... and {len(errors) - 3} more"
        super().__init__(msg)


class PlanningError(NiripError):
    """Plan compilation failed."""


class CycleError(PlanningError):
    """Dependency cycle detected during topological sort."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"dependency cycle: {' -> '.join(cycle)}")


class CaptureError(NiripError):
    """Capture operation failed."""


class NiripConnectionError(NiripError):
    """Cannot connect to niri compositor."""
```

**Changes from current:**
- **Removed:** `MatchError`, `AmbiguousMatchError` — now `ResolutionStatus` enum values.
- **Removed:** `ExecutionError`, `StepTimeoutError` — now `StepOutcome` enum values in `StepResult`.
- **Added:** `SpecValidationError` carries structured `errors` and `warnings` lists.
- **Added:** `CycleError` carries the `cycle` list.

**Tests:** `tests/test_errors.py` — hierarchy, `isinstance` checks, structured fields on `SpecValidationError` and `CycleError`.

---

### 2.3 `src/nirip/config.py`

**Purpose:** Nirip-level configuration. Does not wrap `NiriConfig` or `NiriStateConfig`.

```python
"""Nirip configuration."""

from __future__ import annotations

from pathlib import Path

from nirip._base import NiripModel


class NiripConfig(NiripModel):
    session_dir: Path = Path("~/.config/nirip/sessions")
    state_dir: Path = Path("~/.local/state/nirip")
    default_timeout_s: float = 20.0
    confirm_before_apply: bool = True
```

**Changes from current:** Inherits `NiripModel` instead of `BaseModel`. Gains `extra="forbid"` and `frozen=True` automatically.

**Tests:** `tests/test_config.py` — defaults, frozen, rejects unknown fields.

---

## 3. Phase 2: Spec Layer

### 3.1 `src/nirip/spec/models.py`

**Purpose:** All user-facing session specification models.

```python
"""Session specification models."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from nirip._base import NiripModel


class MatchRule(NiripModel):
    """Window matching rule with boolean composition."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    app_id: str | None = None
    app_id_regex: str | None = None
    title: str | None = None
    title_regex: str | None = None
    pid: int | None = None
    any_of: list[MatchRule] | None = Field(None, validation_alias="any")
    not_rule: MatchRule | None = Field(None, validation_alias="not")

    @model_validator(mode="after")
    def _validate_not_empty(self) -> MatchRule:
        has_leaf = any([
            self.app_id, self.app_id_regex,
            self.title, self.title_regex,
            self.pid is not None,
        ])
        has_composite = self.any_of is not None or self.not_rule is not None
        if not has_leaf and not has_composite:
            raise ValueError("MatchRule must have at least one criterion")
        return self


class SpawnSpec(NiripModel):
    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False


class PlacementSpec(NiripModel):
    floating: bool = False
    fullscreen: bool = False
    maximized: bool = False
    focus: bool = False
    column_width: float | str | None = None
    window_height: float | str | None = None

    @model_validator(mode="after")
    def _validate_mutual_exclusion(self) -> PlacementSpec:
        if self.floating and self.fullscreen:
            raise ValueError("floating and fullscreen are mutually exclusive")
        return self


class AppSpec(NiripModel):
    name: str
    match: MatchRule
    spawn: SpawnSpec | None = None
    placement: PlacementSpec = Field(default_factory=PlacementSpec)
    optional: bool = False
    startup_timeout_s: float | None = None
    depends_on: list[str] = Field(default_factory=list)


class WorkspaceSpec(NiripModel):
    name: str
    output: str | None = None
    focus: bool = False
    apps: list[AppSpec] = Field(default_factory=list)


class SessionOptions(NiripModel):
    mode: Literal["reconcile", "clean"] = "reconcile"
    match_existing: bool = True
    launch_missing: bool = True
    stop_on_error: bool = True
    move_unmatched: bool = False
    default_startup_timeout_s: float = 20.0


class SessionSpec(NiripModel):
    name: str
    description: str = ""
    options: SessionOptions = Field(default_factory=SessionOptions)
    workspaces: list[WorkspaceSpec]
```

**Changes from current:**
- All models inherit `NiripModel` → `extra="forbid"`, `frozen=True`.
- `MatchRule` uses `validation_alias="any"` (not `alias="any"`), with `populate_by_name=True`.
- `SessionOptions.mode` is `Literal["reconcile", "clean"]` instead of bare `str`.

**Tests:** `tests/test_spec_models.py` — all existing, plus extra=forbid, validation_alias, Literal validation.

---

### 3.2 `src/nirip/spec/validators.py`

**Purpose:** Deep validation returning `ValidationResult` — never drops warnings.

```python
"""Session spec validation."""

from __future__ import annotations

import re

from pydantic import Field

from nirip._base import NiripModel
from nirip.spec.models import AppSpec, MatchRule, SessionSpec


class ValidationResult(NiripModel):
    valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ValidatedSpec(NiripModel):
    """A spec that passed parsing, bundled with its validation report."""
    spec: SessionSpec
    validation: ValidationResult


def validate_session(spec: SessionSpec) -> ValidationResult:
    """Run all validation checks. Never raises — all problems in result."""
    errors: list[str] = []
    warnings: list[str] = []

    _check_unique_workspace_names(spec, errors)
    _check_unique_app_names(spec, errors)
    _check_depends_on_refs(spec, errors)
    _check_regex_patterns(spec, errors)
    _check_weak_matchers(spec, warnings)
    _check_inter_app_conflicts(spec, warnings)
    _check_spawn_commands(spec, errors)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
```

**Validation functions (private, same checks as current):**

- `_check_unique_workspace_names(spec, errors)` — duplicate workspace names → error.
- `_check_unique_app_names(spec, errors)` — duplicate app names within workspace → error.
- `_check_depends_on_refs(spec, errors)` — dangling refs → error. Includes DFS cycle detection.
- `_check_regex_patterns(spec, errors)` — invalid regex → error.
- `_check_weak_matchers(spec, warnings)` — title_regex-only → **warning**.
- `_check_inter_app_conflicts(spec, warnings)` — identical match signatures → warning.
- `_check_spawn_commands(spec, errors)` — empty command → error.

**Changes from current:**
- `ValidationResult` is `NiripModel` (frozen, extra=forbid).
- **New:** `ValidatedSpec` bundles spec + validation.
- Warnings always preserved.
- `validate_session` takes separate `errors`/`warnings` lists and passes them to sub-checks.

---

### 3.3 `src/nirip/spec/defaults.py`

**Purpose:** Apply session defaults to apps.

```python
"""Default merging for session specs."""

from __future__ import annotations

from nirip.spec.models import SessionSpec


def apply_defaults(spec: SessionSpec) -> SessionSpec:
    """Return new SessionSpec with defaults applied to all apps."""
    default_timeout = spec.options.default_startup_timeout_s
    new_workspaces = []
    for ws in spec.workspaces:
        new_apps = []
        for app in ws.apps:
            if app.startup_timeout_s is None:
                app = app.model_copy(update={"startup_timeout_s": default_timeout})
            new_apps.append(app)
        new_workspaces.append(ws.model_copy(update={"apps": new_apps}))
    return spec.model_copy(update={"workspaces": new_workspaces})
```

Uses `model_copy(update=...)` for frozen model mutation. Identical logic to current.

---

### 3.4 `src/nirip/spec/loader.py`

**Purpose:** YAML → `ValidatedSpec`.

```python
"""YAML loading and validation pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from nirip.errors import SpecError, SpecValidationError
from nirip.spec.defaults import apply_defaults
from nirip.spec.models import SessionSpec
from nirip.spec.validators import ValidatedSpec, validate_session


def load_spec_from_file(path: str | Path) -> ValidatedSpec:
    p = Path(path)
    if not p.exists():
        raise SpecError(f"file not found: {p}")
    text = p.read_text(encoding="utf-8")
    return load_spec_from_string(text, source=str(p))


def load_spec_from_string(text: str, *, source: str = "<string>") -> ValidatedSpec:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SpecError(f"YAML parse error in {source}: {e}") from e
    if not isinstance(data, dict):
        raise SpecError(f"expected mapping in {source}, got {type(data).__name__}")
    return load_spec_from_dict(data, source=source)


def load_spec_from_dict(data: dict[str, Any], *, source: str = "<dict>") -> ValidatedSpec:
    try:
        spec = SessionSpec.model_validate(data)
    except Exception as e:
        raise SpecError(f"spec parse error in {source}: {e}") from e

    spec = apply_defaults(spec)
    validation = validate_session(spec)

    if not validation.valid:
        raise SpecValidationError(validation.errors, validation.warnings)

    return ValidatedSpec(spec=spec, validation=validation)
```

**Changes from current:** Returns `ValidatedSpec`. Raises `SpecValidationError` with structured data.

---

## 4. Phase 3: Resolve Layer

### 4.1 `src/nirip/resolve/models.py`

**Purpose:** All intermediate models for normalization, matching, and resolution.

```python
"""Resolution layer models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, computed_field

from nirip._base import NiripModel
from nirip.spec.models import MatchRule, PlacementSpec, SessionOptions, SpawnSpec


# ── Normalization ──

class NormalizedApp(NiripModel):
    name: str
    workspace_name: str
    match: MatchRule
    spawn: SpawnSpec | None
    placement: PlacementSpec
    optional: bool
    startup_timeout_s: float
    depends_on: list[str]


class NormalizedWorkspace(NiripModel):
    name: str
    output: str | None
    focus: bool
    app_names: list[str]


class NormalizedSession(NiripModel):
    name: str
    description: str
    options: SessionOptions
    workspaces: list[NormalizedWorkspace]
    apps: list[NormalizedApp]
    app_index: dict[str, NormalizedApp] = Field(default_factory=dict)


# ── Matching ──

class MatchCandidate(NiripModel):
    window_id: int
    confidence: float
    reasons: list[str]


class MatchDecision(NiripModel):
    app_name: str
    workspace_name: str
    assigned_window_id: int | None = None
    candidates: list[MatchCandidate]
    confidence: float = 0.0
    rationale: list[str]

    @computed_field
    @property
    def is_ambiguous(self) -> bool:
        return sum(1 for c in self.candidates if c.confidence > 0.6) > 1

    @computed_field
    @property
    def is_matched(self) -> bool:
        return self.assigned_window_id is not None


# ── Resolution ──

class ResolutionStatus(StrEnum):
    MATCHED = "matched"
    DRIFTED = "drifted"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    OPTIONAL_MISSING = "optional_missing"


class DriftKind(StrEnum):
    WRONG_WORKSPACE = "wrong_workspace"
    WRONG_FLOATING = "wrong_floating"
    WRONG_FULLSCREEN = "wrong_fullscreen"
    WRONG_MAXIMIZED = "wrong_maximized"


class DriftItem(NiripModel):
    kind: DriftKind
    current: str
    desired: str


class AppResolution(NiripModel):
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    match_decision: MatchDecision
    drift: list[DriftItem]
    action_required: bool

    @computed_field
    @property
    def needs_spawn(self) -> bool:
        return self.status == ResolutionStatus.MISSING and self.action_required

    @computed_field
    @property
    def needs_move(self) -> bool:
        return any(d.kind == DriftKind.WRONG_WORKSPACE for d in self.drift)


class WorkspaceResolution(NiripModel):
    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    app_resolutions: list[AppResolution]


class Resolution(NiripModel):
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]
    unmatched_apps: list[AppResolution]
    ambiguous_apps: list[AppResolution]
    warnings: list[str]

    @computed_field
    @property
    def has_drift(self) -> bool:
        for wr in self.workspace_resolutions:
            if not wr.exists or not wr.output_correct:
                return True
            if any(ar.action_required for ar in wr.app_resolutions):
                return True
        return bool(self.unmatched_apps)

    @computed_field
    @property
    def fully_converged(self) -> bool:
        return not self.has_drift and not self.ambiguous_apps
```

**Changes from current:** All inherit `NiripModel`. `MatchDecision.best` → `assigned_window_id`.

---

### 4.2 `src/nirip/resolve/normalizer.py`

**Purpose:** `SessionSpec` → `NormalizedSession`.

```python
"""Spec normalization."""

from __future__ import annotations

from nirip.resolve.models import NormalizedApp, NormalizedSession, NormalizedWorkspace
from nirip.spec.models import SessionSpec


def normalize(spec: SessionSpec) -> NormalizedSession:
    apps: list[NormalizedApp] = []
    workspaces: list[NormalizedWorkspace] = []
    app_index: dict[str, NormalizedApp] = {}

    for ws in spec.workspaces:
        app_names: list[str] = []
        for app_spec in ws.apps:
            na = NormalizedApp(
                name=app_spec.name,
                workspace_name=ws.name,
                match=app_spec.match,
                spawn=app_spec.spawn,
                placement=app_spec.placement,
                optional=app_spec.optional,
                startup_timeout_s=(
                    app_spec.startup_timeout_s
                    or spec.options.default_startup_timeout_s
                ),
                depends_on=app_spec.depends_on,
            )
            apps.append(na)
            app_names.append(app_spec.name)
            app_index[f"{ws.name}/{app_spec.name}"] = na

        workspaces.append(NormalizedWorkspace(
            name=ws.name, output=ws.output,
            focus=ws.focus, app_names=app_names,
        ))

    return NormalizedSession(
        name=spec.name, description=spec.description,
        options=spec.options, workspaces=workspaces,
        apps=apps, app_index=app_index,
    )
```

Identical logic, updated model base.

---

### 4.3 `src/nirip/resolve/matcher.py`

**Purpose:** Rule evaluation + global window assignment (new).

```python
"""Window matching: rule evaluation and global assignment."""

from __future__ import annotations

import re
from typing import Iterable

from niri_pypc.types.generated.models import Window

from nirip.resolve.models import MatchCandidate, MatchDecision, NormalizedApp
from nirip.spec.models import MatchRule


def evaluate_rule(
    rule: MatchRule, window: Window,
) -> tuple[bool, float, list[str]]:
    """Evaluate a match rule against a window. Returns (matched, confidence, reasons)."""
    # Same algorithm as current, but on concrete Window type:
    #
    # Leaf criteria (AND-composed by default):
    #   app_id exact    → confidence 1.0
    #   app_id_regex    → confidence 0.9
    #   title exact     → confidence 0.8
    #   title_regex     → confidence 0.7
    #   pid exact       → confidence 1.0
    #
    # Composite:
    #   any_of → OR: max confidence of sub-matches
    #   not_rule → negate sub-match, inherit confidence
    #
    # AND composition: all leaf criteria must match,
    #   confidence = min of individual scores.
    ...


def assign_windows(
    apps: list[NormalizedApp],
    windows: Iterable[Window],
) -> list[MatchDecision]:
    """Globally consistent 1:1 app→window assignment.

    1. Evaluate every (app, window) pair → confidence matrix.
    2. Collect all (app_idx, window_id, confidence) triples.
    3. Sort by confidence descending.
    4. Greedy assign: highest-confidence unassigned pair wins.
    5. Key invariant: no window assigned to more than one app.
    """
    window_list = list(windows)

    # Build per-app candidate lists
    all_candidates: list[list[MatchCandidate]] = []
    for app in apps:
        candidates = []
        for w in window_list:
            matched, conf, reasons = evaluate_rule(app.match, w)
            if matched:
                candidates.append(MatchCandidate(
                    window_id=w.id, confidence=conf, reasons=reasons,
                ))
        all_candidates.append(candidates)

    # Collect and sort triples
    triples: list[tuple[int, int, float]] = []
    for app_idx, candidates in enumerate(all_candidates):
        for c in candidates:
            triples.append((app_idx, c.window_id, c.confidence))
    triples.sort(key=lambda t: t[2], reverse=True)

    # Greedy assignment
    assigned_app: set[int] = set()
    assigned_window: set[int] = set()
    app_to_window: dict[int, int] = {}

    for app_idx, window_id, confidence in triples:
        if app_idx in assigned_app or window_id in assigned_window:
            continue
        app_to_window[app_idx] = window_id
        assigned_app.add(app_idx)
        assigned_window.add(window_id)

    # Build decisions
    decisions: list[MatchDecision] = []
    for app_idx, app in enumerate(apps):
        candidates = all_candidates[app_idx]
        wid = app_to_window.get(app_idx)
        conf = 0.0
        rationale: list[str] = []

        if wid is not None:
            conf = next(c.confidence for c in candidates if c.window_id == wid)
            rationale.append(f"assigned window {wid} (confidence {conf:.2f})")
        elif candidates:
            rationale.append(
                f"{len(candidates)} candidate(s) all claimed by higher-confidence matches"
            )
        else:
            rationale.append("no matching windows found")

        decisions.append(MatchDecision(
            app_name=app.name, workspace_name=app.workspace_name,
            assigned_window_id=wid, candidates=candidates,
            confidence=conf, rationale=rationale,
        ))

    return decisions
```

**Changes from current:**
- **Removed:** `WindowLike` protocol. Uses `niri_pypc.Window` directly.
- **Removed:** `match_app()`. Replaced by `assign_windows()` (global 1:1 assignment).
- `evaluate_rule()` — same algorithm, concrete types.

**Tests:** `tests/test_matcher.py`
- All existing `evaluate_rule` tests (use Window or fakes).
- **New `assign_windows` tests:** two apps one window, invariant check, empty windows.

---

### 4.4 `src/nirip/resolve/resolver.py`

**Purpose:** `NormalizedSession` + `Snapshot` → `Resolution`.

```python
"""Session resolution against live compositor state."""

from __future__ import annotations

from niri_state import Snapshot

from nirip.resolve.matcher import assign_windows
from nirip.resolve.models import (
    AppResolution, DriftItem, DriftKind,
    NormalizedSession, Resolution, ResolutionStatus,
    WorkspaceResolution,
)


def resolve(normalized: NormalizedSession, snapshot: Snapshot) -> Resolution:
    """Resolve a normalized session against a live snapshot."""
    # 1. Build workspace name → Workspace lookup
    ws_by_name = {
        ws.name: ws for ws in snapshot.workspaces.values()
        if ws.name is not None
    }

    # 2. Global window assignment across ALL apps
    decisions = assign_windows(normalized.apps, snapshot.windows.values())
    decision_index = {
        (d.workspace_name, d.app_name): d for d in decisions
    }

    # 3. Per-workspace resolution
    workspace_resolutions = []
    unmatched = []
    ambiguous = []

    for nws in normalized.workspaces:
        live_ws = ws_by_name.get(nws.name)
        exists = live_ws is not None
        output_correct = (
            exists and (nws.output is None or live_ws.output == nws.output)
        )

        app_resolutions = []
        for app_name in nws.app_names:
            napp = normalized.app_index[f"{nws.name}/{app_name}"]
            decision = decision_index[(nws.name, app_name)]

            if decision.assigned_window_id is not None:
                window = snapshot.windows[decision.assigned_window_id]
                drift = _detect_drift(window, napp, nws.name, ws_by_name, snapshot)
                if drift:
                    status = ResolutionStatus.DRIFTED
                else:
                    status = ResolutionStatus.MATCHED
                action_required = bool(drift)
            else:
                drift = []
                if napp.optional:
                    status = ResolutionStatus.OPTIONAL_MISSING
                    action_required = False
                else:
                    status = ResolutionStatus.MISSING
                    action_required = normalized.options.launch_missing

            if decision.is_ambiguous:
                status = ResolutionStatus.AMBIGUOUS

            ar = AppResolution(
                app_name=app_name, workspace_name=nws.name,
                status=status, match_decision=decision,
                drift=drift, action_required=action_required,
            )
            app_resolutions.append(ar)

            if status == ResolutionStatus.MISSING:
                unmatched.append(ar)
            if status == ResolutionStatus.AMBIGUOUS:
                ambiguous.append(ar)

        workspace_resolutions.append(WorkspaceResolution(
            name=nws.name, exists=exists,
            output_correct=output_correct,
            desired_output=nws.output,
            current_output=live_ws.output if live_ws else None,
            app_resolutions=app_resolutions,
        ))

    return Resolution(
        session_name=normalized.name,
        workspace_resolutions=workspace_resolutions,
        unmatched_apps=unmatched,
        ambiguous_apps=ambiguous,
        warnings=[],
    )


def _detect_drift(
    window, napp, ws_name, ws_by_name, snapshot,
) -> list[DriftItem]:
    """Detect all drift between a matched window and its desired state."""
    drift = []

    # WRONG_WORKSPACE: window not on desired workspace.
    # KEY FIX: includes the case where desired workspace doesn't exist yet.
    target_ws = ws_by_name.get(ws_name)
    if target_ws is None:
        # Desired workspace doesn't exist — window is on wrong workspace by definition
        drift.append(DriftItem(
            kind=DriftKind.WRONG_WORKSPACE,
            current=str(window.workspace_id),
            desired=ws_name,
        ))
    elif window.workspace_id != target_ws.id:
        drift.append(DriftItem(
            kind=DriftKind.WRONG_WORKSPACE,
            current=str(window.workspace_id),
            desired=ws_name,
        ))

    # WRONG_FLOATING
    if window.is_floating != napp.placement.floating:
        drift.append(DriftItem(
            kind=DriftKind.WRONG_FLOATING,
            current=str(window.is_floating),
            desired=str(napp.placement.floating),
        ))

    # WRONG_FULLSCREEN
    if window.is_fullscreen != napp.placement.fullscreen:
        drift.append(DriftItem(
            kind=DriftKind.WRONG_FULLSCREEN,
            current=str(window.is_fullscreen),
            desired=str(napp.placement.fullscreen),
        ))

    # WRONG_MAXIMIZED (verify field name on Window)
    if hasattr(window, "is_maximized"):
        if window.is_maximized != napp.placement.maximized:
            drift.append(DriftItem(
                kind=DriftKind.WRONG_MAXIMIZED,
                current=str(window.is_maximized),
                desired=str(napp.placement.maximized),
            ))

    return drift
```

**Changes from current:**
- **Removed:** `SnapshotLike`, `WorkspaceLike` protocols. Uses `Snapshot`, `Window`.
- **Fixed:** `_detect_drift` checks WRONG_WORKSPACE even when target workspace doesn't exist.
- Uses `assign_windows()` for global matching.

---

## 5. Phase 4: Planning Layer

### 5.1 `src/nirip/planning/models.py`

**Purpose:** Discriminated union of typed plan steps.

All 13 step types + `PlanStep` union + `Plan` + `SessionDiff`. Full code in the refined concept document section 10.1. Key types:

```python
class StepBase(NiripModel):
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    app_name: str | None = None
    workspace_name: str | None = None

# 13 concrete step types, each with kind: Literal["..."] discriminator
# EnsureWorkspaceStep, MoveWorkspaceToOutputStep, SpawnWindowStep,
# WaitForWindowStep, MoveWindowToWorkspaceStep, SetFloatingStep,
# SetTilingStep, SetFullscreenStep, SetMaximizedStep,
# SetColumnWidthStep, SetWindowHeightStep, FocusWindowStep,
# FocusWorkspaceStep

PlanStep = Annotated[..., Discriminator("kind")]

class Plan(NiripModel):
    session_name: str
    steps: list[PlanStep]
    resolution: Resolution
    warnings: list[str] = Field(default_factory=list)
    # computed: requires_spawn, step_count, is_empty

class SessionDiff(NiripModel):
    session_name: str
    already_matched: list[str] = Field(default_factory=list)
    will_spawn: list[str] = Field(default_factory=list)
    will_move: list[str] = Field(default_factory=list)
    will_adjust: list[str] = Field(default_factory=list)
    workspace_changes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # computed: has_drift, has_errors
```

See the refined concept document section 10.1 for complete field definitions of all 13 step types. The key requirement is that each step carries exactly the data it needs:
- `SpawnWindowStep`: `command`, `cwd`, `env`, `shell` (from SpawnSpec)
- `WaitForWindowStep`: `match` (MatchRule), `timeout_s`
- `MoveWindowToWorkspaceStep`: `window_id`, `target_workspace`
- `SetFullscreenStep`: `window_id`, `fullscreen: bool`
- `SetColumnWidthStep`: `window_id`, `proportion | pixels`

---

### 5.2 `src/nirip/planning/ordering.py`

Unchanged from current. Topological sort with cycle detection. Updated type signature for `PlanStep` union.

---

### 5.3 `src/nirip/planning/compiler.py`

**Purpose:** `Resolution` + `NormalizedSession` → `Plan` / `SessionDiff`.

```python
"""Plan compilation from resolution."""

from __future__ import annotations

from nirip.planning.models import *  # all step types
from nirip.planning.ordering import topological_sort
from nirip.resolve.models import (
    DriftKind, NormalizedSession, Resolution, ResolutionStatus,
)


def compile_plan(resolution: Resolution, normalized: NormalizedSession) -> Plan:
    """Compile resolution into ordered execution plan."""
    steps: list[PlanStep] = []
    step_counter = 0

    def next_id(prefix: str) -> str:
        nonlocal step_counter
        step_counter += 1
        return f"{prefix}-{step_counter}"

    for wr in resolution.workspace_resolutions:
        ensure_id = None

        # Workspace-level steps
        if not wr.exists:
            ensure_id = next_id("ensure-ws")
            steps.append(EnsureWorkspaceStep(
                id=ensure_id,
                description=f"create workspace '{wr.name}'",
                workspace_name=wr.name,
                target_output=wr.desired_output,
            ))
        elif not wr.output_correct and wr.desired_output:
            steps.append(MoveWorkspaceToOutputStep(
                id=next_id("move-ws"),
                description=f"move workspace '{wr.name}' to {wr.desired_output}",
                workspace_name=wr.name,
                target_output=wr.desired_output,
            ))

        # Per-app steps
        for ar in wr.app_resolutions:
            napp = normalized.app_index[f"{wr.name}/{ar.app_name}"]
            deps = [ensure_id] if ensure_id else []

            if ar.needs_spawn and napp.spawn:
                spawn_id = next_id("spawn")
                steps.append(SpawnWindowStep(
                    id=spawn_id,
                    description=f"spawn {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    command=napp.spawn.command,
                    cwd=napp.spawn.cwd,
                    env=napp.spawn.env,
                    shell=napp.spawn.shell,
                    depends_on=deps,
                ))
                steps.append(WaitForWindowStep(
                    id=next_id("wait"),
                    description=f"wait for {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    match=napp.match,
                    timeout_s=napp.startup_timeout_s,
                    depends_on=[spawn_id],
                ))

            wid = ar.match_decision.assigned_window_id

            if ar.needs_move and wid is not None:
                steps.append(MoveWindowToWorkspaceStep(
                    id=next_id("move"),
                    description=f"move {ar.app_name} to '{wr.name}'",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    window_id=wid,
                    target_workspace=wr.name,
                    depends_on=deps,
                ))

            # Placement drift steps
            if wid is not None:
                for d in ar.drift:
                    if d.kind == DriftKind.WRONG_FLOATING:
                        if napp.placement.floating:
                            steps.append(SetFloatingStep(
                                id=next_id("float"), window_id=wid,
                                description=f"set {ar.app_name} floating",
                                app_name=ar.app_name, workspace_name=wr.name,
                            ))
                        else:
                            steps.append(SetTilingStep(
                                id=next_id("tile"), window_id=wid,
                                description=f"set {ar.app_name} tiling",
                                app_name=ar.app_name, workspace_name=wr.name,
                            ))
                    elif d.kind == DriftKind.WRONG_FULLSCREEN:
                        steps.append(SetFullscreenStep(
                            id=next_id("fs"), window_id=wid,
                            fullscreen=napp.placement.fullscreen,
                            description=f"set {ar.app_name} fullscreen={napp.placement.fullscreen}",
                            app_name=ar.app_name, workspace_name=wr.name,
                        ))
                    elif d.kind == DriftKind.WRONG_MAXIMIZED:
                        steps.append(SetMaximizedStep(
                            id=next_id("max"), window_id=wid,
                            maximized=napp.placement.maximized,
                            description=f"set {ar.app_name} maximized={napp.placement.maximized}",
                            app_name=ar.app_name, workspace_name=wr.name,
                        ))

            # Column width / window height (for matched or post-wait windows)
            if wid is not None and napp.placement.column_width is not None:
                prop, px = _parse_size(napp.placement.column_width)
                steps.append(SetColumnWidthStep(
                    id=next_id("cw"), window_id=wid,
                    proportion=prop, pixels=px,
                    description=f"set column width for {ar.app_name}",
                    app_name=ar.app_name, workspace_name=wr.name,
                ))

            if wid is not None and napp.placement.window_height is not None:
                prop, px = _parse_size(napp.placement.window_height)
                steps.append(SetWindowHeightStep(
                    id=next_id("wh"), window_id=wid,
                    proportion=prop, pixels=px,
                    description=f"set window height for {ar.app_name}",
                    app_name=ar.app_name, workspace_name=wr.name,
                ))

            # Focus
            if wid is not None and napp.placement.focus:
                steps.append(FocusWindowStep(
                    id=next_id("focus"), window_id=wid,
                    description=f"focus {ar.app_name}",
                    app_name=ar.app_name, workspace_name=wr.name,
                ))

    # Workspace focus
    for nws in normalized.workspaces:
        if nws.focus:
            steps.append(FocusWorkspaceStep(
                id=next_id("focus-ws"),
                description=f"focus workspace '{nws.name}'",
                workspace_name=nws.name,
            ))

    steps = topological_sort(steps)

    return Plan(
        session_name=resolution.session_name,
        steps=steps,
        resolution=resolution,
    )


def _parse_size(value: float | str) -> tuple[float | None, int | None]:
    """Parse column_width / window_height from spec format."""
    if isinstance(value, (int, float)):
        return (float(value), None)  # proportion
    if isinstance(value, str) and value.startswith("px:"):
        return (None, int(value[3:]))
    return (float(value), None)


def compile_diff(resolution: Resolution) -> SessionDiff:
    """Human-readable diff from resolution."""
    # Walk resolution, classify apps into categories.
    # Unchanged logic from current implementation.
    ...
```

**Changes from current:**
- **`compile_plan` takes `normalized` parameter** — accesses SpawnSpec, MatchRule, PlacementSpec.
- Emits typed step objects with all required data.
- Handles `column_width`, `window_height`, focus steps.
- `depends_on` from AppSpec would be honored (TODO: add cross-app dependency wiring using the topological sort).

---

## 6. Phase 5: Execution Layer

### 6.1 `src/nirip/execution/models.py`

```python
"""Execution layer models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import computed_field

from niri_pypc import NiriClient
from niri_state import NiriState

from nirip._base import NiripModel
from nirip.planning.models import PlanStep


class StepOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class StepResult(NiripModel):
    step: PlanStep
    outcome: StepOutcome
    message: str
    window_id: int | None = None
    duration_s: float = 0.0


class ApplyResult(NiripModel):
    session_name: str
    success: bool
    steps: list[StepResult]
    total_duration_s: float

    @computed_field
    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.COMPLETED)

    @computed_field
    @property
    def skipped_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.SKIPPED)

    @computed_field
    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps
                if s.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT)]


@dataclass
class SessionPorts:
    """Runtime services for session execution."""
    state: NiriState
    client: NiriClient
```

**Removed:** `ActionClient` protocol, `StepAction`. **New:** `SessionPorts` dataclass.

---

### 6.2 `src/nirip/execution/runtime.py`

Mutable per-app tracking during execution. Uses `BaseModel` with `frozen=False`:

```python
"""Ephemeral execution tracking state."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AppRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    app_name: str
    workspace_name: str
    matched_window_id: int | None = None
    spawned: bool = False
    spawn_pid: int | None = None
    completed: bool = False
    error: str | None = None


class SessionRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    session_name: str
    apps: dict[str, AppRuntimeState] = Field(default_factory=dict)
    started_at: float | None = None
```

---

### 6.3 `src/nirip/execution/predicates.py`

Skip-check predicates using concrete `Snapshot`:

```python
"""Skip-check predicates for plan steps."""

from __future__ import annotations

from niri_state import Snapshot

from nirip.planning.models import *


def is_already_satisfied(step: PlanStep, snapshot: Snapshot) -> bool:
    match step:
        case EnsureWorkspaceStep():
            return any(ws.name == step.workspace_name
                       for ws in snapshot.workspaces.values())
        case MoveWindowToWorkspaceStep():
            w = snapshot.windows.get(step.window_id)
            if w is None:
                return False
            target = next((ws for ws in snapshot.workspaces.values()
                           if ws.name == step.target_workspace), None)
            return target is not None and w.workspace_id == target.id
        case SetFloatingStep():
            w = snapshot.windows.get(step.window_id)
            return w is not None and w.is_floating
        case SetTilingStep():
            w = snapshot.windows.get(step.window_id)
            return w is not None and not w.is_floating
        case SetFullscreenStep():
            w = snapshot.windows.get(step.window_id)
            return w is not None and w.is_fullscreen == step.fullscreen
        case SetMaximizedStep():
            w = snapshot.windows.get(step.window_id)
            return w is not None and getattr(w, "is_maximized", False) == step.maximized
        case _:
            return False
```

---

### 6.4 `src/nirip/execution/handlers.py`

Per-step execution calling `niri_pypc.actions.*` directly. Each handler:
1. Checks `is_already_satisfied` → SKIPPED
2. Builds action via `actions.*` builder
3. Sends via `ports.client.request(action)`
4. Optionally waits via `wait_until()` for verification
5. Returns `StepResult`

Full implementation for all 13 step types. Key patterns:

```python
async def execute_step(step, ports, runtime) -> StepResult:
    if is_already_satisfied(step, ports.state.snapshot):
        return StepResult(step=step, outcome=StepOutcome.SKIPPED, message="already satisfied")
    match step:
        case EnsureWorkspaceStep(): ...     # actions.focus_workspace(name)
        case SpawnWindowStep(): ...          # asyncio.create_subprocess_exec
        case WaitForWindowStep(): ...        # wait_until + evaluate_rule
        case MoveWindowToWorkspaceStep(): ...# actions.move_window_to_workspace
        case SetFloatingStep(): ...          # actions.move_window_to_floating
        case SetTilingStep(): ...            # actions.move_window_to_tiling
        case SetFullscreenStep(): ...        # actions.fullscreen_window (toggle)
        case SetMaximizedStep(): ...         # actions.maximize_window_to_edges
        case SetColumnWidthStep(): ...       # actions.focus_window + actions.set_column_width
        case SetWindowHeightStep(): ...      # actions.set_window_height
        case FocusWindowStep(): ...          # actions.focus_window
        case FocusWorkspaceStep(): ...       # actions.focus_workspace
        case MoveWorkspaceToOutputStep(): ...# actions.move_workspace_to_monitor
```

**Spawn handler** uses `asyncio.create_subprocess_exec` for PID tracking. **Wait handler** uses `niri_state.api.waiters.wait_until()` with `WaitTimeoutError` catch.

---

### 6.5 `src/nirip/execution/executor.py`

```python
"""Plan executor."""

from __future__ import annotations

import time

from nirip.execution.handlers import execute_step
from nirip.execution.models import ApplyResult, SessionPorts, StepOutcome
from nirip.execution.runtime import AppRuntimeState, SessionRuntime
from nirip.planning.models import Plan
from nirip.spec.models import SessionOptions


async def execute_plan(
    plan: Plan, ports: SessionPorts, options: SessionOptions,
) -> ApplyResult:
    t0 = time.monotonic()
    runtime = SessionRuntime(session_name=plan.session_name, started_at=t0)

    for step in plan.steps:
        if step.app_name and step.app_name not in runtime.apps:
            runtime.apps[step.app_name] = AppRuntimeState(
                app_name=step.app_name,
                workspace_name=step.workspace_name or "",
            )

    results = []
    for step in plan.steps:
        try:
            result = await execute_step(step, ports, runtime)
        except Exception as e:
            result = StepResult(
                step=step, outcome=StepOutcome.FAILED,
                message=str(e), duration_s=time.monotonic() - t0,
            )
        results.append(result)
        if result.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT):
            if options.stop_on_error:
                break

    return ApplyResult(
        session_name=plan.session_name,
        success=all(r.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED)
                     for r in results),
        steps=results,
        total_duration_s=time.monotonic() - t0,
    )
```

Standalone async function, not a class. Takes `SessionPorts` with real connections.

---

## 7. Phase 6: Capture Layer

### 7.1 `src/nirip/capture/inference.py`

```python
"""Infer match rules and app names from live windows."""

from __future__ import annotations

from niri_pypc.types.generated.models import Window

from nirip.spec.models import MatchRule


def infer_app_name(window: Window, fallback_prefix: str = "app") -> str:
    if window.app_id:
        return window.app_id.rsplit(".", 1)[-1].lower().replace(" ", "-")
    if window.title:
        return window.title.lower().replace(" ", "-")[:30]
    return f"{fallback_prefix}-{window.id}"


def infer_match_rule(window: Window) -> MatchRule:
    if window.app_id:
        return MatchRule(app_id=window.app_id)
    if window.title:
        return MatchRule(title=window.title)
    return MatchRule(title=f"window-{window.id}")
```

Uses concrete `Window`. Otherwise identical to current.

---

### 7.2 `src/nirip/capture/capturer.py`

```python
"""Capture current state as a session scaffold."""

from __future__ import annotations

from pydantic import computed_field

from niri_state import Snapshot
from niri_state.api.selectors import windows, workspaces

from nirip._base import NiripModel
from nirip.capture.inference import infer_app_name, infer_match_rule
from nirip.spec.models import AppSpec, SessionSpec, WorkspaceSpec


class CapturedSession(NiripModel):
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


def capture_from_snapshot(
    snapshot: Snapshot, *, name: str | None = None,
) -> CapturedSession:
    workspace_specs = []
    notes = []

    for ws in workspaces.list_workspaces(snapshot):
        if ws.name is None:
            notes.append(f"skipped unnamed workspace (id={ws.id})")
            continue
        apps = []
        for w in windows.list_windows_on_workspace(snapshot, ws.id):
            apps.append(AppSpec(
                name=infer_app_name(w),
                match=infer_match_rule(w),
            ))
        workspace_specs.append(WorkspaceSpec(
            name=ws.name, output=ws.output, apps=apps,
        ))

    notes.append("Add spawn commands for apps you want auto-launched")
    notes.append("Refine match rules for more reliable matching")

    return CapturedSession(
        spec=SessionSpec(name=name or "captured", workspaces=workspace_specs),
        notes=notes,
    )
```

Uses `niri_state.api.selectors` instead of manual iteration.

---

## 8. Phase 7: Facade Layer

### 8.1 `src/nirip/facade/async_nirip.py`

```python
"""Primary async API."""

from __future__ import annotations

from typing import Any

from niri_pypc import NiriClient
from niri_state import HealthState, NiriState, Snapshot

from nirip.capture.capturer import CapturedSession, capture_from_snapshot
from nirip.config import NiripConfig
from nirip.execution.executor import execute_plan
from nirip.execution.models import ApplyResult, SessionPorts
from nirip.planning.compiler import compile_diff, compile_plan
from nirip.planning.models import Plan, SessionDiff
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.models import SessionSpec


class AsyncNirip:
    """Async API owning real NiriState + NiriClient connections."""

    def __init__(
        self, *, state: NiriState, client: NiriClient,
        config: NiripConfig | None = None,
    ) -> None:
        self._state = state
        self._client = client
        self._config = config or NiripConfig()

    @classmethod
    async def open(cls, config: NiripConfig | None = None) -> AsyncNirip:
        state = await NiriState.open()
        client = NiriClient.create()
        return cls(state=state, client=client, config=config)

    @property
    def snapshot(self) -> Snapshot:
        return self._state.snapshot

    @property
    def health(self) -> HealthState:
        return self._state.health()

    async def diff(self, spec: SessionSpec) -> SessionDiff:
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        return compile_diff(resolution)

    async def plan(self, spec: SessionSpec) -> Plan:
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        return compile_plan(resolution, normalized)

    async def apply(self, spec: SessionSpec) -> ApplyResult:
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        plan = compile_plan(resolution, normalized)
        if plan.is_empty:
            return ApplyResult(
                session_name=spec.name, success=True,
                steps=[], total_duration_s=0.0,
            )
        ports = SessionPorts(state=self._state, client=self._client)
        return await execute_plan(plan, ports, spec.options)

    async def capture(self, *, name: str | None = None) -> CapturedSession:
        return capture_from_snapshot(self.snapshot, name=name)

    async def close(self) -> None:
        await self._state.close()
        await self._client.close()

    async def __aenter__(self) -> AsyncNirip:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
```

**Key change:** Owns real connections. No `bind_snapshot()`. `apply()` actually executes.

---

### 8.2 `src/nirip/facade/sync_nirip.py`

```python
"""Synchronous wrapper."""

from __future__ import annotations

import asyncio
from typing import Any

from niri_pypc import NiriClient
from niri_state import NiriState

from nirip.capture.capturer import CapturedSession
from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.planning.models import Plan, SessionDiff
from nirip.spec.models import SessionSpec


class SyncNirip:
    def __init__(
        self, *, state: NiriState, client: NiriClient,
        config: NiripConfig | None = None,
    ) -> None:
        self._async = AsyncNirip(state=state, client=client, config=config)

    @classmethod
    def open(cls, config: NiripConfig | None = None) -> SyncNirip:
        state = asyncio.run(NiriState.open())
        client = NiriClient.create()
        return cls(state=state, client=client, config=config)

    def diff(self, spec: SessionSpec) -> SessionDiff:
        return asyncio.run(self._async.diff(spec))

    def plan(self, spec: SessionSpec) -> Plan:
        return asyncio.run(self._async.plan(spec))

    def apply(self, spec: SessionSpec) -> ApplyResult:
        return asyncio.run(self._async.apply(spec))

    def capture(self, *, name: str | None = None) -> CapturedSession:
        return asyncio.run(self._async.capture(name=name))

    def close(self) -> None:
        asyncio.run(self._async.close())

    def __enter__(self) -> SyncNirip:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
```

---

## 9. Phase 8: CLI Layer

### 9.1 `src/nirip/cli/main.py`

```python
"""CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nirip", description="Niri session manager")
    sub = parser.add_subparsers(dest="command")

    p_apply = sub.add_parser("apply", help="Apply a session spec")
    p_apply.add_argument("session_file")
    p_apply.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    p_diff = sub.add_parser("diff", help="Show what would change")
    p_diff.add_argument("session_file")

    p_plan = sub.add_parser("plan", help="Show execution plan")
    p_plan.add_argument("session_file")

    p_capture = sub.add_parser("capture", help="Capture current state")
    p_capture.add_argument("-o", "--output", help="Write to file")
    p_capture.add_argument("-n", "--name", help="Session name")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    from nirip.cli.commands import cmd_apply, cmd_capture, cmd_diff, cmd_plan

    try:
        if args.command == "apply":
            output = asyncio.run(cmd_apply(args.session_file, yes=args.yes))
        elif args.command == "diff":
            output = asyncio.run(cmd_diff(args.session_file))
        elif args.command == "plan":
            output = asyncio.run(cmd_plan(args.session_file))
        elif args.command == "capture":
            output = asyncio.run(cmd_capture(name=args.name, output=args.output))
        else:
            parser.print_help()
            return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(output)
    return 0
```

---

### 9.2 `src/nirip/cli/commands.py`

```python
"""CLI command handlers."""

from __future__ import annotations

import sys

import yaml

from nirip.facade.async_nirip import AsyncNirip
from nirip.spec.loader import load_spec_from_file


async def cmd_apply(session_file: str, *, yes: bool = False) -> str:
    validated = load_spec_from_file(session_file)
    for w in validated.validation.warnings:
        print(f"  warning: {w}", file=sys.stderr)

    async with await AsyncNirip.open() as nirip:
        if not yes:
            diff = await nirip.diff(validated.spec)
            text = yaml.dump(diff.model_dump(), default_flow_style=False)
            print(text, file=sys.stderr)
            if diff.has_drift:
                answer = input("Apply? [y/N] ")
                if answer.lower() != "y":
                    return "aborted"

        result = await nirip.apply(validated.spec)
        return yaml.dump(result.model_dump(), default_flow_style=False)


async def cmd_diff(session_file: str) -> str:
    validated = load_spec_from_file(session_file)
    async with await AsyncNirip.open() as nirip:
        diff = await nirip.diff(validated.spec)
        return yaml.dump(diff.model_dump(), default_flow_style=False)


async def cmd_plan(session_file: str) -> str:
    validated = load_spec_from_file(session_file)
    async with await AsyncNirip.open() as nirip:
        plan = await nirip.plan(validated.spec)
        return yaml.dump(plan.model_dump(), default_flow_style=False)


async def cmd_capture(
    *, name: str | None = None, output: str | None = None,
) -> str:
    async with await AsyncNirip.open() as nirip:
        captured = await nirip.capture(name=name)
        text = yaml.dump(captured.spec.model_dump(), default_flow_style=False)
        if output:
            from pathlib import Path
            Path(output).write_text(text, encoding="utf-8")
        return text
```

All commands use `AsyncNirip.open()` for real compositor connection. Warnings displayed.

---

## 10. Phase 9: Package Exports

### 10.1 `src/nirip/__init__.py`

```python
"""nirip: Declarative session reconciler for Niri."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.facade.sync_nirip import SyncNirip
from nirip.spec.loader import load_spec_from_dict, load_spec_from_file, load_spec_from_string
from nirip.spec.models import SessionSpec
from nirip.spec.validators import ValidatedSpec

__all__ = [
    "ApplyResult", "AsyncNirip", "NiripConfig",
    "SessionSpec", "SyncNirip", "ValidatedSpec",
    "apply_session", "load_session",
    "load_spec_from_dict", "load_spec_from_file", "load_spec_from_string",
]


def load_session(path: str | Path) -> ValidatedSpec:
    return load_spec_from_file(path)


def apply_session(spec: SessionSpec) -> ApplyResult:
    async def _run() -> ApplyResult:
        async with await AsyncNirip.open() as nirip:
            return await nirip.apply(spec)
    return asyncio.run(_run())
```

### 10.2 `src/nirip/__main__.py`

```python
from nirip.cli.main import main
main()
```

### 10.3 Subpackage `__init__.py` files

Each subpackage re-exports its key symbols:

| Package | Exports |
|---|---|
| `spec/` | `SessionSpec, MatchRule, SpawnSpec, PlacementSpec, AppSpec, WorkspaceSpec, SessionOptions, ValidatedSpec` |
| `resolve/` | `normalize, resolve, Resolution, NormalizedSession` |
| `planning/` | `compile_plan, compile_diff, Plan, SessionDiff, PlanStep` |
| `execution/` | `execute_plan, ApplyResult, StepResult, SessionPorts` |
| `capture/` | `capture_from_snapshot, CapturedSession` |
| `facade/` | `AsyncNirip, SyncNirip` |
| `cli/` | `main` |

---

## 11. Phase 10: Tests

### Test infrastructure — `tests/conftest.py`

```python
"""Shared test fakes and fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeWindow:
    """Minimal window fake for matcher/resolver tests."""
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
    """Minimal snapshot fake for resolver tests."""
    windows: dict[int, FakeWindow] = field(default_factory=dict)
    workspaces: dict[int, FakeWorkspace] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    focused_window_id: int | None = None
    focused_workspace_id: int | None = None


class RecordingClient:
    """Records action requests for assertion."""
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
```

**Important implementation note:** The `evaluate_rule` function and `resolve` function currently accept `WindowLike`/`SnapshotLike` protocols, which these fakes satisfy. In the rewrite, these functions accept concrete `Window`/`Snapshot` types. There are two approaches for testing:

1. **Use real types:** Construct actual `Window`, `Workspace`, `Snapshot` instances from niri-pypc/niri-state. This is more correct but requires understanding their constructors.
2. **Use structural typing:** Python's `match` and attribute access work with any object that has the right attributes. The fakes above will work with `evaluate_rule` if it accesses `.id`, `.app_id`, `.title`, etc. through attribute access (not isinstance checks).

**Recommended:** Start with fakes. If type checkers complain, add `# type: ignore` or create proper factory functions that construct real instances.

### Test file inventory

| File | What it tests | Status |
|---|---|---|
| `tests/test_base.py` | NiripModel base class | **New** |
| `tests/test_errors.py` | Error hierarchy | Update |
| `tests/test_config.py` | NiripConfig | Update |
| `tests/test_spec_models.py` | All spec models | Update |
| `tests/test_spec_loader.py` | YAML loading | Update (ValidatedSpec) |
| `tests/test_spec_validators.py` | Validation | Update (warnings) |
| `tests/test_spec_defaults.py` | Default merging | Unchanged |
| `tests/test_normalizer.py` | Normalization | Unchanged |
| `tests/test_matcher.py` | Rule eval + global assignment | **Major update** |
| `tests/test_resolver.py` | Resolution + drift | **Major update** |
| `tests/test_planning_models.py` | Discriminated union | **New** |
| `tests/test_compiler.py` | Plan compilation | **Major update** |
| `tests/test_ordering.py` | Topological sort | Unchanged |
| `tests/test_executor.py` | Execution with fakes | **Rewrite** |
| `tests/test_capturer.py` | Capture | Update |
| `tests/test_integration.py` | Full pipeline | **Rewrite** |

### Key new test cases

**`test_matcher.py` — global assignment:**
- Two apps, two windows, unambiguous → each gets its window.
- Two apps, one window → higher-confidence app wins.
- **Invariant:** no `assigned_window_id` appears twice across decisions.
- Zero windows → all apps unassigned.

**`test_resolver.py` — missing workspace drift:**
- Window matched but desired workspace doesn't exist → DRIFTED with WRONG_WORKSPACE.
- Window on correct workspace → MATCHED (no drift).

**`test_compiler.py` — data propagation:**
- SpawnWindowStep carries command/cwd/env/shell from SpawnSpec.
- WaitForWindowStep carries match rule and timeout.
- Focus steps emitted when placement.focus=True.
- SetColumnWidthStep emitted when column_width is set.

**`test_executor.py` — recording client:**
- Steps send correct `ActionRequest` types to `RecordingClient`.
- Skip-check prevents redundant actions.
- WaitTimeoutError → StepOutcome.TIMED_OUT.
- stop_on_error halts execution.

---

## 12. Files to Delete

| File | Reason |
|---|---|
| `src/nirip/execution/actions.py` | `StepAction` and `action_for_step()` replaced by direct `niri_pypc.actions.*` calls in `handlers.py`. |

All other files are rewritten in place. No other deletions.

---

## 13. Dependency Import Map

Where each external symbol is imported in the nirip codebase:

```
niri_pypc.NiriClient              → execution/models.py, facade/async_nirip.py, facade/sync_nirip.py
niri_pypc.actions.*               → execution/handlers.py (all builders)
niri_pypc.actions.workspace_by_name → execution/handlers.py
niri_pypc.actions.size_set_proportion → execution/handlers.py
niri_pypc.actions.size_set_fixed  → execution/handlers.py
niri_pypc.types.generated.models.Window → resolve/matcher.py, resolve/resolver.py, capture/inference.py
niri_pypc.types.generated.models.Workspace → (accessed via Snapshot, not imported separately)
niri_pypc.types.generated.request.ActionRequest → (type annotations only)

niri_state.NiriState              → execution/models.py, facade/async_nirip.py, facade/sync_nirip.py
niri_state.Snapshot               → resolve/resolver.py, execution/predicates.py, capture/capturer.py
niri_state.HealthState            → facade/async_nirip.py
niri_state.WaitTimeoutError       → execution/handlers.py
niri_state.api.waiters.wait_until → execution/handlers.py
niri_state.api.selectors.windows  → capture/capturer.py
niri_state.api.selectors.workspaces → capture/capturer.py

asyncio                           → execution/handlers.py (create_subprocess_exec)
os                                → execution/handlers.py (environ)
time                              → execution/handlers.py, execution/executor.py
re                                → resolve/matcher.py, spec/validators.py
yaml                              → spec/loader.py, cli/commands.py
```

### Internal dependency graph (nirip modules)

```
_base.py ← errors.py, config.py
    ↑
spec/models.py ← spec/validators.py ← spec/defaults.py ← spec/loader.py
    ↑
resolve/models.py ← resolve/normalizer.py ← resolve/matcher.py ← resolve/resolver.py
    ↑
planning/models.py ← planning/ordering.py ← planning/compiler.py
    ↑
execution/models.py ← execution/runtime.py ← execution/predicates.py ← execution/handlers.py ← execution/executor.py
    ↑
capture/inference.py ← capture/capturer.py
    ↑
facade/async_nirip.py ← facade/sync_nirip.py
    ↑
cli/commands.py ← cli/main.py
    ↑
__init__.py
```

No circular dependencies. Each layer depends only on layers below it.
