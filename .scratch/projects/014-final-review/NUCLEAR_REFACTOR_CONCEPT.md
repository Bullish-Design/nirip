# Nuclear Refactor Concept

**Goal:** Reduce nirip from 41 files / 2,316 LOC to 6 files / ~1,500 LOC with zero functionality loss. Every file is readable top-to-bottom in one sitting. Any operation traces through at most 2 files.

---

## Target File Structure

```
src/nirip/
├── __init__.py      # Public API (~60 LOC)
├── spec.py          # Models + validation + YAML loading (~300 LOC)
├── resolve.py       # Matching + drift detection + resolution (~300 LOC)
├── plan.py          # Step generation + ordering (~350 LOC)
├── execute.py       # Async execution engine (~300 LOC)
├── capture.py       # Snapshot → spec template (~70 LOC)
└── cli.py           # Argparse + commands + formatting (~180 LOC)
```

Plus one extension point kept separate:
```
├── hooks.py         # ExecutionHook protocol + LoggingHook (~40 LOC)
```

---

## What Gets Deleted

| Thing | Lines | Reason |
|-------|-------|--------|
| `_base.py` | 18 | Inline `model_config` on each model (1 line) |
| `config.py` (`NiripConfig`) | 14 | Dead code — no field is ever read |
| `errors.py` (5 of 7 classes) | 30 | Keep `NiripError` + `ValidationError` only |
| `WindowAssigner` protocol | 10 | One implementation, never swapped |
| `GreedyAssigner` class | 36 | Becomes 15 lines inline in `resolve.py` |
| `MatchCandidate` model | 4 | Becomes a local tuple |
| `MatchDecision` model | 20 | Absorbed into `AppResolution` fields |
| `SessionDiff` model | 26 | Formatting produces strings directly from Resolution |
| `CapturedSession` wrapper | 14 | Return `SessionSpec` directly |
| 12 `__init__.py` re-exports | ~80 | No packages = no re-exports |
| `computed_field` decorators | ~40 | Replace with `@property` or inline calls |
| `compile_diff()` function | 28 | Logic moves to CLI formatting |

**Total deleted:** ~330 lines of boilerplate/indirection.

---

## File 1: `spec.py` (~300 LOC)

### Currently: 4 files
- `spec/models.py` (93 LOC)
- `spec/validators.py` (160 LOC)
- `spec/loader.py` (44 LOC)
- `spec/__init__.py` (15 LOC)

### Structure

```python
"""Session specification: models, validation, and YAML loading."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ─── Models ──────────────────────────────────────────────────────────────────

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class MatchRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    app_id: str | None = None
    app_id_regex: str | None = None
    title: str | None = None
    title_regex: str | None = None
    pid: int | None = None
    any_of: list[MatchRule] | None = Field(None, validation_alias="any")
    not_rule: MatchRule | None = Field(None, validation_alias="not")

    @model_validator(mode="after")
    def _validate_not_empty(self) -> MatchRule:
        has_leaf = any([self.app_id, self.app_id_regex, self.title, self.title_regex, self.pid is not None])
        has_composite = self.any_of is not None or self.not_rule is not None
        if not has_leaf and not has_composite:
            raise ValueError("MatchRule must have at least one criterion")
        return self


class SpawnSpec(BaseModel):
    model_config = _FROZEN
    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False


class PlacementSpec(BaseModel):
    model_config = _FROZEN
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


class AppSpec(BaseModel):
    model_config = _FROZEN
    name: str
    match: MatchRule
    spawn: SpawnSpec | None = None
    placement: PlacementSpec = Field(default_factory=PlacementSpec)
    optional: bool = False
    startup_timeout_s: float | None = None
    depends_on: list[str] = Field(default_factory=list)


class WorkspaceSpec(BaseModel):
    model_config = _FROZEN
    name: str
    output: str | None = None
    focus: bool = False
    apps: list[AppSpec] = Field(default_factory=list)


class SessionOptions(BaseModel):
    model_config = _FROZEN
    launch_missing: bool = True
    stop_on_error: bool = True
    default_startup_timeout_s: float = 20.0


class SessionSpec(BaseModel):
    model_config = _FROZEN
    name: str
    description: str = ""
    options: SessionOptions = Field(default_factory=SessionOptions)
    workspaces: list[WorkspaceSpec]


# ─── Validation ──────────────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    model_config = _FROZEN
    valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_session(spec: SessionSpec) -> ValidationResult:
    """Run all checks. Never raises — problems reported in result."""
    errors: list[str] = []
    warnings: list[str] = []
    _check_unique_workspace_names(spec, errors)
    _check_unique_app_names(spec, errors)
    _check_depends_on_refs(spec, errors)
    _check_regex_patterns(spec, errors)
    _check_weak_matchers(spec, warnings)
    _check_inter_app_conflicts(spec, warnings)
    _check_spawn_commands(spec, errors)
    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _check_unique_workspace_names(spec, errors): ...
def _check_unique_app_names(spec, errors): ...
def _check_depends_on_refs(spec, errors): ...  # includes cycle detection
def _check_regex_patterns(spec, errors): ...
def _check_weak_matchers(spec, warnings): ...
def _check_inter_app_conflicts(spec, warnings): ...
def _check_spawn_commands(spec, errors): ...


# ─── Loading ─────────────────────────────────────────────────────────────────

class NiripError(Exception):
    """Base for all nirip errors."""

class ValidationError(NiripError):
    """Spec validation failed."""
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__(f"{len(errors)} error(s): {'; '.join(errors[:3])}")


def load_from_file(path: str | Path) -> tuple[SessionSpec, ValidationResult]:
    p = Path(path)
    if not p.exists():
        raise NiripError(f"file not found: {p}")
    return load_from_string(p.read_text(encoding="utf-8"), source=str(p))


def load_from_string(text: str, *, source: str = "<string>") -> tuple[SessionSpec, ValidationResult]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise NiripError(f"YAML parse error in {source}: {e}") from e
    if not isinstance(data, dict):
        raise NiripError(f"expected mapping in {source}, got {type(data).__name__}")
    return load_from_dict(data, source=source)


def load_from_dict(data: dict[str, Any], *, source: str = "<dict>") -> tuple[SessionSpec, ValidationResult]:
    try:
        spec = SessionSpec.model_validate(data)
    except Exception as e:
        raise NiripError(f"spec parse error in {source}: {e}") from e
    validation = validate_session(spec)
    if not validation.valid:
        raise ValidationError(validation.errors, validation.warnings)
    return spec, validation
```

**Key changes from current:**
- No `ValidatedSpec` wrapper — return a tuple `(spec, validation)` or just the spec (validation passed if no exception)
- Errors defined here, not in a separate file (they're only raised here)
- `_FROZEN` config shared via module-level constant, no base class import

---

## File 2: `resolve.py` (~300 LOC)

### Currently: 5 files
- `resolve/models.py` (144 LOC)
- `resolve/resolver.py` (122 LOC)
- `resolve/matcher.py` (139 LOC)
- `resolve/assigner.py` (36 LOC)
- `resolve/__init__.py` (7 LOC)

### Structure

```python
"""Window matching, assignment, and resolution against live state."""
from __future__ import annotations

import re
from collections.abc import Iterable
from enum import IntEnum, StrEnum
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from niri_pypc.types.generated.models import Window, Workspace
from niri_state import Snapshot

from nirip.spec import AppSpec, MatchRule, SessionSpec

_FROZEN = ConfigDict(extra="forbid", frozen=True)


# ─── Types ───────────────────────────────────────────────────────────────────

class MatchTier(IntEnum):
    NONE = 0
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    EXACT = 4


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
    window_id: int | None = None       # assigned window (was in MatchDecision)
    is_ambiguous: bool = False          # was computed_field on MatchDecision
    drift: list[DriftItem]
    spec: AppSpec
    startup_timeout_s: float

    @property
    def needs_move(self) -> bool:
        return any(d.kind == DriftKind.WRONG_WORKSPACE for d in self.drift)


class WorkspaceState(BaseModel):
    """Workspace-level facts (not a container for apps)."""
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
    apps: list[AppResolution]           # FLAT list — not nested
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
    """Evaluate a match rule against a window. Returns (matched, tier)."""
    best_tier = MatchTier.NONE
    failed = False

    if rule.app_id is not None:
        if window.app_id == rule.app_id:
            best_tier = max(best_tier, MatchTier.EXACT)
        else:
            failed = True

    if rule.app_id_regex is not None:
        if window.app_id and _compile(rule.app_id_regex).search(window.app_id):
            best_tier = max(best_tier, MatchTier.STRONG)
        else:
            failed = True

    if rule.title is not None:
        if window.title == rule.title:
            best_tier = max(best_tier, MatchTier.MODERATE)
        else:
            failed = True

    if rule.title_regex is not None:
        if window.title and _compile(rule.title_regex).search(window.title):
            best_tier = max(best_tier, MatchTier.WEAK)
        else:
            failed = True

    if rule.pid is not None:
        if getattr(window, "pid", None) == rule.pid:
            best_tier = max(best_tier, MatchTier.EXACT)
        else:
            failed = True

    if rule.any_of:
        any_match = [evaluate_rule(sub, window) for sub in rule.any_of if evaluate_rule(sub, window)[0]]
        if any_match:
            best_tier = max(best_tier, max(r[1] for r in any_match))
        else:
            failed = True

    if rule.not_rule:
        if evaluate_rule(rule.not_rule, window)[0]:
            failed = True

    if failed:
        return False, MatchTier.NONE
    return True, max(best_tier, MatchTier.WEAK)


# ─── Assignment (greedy, inlined) ────────────────────────────────────────────

def _assign(
    apps: list[tuple[str, AppSpec]],
    windows: Iterable[Window],
) -> list[tuple[int | None, bool]]:
    """Greedy 1:1 assignment. Returns (window_id, is_ambiguous) per app."""
    window_list = list(windows)

    # Build candidates: list of (app_idx, window_id, tier) for all matches
    candidates_per_app: list[list[tuple[int, MatchTier]]] = []
    triples: list[tuple[int, int, MatchTier]] = []

    for app_idx, (_ws, app_spec) in enumerate(apps):
        app_candidates = []
        for w in window_list:
            matched, tier = evaluate_rule(app_spec.match, w)
            if matched:
                app_candidates.append((w.id, tier))
                triples.append((app_idx, w.id, tier))
        candidates_per_app.append(app_candidates)

    # Greedy: sort by tier descending, assign first-come-first-served
    triples.sort(key=lambda t: t[2], reverse=True)
    assigned_app: set[int] = set()
    assigned_window: set[int] = set()
    result_map: dict[int, int] = {}

    for app_idx, window_id, _tier in triples:
        if app_idx in assigned_app or window_id in assigned_window:
            continue
        result_map[app_idx] = window_id
        assigned_app.add(app_idx)
        assigned_window.add(window_id)

    # Build results with ambiguity detection
    results: list[tuple[int | None, bool]] = []
    for app_idx, candidates in enumerate(candidates_per_app):
        wid = result_map.get(app_idx)
        is_ambiguous = False
        if len(candidates) >= 2:
            tiers = [t for _, t in candidates]
            top = max(tiers)
            is_ambiguous = sum(1 for t in tiers if t == top) > 1
        results.append((wid, is_ambiguous))

    return results


# ─── Resolution ──────────────────────────────────────────────────────────────

_PROPERTY_CHECKS: list[tuple[DriftKind, str, str]] = [
    (DriftKind.WRONG_FLOATING, "is_floating", "floating"),
    (DriftKind.WRONG_FULLSCREEN, "is_fullscreen", "fullscreen"),
    (DriftKind.WRONG_MAXIMIZED, "is_maximized", "maximized"),
]


def resolve(spec: SessionSpec, snapshot: Snapshot) -> Resolution:
    """Resolve a session spec against a live compositor snapshot."""
    ws_by_name = {ws.name: ws for ws in snapshot.workspaces.values() if ws.name is not None}
    default_timeout = spec.options.default_startup_timeout_s

    # Flatten all apps with workspace context
    all_apps: list[tuple[str, AppSpec]] = [
        (ws.name, app) for ws in spec.workspaces for app in ws.apps
    ]

    # Assign windows globally
    assignments = _assign(all_apps, snapshot.windows.values())

    # Build workspace states
    workspace_states = []
    for ws in spec.workspaces:
        live_ws = ws_by_name.get(ws.name)
        exists = live_ws is not None
        workspace_states.append(WorkspaceState(
            name=ws.name,
            exists=exists,
            output_correct=exists and (ws.output is None or live_ws.output == ws.output),
            desired_output=ws.output,
            current_output=live_ws.output if live_ws else None,
            focus=ws.focus,
        ))

    # Build app resolutions
    app_resolutions = []
    for (ws_name, app_spec), (window_id, is_ambiguous) in zip(all_apps, assignments, strict=True):
        timeout = app_spec.startup_timeout_s or default_timeout

        if window_id is not None:
            window = snapshot.windows[window_id]
            drift = _detect_drift(window, app_spec, ws_name, ws_by_name)
            status = ResolutionStatus.DRIFTED if drift else ResolutionStatus.MATCHED
        else:
            drift = []
            status = ResolutionStatus.OPTIONAL_MISSING if app_spec.optional else ResolutionStatus.MISSING

        if is_ambiguous:
            status = ResolutionStatus.AMBIGUOUS

        app_resolutions.append(AppResolution(
            app_name=app_spec.name,
            workspace_name=ws_name,
            status=status,
            window_id=window_id,
            is_ambiguous=is_ambiguous,
            drift=drift,
            spec=app_spec,
            startup_timeout_s=timeout,
        ))

    return Resolution(
        session_name=spec.name,
        workspaces=workspace_states,
        apps=app_resolutions,
    )


def _detect_drift(window, app_spec, ws_name, ws_by_name) -> list[DriftItem]:
    drift = []
    target_ws = ws_by_name.get(ws_name)
    if target_ws is None or window.workspace_id != target_ws.id:
        drift.append(DriftItem(kind=DriftKind.WRONG_WORKSPACE, current=str(window.workspace_id), desired=ws_name))
    for kind, win_attr, place_attr in _PROPERTY_CHECKS:
        if getattr(window, win_attr, False) != getattr(app_spec.placement, place_attr):
            drift.append(DriftItem(
                kind=kind,
                current=str(getattr(window, win_attr, False)),
                desired=str(getattr(app_spec.placement, place_attr)),
            ))
    return drift
```

**Key simplifications:**
- `evaluate_rule` returns `(bool, MatchTier)` — drops `reasons` list (debug info that's never surfaced to users)
- `_assign` is a module-level function, not a protocol+class
- `MatchDecision` gone — its data is split between `AppResolution.window_id` and `AppResolution.is_ambiguous`
- `Resolution.apps` is flat — no nested `WorkspaceResolution` containers
- `WorkspaceState` is just facts, not a container for apps

---

## File 3: `plan.py` (~350 LOC)

### Currently: 5 files
- `planning/models.py` (157 LOC)
- `planning/builder.py` (258 LOC)
- `planning/compiler.py` (109 LOC)
- `planning/ordering.py` (42 LOC)
- `planning/__init__.py` (7 LOC)

### Structure

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
    """Generate an ordered execution plan from a resolution."""
    steps: list[PlanStep] = []
    counter = 0
    app_first: dict[str, str] = {}  # "ws/app" -> first step id
    app_last: dict[str, str] = {}   # "ws/app" -> last step id

    def emit(kind: StepKind, description: str, **kwargs) -> str:
        nonlocal counter
        counter += 1
        sid = f"{kind.value}-{counter}"
        step = PlanStep(id=sid, kind=kind, description=description, **kwargs)
        steps.append(step)
        # Track app step spans for dependency wiring
        key = f"{step.workspace_name}/{step.app_name}" if step.app_name and step.workspace_name else None
        if key:
            if key not in app_first:
                app_first[key] = sid
            app_last[key] = sid
        return sid

    # Phase 1: Workspace setup + app steps
    for ws in resolution.workspaces:
        base_deps = _workspace_steps(ws, emit)

        for ar in resolution.apps_in(ws.name):
            if not _should_act(ar, options):
                continue
            placement_deps = list(base_deps)
            if ar.status == ResolutionStatus.MISSING and ar.spec.spawn:
                placement_deps = _spawn_steps(ar, ws.name, base_deps, emit)
            _placement_steps(ar, ws.name, placement_deps, emit)

    # Phase 2: Workspace focus (always last)
    for ws in resolution.workspaces:
        if ws.focus:
            emit(StepKind.FOCUS_WORKSPACE, f"focus workspace '{ws.name}'", workspace_name=ws.name)

    # Phase 3: Wire inter-app depends_on
    _wire_dependencies(steps, app_first, app_last, resolution)

    return Plan(
        session_name=resolution.session_name,
        steps=_topological_sort(steps),
        resolution=resolution,
    )


def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
    match ar.status:
        case ResolutionStatus.MATCHED | ResolutionStatus.OPTIONAL_MISSING | ResolutionStatus.AMBIGUOUS:
            return False
        case ResolutionStatus.MISSING:
            return options.launch_missing
        case ResolutionStatus.DRIFTED:
            return True


def _workspace_steps(ws: WorkspaceState, emit) -> list[str]:
    if not ws.exists:
        sid = emit(StepKind.CREATE_WORKSPACE, f"create workspace '{ws.name}'",
                   workspace_name=ws.name, target_output=ws.desired_output)
        return [sid]
    if not ws.output_correct and ws.desired_output:
        sid = emit(StepKind.MOVE_WORKSPACE_TO_OUTPUT, f"move workspace '{ws.name}' to {ws.desired_output}",
                   workspace_name=ws.name, target_output=ws.desired_output)
        return [sid]
    return []


def _spawn_steps(ar: AppResolution, ws_name: str, base_deps: list[str], emit) -> list[str]:
    spawn_id = emit(StepKind.SPAWN_WINDOW, f"spawn {ar.app_name}",
                    app_name=ar.app_name, workspace_name=ws_name,
                    command=ar.spec.spawn.command, cwd=ar.spec.spawn.cwd,
                    env=ar.spec.spawn.env, shell=ar.spec.spawn.shell,
                    depends_on=base_deps)
    wait_id = emit(StepKind.WAIT_FOR_WINDOW, f"wait for {ar.app_name}",
                   app_name=ar.app_name, workspace_name=ws_name,
                   match=ar.spec.match, timeout_s=ar.startup_timeout_s,
                   depends_on=[spawn_id])
    return [wait_id]


def _placement_steps(ar: AppResolution, ws_name: str, deps: list[str], emit) -> None:
    wid = ar.window_id  # directly on AppResolution now

    # Move to workspace if needed
    if ar.needs_move or ar.status == ResolutionStatus.MISSING:
        emit(StepKind.MOVE_WINDOW, f"move {ar.app_name} to '{ws_name}'",
             app_name=ar.app_name, workspace_name=ws_name, window_id=wid, depends_on=deps)

    # State corrections (data-driven)
    _STATE_DRIFT_MAP = [
        (DriftKind.WRONG_FLOATING, "floating", WindowProperty.FLOATING, WindowProperty.TILING),
        (DriftKind.WRONG_FULLSCREEN, "fullscreen", WindowProperty.FULLSCREEN, None),
        (DriftKind.WRONG_MAXIMIZED, "maximized", WindowProperty.MAXIMIZED, None),
    ]
    for drift_kind, placement_attr, prop_true, prop_false in _STATE_DRIFT_MAP:
        has_drift = any(d.kind == drift_kind for d in ar.drift)
        desired = getattr(ar.spec.placement, placement_attr)
        if has_drift or (ar.status == ResolutionStatus.MISSING and desired):
            prop = prop_true if desired else (prop_false or prop_true)
            emit(StepKind.SET_STATE, f"set {ar.app_name} {prop.value}",
                 app_name=ar.app_name, workspace_name=ws_name, window_id=wid,
                 property=prop, value=desired, depends_on=deps)

    # Resize
    if ar.spec.placement.column_width is not None:
        prop, px = _parse_size(ar.spec.placement.column_width)
        emit(StepKind.RESIZE, f"set column width for {ar.app_name}",
             app_name=ar.app_name, workspace_name=ws_name, window_id=wid,
             axis=ResizeAxis.WIDTH, proportion=prop, pixels=px, depends_on=deps)
    if ar.spec.placement.window_height is not None:
        prop, px = _parse_size(ar.spec.placement.window_height)
        emit(StepKind.RESIZE, f"set window height for {ar.app_name}",
             app_name=ar.app_name, workspace_name=ws_name, window_id=wid,
             axis=ResizeAxis.HEIGHT, proportion=prop, pixels=px, depends_on=deps)

    # Focus
    if ar.spec.placement.focus:
        emit(StepKind.FOCUS_WINDOW, f"focus {ar.app_name}",
             app_name=ar.app_name, workspace_name=ws_name, window_id=wid, depends_on=deps)


def _wire_dependencies(steps, app_first, app_last, resolution) -> None:
    """Mutate step depends_on to honor inter-app depends_on from spec."""
    deps_to_add: dict[str, list[str]] = {}
    for ar in resolution.apps:
        if not ar.spec.depends_on:
            continue
        first_key = f"{ar.workspace_name}/{ar.app_name}"
        first_id = app_first.get(first_key)
        if first_id is None:
            continue
        for dep_name in ar.spec.depends_on:
            dep_key = f"{ar.workspace_name}/{dep_name}"
            dep_last = app_last.get(dep_key)
            if dep_last:
                deps_to_add.setdefault(first_id, []).append(dep_last)

    if deps_to_add:
        for i, step in enumerate(steps):
            if step.id in deps_to_add:
                steps[i] = step.model_copy(update={"depends_on": step.depends_on + deps_to_add[step.id]})


def _parse_size(value: float | str) -> tuple[float | None, int | None]:
    if isinstance(value, (int, float)):
        return (float(value), None)
    if isinstance(value, str):
        if value.startswith("px:"):
            try:
                return (None, int(value[3:]))
            except ValueError as e:
                raise NiripError(f"invalid pixel size: {value!r}") from e
        try:
            return (float(value), None)
        except ValueError as e:
            raise NiripError(f"invalid size value: {value!r}") from e
    raise NiripError(f"unexpected size type: {type(value).__name__}")


# ─── Topological Sort ────────────────────────────────────────────────────────

def _topological_sort(steps: list[PlanStep]) -> list[PlanStep]:
    id_map = {s.id: s for s in steps}
    indegree = {s.id: 0 for s in steps}
    edges: dict[str, list[str]] = defaultdict(list)

    for step in steps:
        for dep in step.depends_on:
            if dep in id_map:
                edges[dep].append(step.id)
                indegree[step.id] += 1

    queue = deque(sorted(sid for sid, d in indegree.items() if d == 0))
    ordered: list[PlanStep] = []

    while queue:
        sid = queue.popleft()
        ordered.append(id_map[sid])
        for nxt in sorted(edges[sid]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(steps):
        ordered_ids = {s.id for s in ordered}
        cycle_ids = [s.id for s in steps if s.id not in ordered_ids]
        raise NiripError(f"dependency cycle among steps: {cycle_ids}")

    return ordered
```

**Key simplifications:**
- `PlanBuilder` class → `build_plan()` function with `emit()` closure
- 9 step classes → 1 `PlanStep` with `StepKind` enum
- `_emit_state_steps` repetition → data-driven `_STATE_DRIFT_MAP` table
- `compile_plan` + `PlanBuilder.build()` → single `build_plan()` function
- `compile_diff` deleted — formatting handles it directly
- `CycleError` → just raise `NiripError` with a message
- `SizeParser` callback type → `_parse_size` called directly

---

## File 4: `execute.py` (~300 LOC)

### Currently: 7 files
- `execution/executor.py` (72 LOC)
- `execution/handlers.py` (221 LOC)
- `execution/runtime.py` (28 LOC)
- `execution/hooks.py` (43 LOC)
- `execution/predicates.py` (36 LOC)
- `execution/_checks.py` (15 LOC)
- `execution/models.py` (59 LOC)

### Structure

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


async def execute_plan(
    plan: Plan,
    ports: SessionPorts,
    options: SessionOptions,
    hook: ExecutionHook | None = None,
) -> ApplyResult:
    t0 = time.monotonic()
    h = hook or _NullHook()
    apps: dict[str, _AppState] = {
        step.app_name: _AppState() for step in plan.steps if step.app_name
    }

    results: list[StepResult] = []
    for step in plan.steps:
        h.on_step_start(step)
        t_step = time.monotonic()
        try:
            result = await _execute_step(step, ports, apps)
        except WaitTimeoutError:
            result = StepResult(step=step, outcome=StepOutcome.TIMED_OUT,
                               message="timed out", duration_s=time.monotonic() - t_step)
        except (ConnectionError, OSError) as e:
            result = StepResult(step=step, outcome=StepOutcome.FAILED,
                               message=f"transport error: {e}", duration_s=time.monotonic() - t_step)

        if result.duration_s == 0.0:
            result = result.model_copy(update={"duration_s": time.monotonic() - t_step})
        h.on_step_complete(step, result)
        results.append(result)

        if result.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT) and options.stop_on_error:
            break

    apply_result = ApplyResult(
        session_name=plan.session_name,
        success=all(r.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED) for r in results),
        steps=results,
        total_duration_s=time.monotonic() - t0,
    )
    h.on_plan_complete(apply_result)
    return apply_result


async def _execute_step(step: PlanStep, ports: SessionPorts, apps: dict[str, _AppState]) -> StepResult:
    # Skip check
    if _is_satisfied(step, ports.state.snapshot):
        return StepResult(step=step, outcome=StepOutcome.SKIPPED, message="already satisfied")

    match step.kind:
        case StepKind.CREATE_WORKSPACE:
            await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
            await _wait(ports.state,
                        lambda snap: any(ws.name == step.workspace_name for ws in snap.workspaces.values()),
                        timeout=3.0)
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace ensured")

        case StepKind.MOVE_WORKSPACE_TO_OUTPUT:
            ref = actions.workspace_by_name(step.workspace_name or "")
            await _request(ports.client, actions.move_workspace_to_monitor(step.target_output, ref))
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace moved")

        case StepKind.SPAWN_WINDOW:
            env = os.environ.copy()
            env.update(step.env)
            if isinstance(step.command, str):
                proc = await asyncio.create_subprocess_exec("/bin/sh", "-lc", step.command, cwd=step.cwd, env=env)
            else:
                proc = await asyncio.create_subprocess_exec(*step.command, cwd=step.cwd, env=env)
            if step.app_name and step.app_name in apps:
                apps[step.app_name].spawn_process = proc
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="spawned", spawn_pid=proc.pid)

        case StepKind.WAIT_FOR_WINDOW:
            matched_wid = None
            def predicate(snap):
                nonlocal matched_wid
                for w in snap.windows.values():
                    if evaluate_rule(step.match, w)[0]:
                        matched_wid = w.id
                        return True
                return False

            proc = apps.get(step.app_name, _AppState()).spawn_process if step.app_name else None
            if proc is not None:
                wait_task = asyncio.create_task(_wait(ports.state, predicate, step.timeout_s))
                exit_task = asyncio.create_task(proc.wait())
                done, pending = await asyncio.wait({wait_task, exit_task}, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                if exit_task in done and wait_task not in done:
                    return StepResult(step=step, outcome=StepOutcome.FAILED,
                                     message=f"process exited ({exit_task.result()}) before window appeared")
                if wait_task in done:
                    await wait_task
            else:
                await _wait(ports.state, predicate, step.timeout_s)

            if step.app_name and step.app_name in apps:
                apps[step.app_name].matched_window_id = matched_wid
            return StepResult(step=step, outcome=StepOutcome.COMPLETED,
                             message=f"window appeared (id={matched_wid})", window_id=matched_wid)

        case StepKind.MOVE_WINDOW:
            wid = _resolve_wid(step, apps)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not available")
            target = step.workspace_name or ""
            await _request(ports.client, actions.move_window_to_workspace(actions.workspace_by_name(target), window_id=wid))
            await _wait(ports.state, lambda snap: (
                (w := snap.windows.get(wid)) is not None
                and (t := next((ws for ws in snap.workspaces.values() if ws.name == target), None)) is not None
                and w.workspace_id == t.id
            ), timeout=5.0)
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window moved", window_id=wid)

        case StepKind.SET_STATE:
            wid = _resolve_wid(step, apps)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not available")
            await _request(ports.client, _STATE_ACTIONS[step.property](wid))
            check = _STATE_CHECKS[step.property]
            try:
                await _wait(ports.state,
                            lambda snap, _w=wid, _c=check, _v=step.value: (
                                (w := snap.windows.get(_w)) is not None and _c(w) == _v),
                            timeout=1.5)
            except WaitTimeoutError:
                pass
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message=f"{step.property} set", window_id=wid)

        case StepKind.RESIZE:
            wid = _resolve_wid(step, apps)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not available")
            change = (actions.size_set_proportion(step.proportion) if step.proportion is not None
                      else actions.size_set_fixed(step.pixels or 0))
            if step.axis == ResizeAxis.WIDTH:
                await _request(ports.client, actions.focus_window(wid))
                await _request(ports.client, actions.set_column_width(change))
            else:
                await _request(ports.client, actions.set_window_height(change, wid))
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message=f"{step.axis} resized", window_id=wid)

        case StepKind.FOCUS_WINDOW:
            wid = _resolve_wid(step, apps)
            if wid is None:
                return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not available")
            await _request(ports.client, actions.focus_window(wid))
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="focused", window_id=wid)

        case StepKind.FOCUS_WORKSPACE:
            await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace focused")

        case _:
            return StepResult(step=step, outcome=StepOutcome.FAILED, message="unhandled step kind")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_wid(step: PlanStep, apps: dict[str, _AppState]) -> int | None:
    if step.window_id is not None:
        return step.window_id
    if step.app_name and step.app_name in apps:
        return apps[step.app_name].matched_window_id
    return None


def _is_satisfied(step: PlanStep, snapshot: Snapshot) -> bool:
    if step.kind == StepKind.CREATE_WORKSPACE:
        return any(ws.name == step.workspace_name for ws in snapshot.workspaces.values())
    if step.kind == StepKind.MOVE_WINDOW and step.window_id is not None:
        w = snapshot.windows.get(step.window_id)
        target = next((ws for ws in snapshot.workspaces.values() if ws.name == step.workspace_name), None)
        return w is not None and target is not None and w.workspace_id == target.id
    if step.kind == StepKind.SET_STATE and step.window_id is not None:
        w = snapshot.windows.get(step.window_id)
        return w is not None and _STATE_CHECKS[step.property](w) == step.value
    return False


async def _request(client, req) -> None:
    resp = client.request(req)
    if asyncio.iscoroutine(resp):
        await resp


async def _wait(state: NiriState, predicate: Callable[[Snapshot], bool], timeout: float) -> Snapshot:
    return await wait_until(state, predicate, config=_WAIT_CONFIG, timeout=timeout)
```

**Key simplifications:**
- `SessionRuntime` + `AppRuntimeState` → simple `dict[str, _AppState]` with 2 fields
- `predicates.py` + `_checks.py` → `_is_satisfied()` inlined (15 lines)
- `executor.py` + `handlers.py` → one `execute_plan` + `_execute_step` in same file
- Hook protocol stays (it's a real extension point) but `NullHook` becomes 3-line `_NullHook`
- `LoggingHook` moves to `hooks.py` (kept as separate file for CLI to import)

---

## File 5: `capture.py` (~70 LOC)

### Currently: 3 files (73 LOC total)

### Structure

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

**Key simplifications:**
- `CapturedSession` model deleted — just return `SessionSpec` directly
- `capture/inference.py` inlined (two 5-line functions)
- No `notes` field — if CLI wants to print hints, it does so in the CLI layer

---

## File 6: `cli.py` (~180 LOC)

### Currently: 4 files (198 LOC total)

### Structure

```python
"""CLI entry point, commands, and formatting."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

from nirip.execute import ApplyResult, ExecutionHook, SessionPorts, StepOutcome, StepResult, execute_plan
from nirip.plan import Plan, StepKind, build_plan
from nirip.resolve import Resolution, ResolutionStatus, resolve
from nirip.spec import NiripError, SessionSpec, load_from_file


# ─── Formatting ──────────────────────────────────────────────────────────────

def format_resolution(resolution: Resolution) -> str:
    """Human-readable summary of what would change."""
    if resolution.fully_converged:
        return "No changes needed — session is converged."
    lines = []
    matched = [ar for ar in resolution.apps if ar.status == ResolutionStatus.MATCHED]
    if matched:
        lines.append(f"Matched: {len(matched)} app(s)")
    # ... will_spawn, will_move, drifted, workspace_changes, errors ...
    return "\n".join(lines)


def format_plan(plan: Plan) -> str:
    if plan.is_empty:
        return "Empty plan — nothing to do."
    lines = [f"Plan: {len(plan.steps)} step(s)"]
    for i, step in enumerate(plan.steps, 1):
        deps = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
        lines.append(f"  {i}. [{step.kind}] {step.description}{deps}")
    return "\n".join(lines)


def format_result(result: ApplyResult) -> str:
    status = "SUCCESS" if result.success else "FAILED"
    lines = [f"Result: {status} ({result.total_duration_s:.1f}s)"]
    lines.append(f"  Completed: {result.completed_count}, Skipped: {result.skipped_count}")
    if result.failed_steps:
        lines.append("  Failed steps:")
        for fs in result.failed_steps:
            lines.append(f"    - {fs.step.description}: {fs.message}")
    return "\n".join(lines)


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
    parser = argparse.ArgumentParser(prog="nirip", description="Niri session manager")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("apply", help="Apply a session spec")
    p.add_argument("session_file")
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("diff", help="Show what would change")
    p.add_argument("session_file")

    p = sub.add_parser("plan", help="Show execution plan")
    p.add_argument("session_file")

    p = sub.add_parser("capture", help="Capture current state")
    p.add_argument("-o", "--output")
    p.add_argument("-n", "--name")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    try:
        match args.command:
            case "apply":
                out = asyncio.run(cmd_apply(args.session_file, yes=args.yes, dry_run=args.dry_run, quiet=args.quiet))
            case "diff":
                out = asyncio.run(cmd_diff(args.session_file))
            case "plan":
                out = asyncio.run(cmd_plan(args.session_file))
            case "capture":
                out = asyncio.run(cmd_capture(name=args.name, output=args.output))
            case _:
                parser.print_help()
                return 1
    except Exception as e:
        if args.verbose:
            import traceback
            traceback.print_exc(file=sys.stderr)
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1
    print(out)
    return 0
```

**Key simplifications:**
- `AsyncNirip` facade deleted — commands directly create state/client (it was doing nothing else)
- `format_diff` → `format_resolution` (operates directly on Resolution, no SessionDiff intermediate)
- `LoggingHook` lives here (its only consumer)
- No separate `commands.py` / `formatting.py` / `main.py` — one file, readable top to bottom

---

## File 7: `__init__.py` (~60 LOC)

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

**Key simplifications:**
- No `AsyncNirip` to export — power users compose `resolve` + `build_plan` + `execute_plan` directly
- One sync convenience function for simple use cases
- Public API is just the pipeline functions + types

---

## Mental Model Comparison

### Before (current): To understand "apply"

```
__init__.py → apply_session()
  → AsyncNirip.open() [facade/async_nirip.py]
    → NiriState, NiriClient lifecycle
  → AsyncNirip.apply() [facade/async_nirip.py]
    → resolve() [resolve/resolver.py]
      → assign_windows() [resolve/matcher.py]
        → evaluate_rule() [resolve/matcher.py]
        → GreedyAssigner.assign() [resolve/assigner.py]
      → _detect_drift() [resolve/resolver.py]
      → builds Resolution with WorkspaceResolution containers [resolve/models.py]
    → compile_plan() [planning/compiler.py]
      → PlanBuilder [planning/builder.py]
        → methods called in specific order
        → 9 step type constructors [planning/models.py]
      → topological_sort() [planning/ordering.py]
    → execute_plan() [execution/executor.py]
      → _init_runtime() [execution/executor.py + runtime.py]
      → execute_step() [execution/handlers.py]
        → is_already_satisfied() [execution/predicates.py]
          → STATE_CHECKS [execution/_checks.py]
        → pattern match on 9 types
        → _resolve_window_id() [execution/handlers.py]
      → hook callbacks [execution/hooks.py]
```

**Files touched:** 14. **Concepts to hold:** ~20.

### After (nuclear): To understand "apply"

```
__init__.py → apply_session()
  → load_from_file() [spec.py]
  → resolve() [resolve.py]
    → evaluate_rule() [resolve.py]
    → _assign() [resolve.py]
    → _detect_drift() [resolve.py]
  → build_plan() [plan.py]
    → emit() closure builds steps
    → _topological_sort() [plan.py]
  → execute_plan() [execute.py]
    → _execute_step() [execute.py]
      → _is_satisfied() [execute.py]
      → match on step.kind enum
```

**Files touched:** 4. **Concepts to hold:** ~8.

---

## Trade-offs Summary

| You Lose | You Gain |
|----------|----------|
| Pydantic enforces per-step-type fields | Single type everywhere, no union gymnastics |
| `WindowAssigner` swap-ability | 15 lines of inline logic you'll never swap |
| `MatchDecision` as debug artifact | Simpler AppResolution with direct fields |
| Nested `WorkspaceResolution` grouping | Flat iteration everywhere |
| `SessionDiff` as standalone concept | Direct formatting from Resolution |
| `AsyncNirip` resource management class | Explicit try/finally (same safety, less indirection) |
| `CapturedSession` wrapper | Return the SessionSpec directly |
| Compile-time exhaustiveness on step construction | Runtime simplicity, one type to learn |
| 9 small, focused files per module | 1 readable file per module |

---

## Migration Path

This isn't an all-or-nothing refactor. A sensible order:

1. **Delete dead code** (NiripConfig, unused exceptions, WindowAssigner) — zero risk
2. **Flatten Resolution** (remove WorkspaceResolution nesting) — mechanical, test-driven
3. **Merge resolve/ into resolve.py** — combine files, no logic change
4. **Merge spec/ into spec.py** — combine files, no logic change
5. **Builder → function** — rewrite build_plan as pure function
6. **Unify PlanStep** — replace 9 classes with one + enum
7. **Merge execution/ files** — inline predicates, runtime, checks
8. **Delete SessionDiff** — move logic to formatting
9. **Delete AsyncNirip facade** — inline into CLI commands
10. **Flatten capture/** — trivial merge
