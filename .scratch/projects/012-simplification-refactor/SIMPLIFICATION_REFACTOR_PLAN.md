# Simplification Refactor Plan

## Overview

Seven coordinated changes to reduce mental overhead for developers learning the nirip library. Execution order is optimized for safety (non-breaking changes first) and dependency satisfaction.

**Starting state**: 2,290 source lines, 35 files, 13 step types, 6 pipeline phases
**Target state**: ~1,900 source lines, 33 files, 8 step types, 5 pipeline phases

Each phase produces a passing test suite and a clean commit.

---

## Phase 1: Flatten Resolution's Stored Lists → Computed Properties

**Goal**: Single source of truth for "what's wrong." Remove parallel list maintenance.

### Step 1.1: Add computed properties to `Resolution`

**File**: `src/nirip/resolve/models.py`

Add three `@computed_field` properties to `Resolution`:

```python
class Resolution(NiripModel):
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]
    unmatched_apps: list[AppResolution]    # KEEP for now (will remove in 1.2)
    ambiguous_apps: list[AppResolution]    # KEEP for now (will remove in 1.2)
    warnings: list[str]

    # NEW computed views
    @computed_field
    @property
    def all_app_resolutions(self) -> list[AppResolution]:
        return [ar for wr in self.workspace_resolutions for ar in wr.app_resolutions]

    @computed_field
    @property
    def actionable_apps(self) -> list[AppResolution]:
        return [ar for ar in self.all_app_resolutions if ar.action_required]
```

**Test**: Run `pytest tests/` — no changes to pass, these are additive.

### Step 1.2: Switch `unmatched_apps` and `ambiguous_apps` to computed

**File**: `src/nirip/resolve/models.py`

Remove the stored fields, replace with computed properties:

```python
class Resolution(NiripModel):
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]
    warnings: list[str]

    @computed_field
    @property
    def unmatched_apps(self) -> list[AppResolution]:
        return [ar for ar in self.all_app_resolutions if ar.status == ResolutionStatus.MISSING]

    @computed_field
    @property
    def ambiguous_apps(self) -> list[AppResolution]:
        return [ar for ar in self.all_app_resolutions if ar.status == ResolutionStatus.AMBIGUOUS]

    # ... existing has_drift, fully_converged stay (update has_drift to not use unmatched_apps)
```

**File**: `src/nirip/resolve/resolver.py`

Remove the `unmatched` and `ambiguous` local lists and their append logic. Remove them from the `Resolution(...)` constructor call:

```python
# Before
return Resolution(
    session_name=normalized.name,
    workspace_resolutions=workspace_resolutions,
    unmatched_apps=unmatched,
    ambiguous_apps=ambiguous,
    warnings=[],
)

# After
return Resolution(
    session_name=normalized.name,
    workspace_resolutions=workspace_resolutions,
    warnings=[],
)
```

**Tests to update**:
- `test_resolver_drift.py` — if it constructs `Resolution` directly, remove the stored fields from the constructor
- `test_matcher_resolver_planning.py` — same

**Verify**: `pytest tests/`

---

## Phase 2: Parameterize Window-State Steps

**Goal**: Collapse 4 state types + 2 sizing types into 2 parameterized types.

### Step 2.1: Define new model types

**File**: `src/nirip/planning/models.py`

Add at the top (after imports):

```python
class WindowProperty(StrEnum):
    FLOATING = "floating"
    TILING = "tiling"
    FULLSCREEN = "fullscreen"
    MAXIMIZED = "maximized"

class SetWindowStateStep(StepBase):
    kind: Literal["set_window_state"] = "set_window_state"
    window_id: int | None = None
    property: WindowProperty
    value: bool = True

class ResizeAxis(StrEnum):
    WIDTH = "width"
    HEIGHT = "height"

class ResizeWindowStep(StepBase):
    kind: Literal["resize_window"] = "resize_window"
    window_id: int | None = None
    axis: ResizeAxis
    proportion: float | None = None
    pixels: int | None = None
```

Update the `PlanStep` discriminated union to include `SetWindowStateStep | ResizeWindowStep` and remove the 6 old types from it.

Keep the old classes temporarily (mark with `# DEPRECATED — remove after migration`) so tests don't break during transition.

### Step 2.2: Migrate compiler emission

**File**: `src/nirip/planning/compiler.py`

Replace `_emit_float_tiling()` calls and inline fullscreen/maximized/sizing emission with new types:

```python
# Floating/tiling
if needs_float_or_tile_correction:
    prop = WindowProperty.FLOATING if napp.placement.floating else WindowProperty.TILING
    steps.append(SetWindowStateStep(
        id=next_id("state"), window_id=wid, property=prop,
        description=f"set {ar.app_name} {prop.value}",
        app_name=ar.app_name, workspace_name=ws_name, depends_on=deps,
    ))

# Fullscreen
if needs_fullscreen:
    steps.append(SetWindowStateStep(
        id=next_id("state"), window_id=wid,
        property=WindowProperty.FULLSCREEN, value=napp.placement.fullscreen,
        description=f"set {ar.app_name} fullscreen",
        app_name=ar.app_name, workspace_name=ws_name, depends_on=deps,
    ))

# Maximized
if needs_maximized:
    steps.append(SetWindowStateStep(
        id=next_id("state"), window_id=wid,
        property=WindowProperty.MAXIMIZED, value=napp.placement.maximized,
        description=f"set {ar.app_name} maximized",
        app_name=ar.app_name, workspace_name=ws_name, depends_on=deps,
    ))

# Column width
if napp.placement.column_width is not None:
    prop, px = _parse_size(napp.placement.column_width)
    steps.append(ResizeWindowStep(
        id=next_id("resize"), window_id=wid, axis=ResizeAxis.WIDTH,
        proportion=prop, pixels=px,
        description=f"set column width for {ar.app_name}",
        app_name=ar.app_name, workspace_name=ws_name, depends_on=deps,
    ))

# Window height
if napp.placement.window_height is not None:
    prop, px = _parse_size(napp.placement.window_height)
    steps.append(ResizeWindowStep(
        id=next_id("resize"), window_id=wid, axis=ResizeAxis.HEIGHT,
        proportion=prop, pixels=px,
        description=f"set window height for {ar.app_name}",
        app_name=ar.app_name, workspace_name=ws_name, depends_on=deps,
    ))
```

Delete the `_emit_float_tiling()` helper function entirely.

### Step 2.3: Migrate handlers to table-driven dispatch

**File**: `src/nirip/execution/handlers.py`

Add tables at module level:

```python
from nirip.planning.models import WindowProperty, ResizeAxis, SetWindowStateStep, ResizeWindowStep

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
```

Replace 4 `case SetFloatingStep/SetTilingStep/SetFullscreenStep/SetMaximizedStep` with one:

```python
case SetWindowStateStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    await _request(ports.client, _STATE_ACTIONS[step.property](wid))
    check = _STATE_CHECKS[step.property]
    target_val = step.value
    try:
        await _wait(
            ports.state,
            lambda snap, _wid=wid, _check=check, _val=target_val: (
                (w := snap.windows.get(_wid)) is not None and _check(w) == _val
            ),
            timeout=1.5,
        )
    except WaitTimeoutError:
        pass
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message=f"{step.property} set", window_id=wid)
```

Replace 2 `case SetColumnWidthStep/SetWindowHeightStep` with one:

```python
case ResizeWindowStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    change = (
        actions.size_set_proportion(step.proportion)
        if step.proportion is not None
        else actions.size_set_fixed(step.pixels or 0)
    )
    if step.axis == ResizeAxis.WIDTH:
        await _request(ports.client, actions.focus_window(wid))
        await _request(ports.client, actions.set_column_width(change))
    else:
        await _request(ports.client, actions.set_window_height(change, wid))
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message=f"{step.axis} resized", window_id=wid)
```

### Step 2.4: Migrate predicates

**File**: `src/nirip/execution/predicates.py`

Replace 4 state cases with one:

```python
case SetWindowStateStep():
    if step.window_id is None:
        return False
    w = snapshot.windows.get(step.window_id)
    if w is None:
        return False
    return _STATE_CHECKS[step.property](w) == step.value
```

`ResizeWindowStep` has no skip predicate (niri doesn't report exact sizes), so no case needed — falls through to `case _: return False`.

### Step 2.5: Delete old types

**File**: `src/nirip/planning/models.py`

Remove: `SetFloatingStep`, `SetTilingStep`, `SetFullscreenStep`, `SetMaximizedStep`, `SetColumnWidthStep`, `SetWindowHeightStep`

Remove them from `PlanStep` union. Remove their imports from `handlers.py`, `predicates.py`, `compiler.py`.

**File**: `src/nirip/execution/handlers.py`

Remove old imports and dead case branches.

### Step 2.6: Update formatting

**File**: `src/nirip/cli/formatting.py`

The `format_plan()` function uses `step.kind` which now shows `"set_window_state"` and `"resize_window"`. The formatter already uses `step.description` for the human-readable part, so this is likely fine. Verify the output reads well.

**Tests to update**:
- `test_compiler.py` — step kind assertions change
- `test_compiler_spawn_placement.py` — step type assertions change
- `test_planning_models.py` — model instantiation changes
- `test_executor.py` — if it constructs step types directly
- `test_cli_formatting.py` — if it references old step kinds

**Verify**: `pytest tests/`

---

## Phase 3: Rename Opaque Terms

**Goal**: Self-documenting terminology. Do this now before later phases add more code referencing these names.

### Step 3.1: `EnsureWorkspaceStep` → `CreateWorkspaceStep`

Search-and-replace across:
- `src/nirip/planning/models.py` — class name + `kind` literal
- `src/nirip/planning/compiler.py` — import + usage
- `src/nirip/execution/handlers.py` — import + case
- `src/nirip/execution/predicates.py` — import + case
- `tests/test_compiler.py`
- `tests/test_compiler_depends_on.py`

### Step 3.2: `rationale` → `reasons` on `MatchDecision`

**File**: `src/nirip/resolve/models.py` — rename field
**File**: `src/nirip/resolve/matcher.py` — rename in `MatchDecision(...)` constructor

### Step 3.3: `will_adjust` → `drifted` on `SessionDiff`

**File**: `src/nirip/planning/models.py` — rename field
**File**: `src/nirip/planning/compiler.py` — rename in `compile_diff()`
**File**: `src/nirip/cli/formatting.py` — rename reference + update display text

### Step 3.4: Verify

`pytest tests/` — update any test assertions referencing old names.

---

## Phase 4: Separate Analysis from Decision

**Goal**: Resolution becomes pure observation. Policy moves to compiler.

### Step 4.1: Remove `action_required` from `AppResolution`

**File**: `src/nirip/resolve/models.py`

Remove field:
```python
class AppResolution(NiripModel):
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    match_decision: MatchDecision
    drift: list[DriftItem]
    # action_required: bool  ← REMOVED
```

Remove `needs_spawn` computed property (depends on `action_required`). Keep `needs_move` (pure observation).

Update `Resolution.has_drift`:
```python
@computed_field
@property
def has_drift(self) -> bool:
    for wr in self.workspace_resolutions:
        if not wr.exists or not wr.output_correct:
            return True
        if any(ar.status in (ResolutionStatus.DRIFTED, ResolutionStatus.MISSING) for ar in wr.app_resolutions):
            return True
    return False
```

Update `actionable_apps` (from Phase 1) — this now can't use `action_required`. **Remove it for now** — the compiler will own this logic.

### Step 4.2: Simplify resolver

**File**: `src/nirip/resolve/resolver.py`

Remove all `action_required` computation:

```python
# Before
if decision.assigned_window_id is not None:
    ...
    action_required = bool(drift)
else:
    ...
    if napp.optional:
        status = ResolutionStatus.OPTIONAL_MISSING
        action_required = False
    else:
        status = ResolutionStatus.MISSING
        action_required = normalized.options.launch_missing

# After
if decision.assigned_window_id is not None:
    window = snapshot.windows[decision.assigned_window_id]
    drift = _detect_drift(window, napp, nws.name, ws_by_name)
    status = ResolutionStatus.DRIFTED if drift else ResolutionStatus.MATCHED
else:
    drift = []
    status = ResolutionStatus.OPTIONAL_MISSING if napp.optional else ResolutionStatus.MISSING

ar = AppResolution(
    app_name=app_name,
    workspace_name=nws.name,
    status=status,
    match_decision=decision,
    drift=drift,
)
```

### Step 4.3: Add `_should_act()` to compiler

**File**: `src/nirip/planning/compiler.py`

Add at module level:

```python
from nirip.spec.models import SessionOptions

def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
    """Policy: determine if this app resolution requires action."""
    match ar.status:
        case ResolutionStatus.MATCHED:
            return False
        case ResolutionStatus.OPTIONAL_MISSING:
            return False
        case ResolutionStatus.MISSING:
            return options.launch_missing
        case ResolutionStatus.DRIFTED:
            return True
        case ResolutionStatus.AMBIGUOUS:
            return False
```

Update `compile_plan()`:

```python
# Before
for ar in wr.app_resolutions:
    if not ar.action_required:
        continue

# After
for ar in wr.app_resolutions:
    if not _should_act(ar, normalized.options):
        continue
```

Update `ar.needs_spawn` references → `ar.status == ResolutionStatus.MISSING`:

```python
# Before
if ar.needs_spawn and napp.spawn:

# After
if ar.status == ResolutionStatus.MISSING and napp.spawn:
```

### Step 4.4: Update `compile_diff()`

**File**: `src/nirip/planning/compiler.py`

`compile_diff()` currently checks `ar.status` directly (not `action_required`), so it mostly works. Verify the `MISSING` case still produces `will_spawn`.

### Step 4.5: Update `Resolution` computed properties

**File**: `src/nirip/resolve/models.py`

Remove `actionable_apps` (it can't work without `action_required`). The compiler owns this logic now.

Keep `unmatched_apps` and `ambiguous_apps` as computed (from Phase 1) — these are pure status-based filters, no policy.

**Tests to update**:
- `test_resolver_drift.py` — remove `action_required` assertions, assert on `status` instead
- `test_compiler.py` — may need to pass options explicitly
- `test_compiler_spawn_placement.py` ��� same
- `test_integration.py` — if it checks `action_required`

**Verify**: `pytest tests/`

---

## Phase 5: Merge Normalization into Resolution

**Goal**: Eliminate `normalize()` as a pipeline phase. Resolution takes `SessionSpec` directly.

### Step 5.1: Add `spec` field to `AppResolution`

**File**: `src/nirip/resolve/models.py`

```python
from nirip.spec.models import AppSpec

class AppResolution(NiripModel):
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    match_decision: MatchDecision
    drift: list[DriftItem]
    spec: AppSpec                   # NEW: original app spec, carried forward
    startup_timeout_s: float        # NEW: resolved timeout (spec or session default)
```

Add `focus` field to `WorkspaceResolution`:

```python
class WorkspaceResolution(NiripModel):
    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    focus: bool                     # NEW: should this workspace be focused?
    app_resolutions: list[AppResolution]
```

### Step 5.2: Change `resolve()` signature to take `SessionSpec`

**File**: `src/nirip/resolve/resolver.py`

```python
from nirip.spec.models import SessionSpec

def resolve(spec: SessionSpec, snapshot: Snapshot) -> Resolution:
    """Resolve a session spec against a live snapshot."""
    default_timeout = spec.options.default_startup_timeout_s
    ws_by_name = {ws.name: ws for ws in snapshot.workspaces.values() if ws.name is not None}

    # Inline what normalize() used to do — build flat app list for matching
    all_apps: list[tuple[str, AppSpec]] = []  # (workspace_name, app_spec)
    for ws in spec.workspaces:
        for app_spec in ws.apps:
            all_apps.append((ws.name, app_spec))

    # Build match decisions (matcher still needs app names + match rules)
    decisions = _assign_windows(all_apps, snapshot.windows.values())
    decision_index = {(ws_name, app.name): d for (ws_name, app), d in zip(all_apps, decisions)}

    workspace_resolutions: list[WorkspaceResolution] = []

    for ws in spec.workspaces:
        live_ws = ws_by_name.get(ws.name)
        exists = live_ws is not None
        output_correct = exists and (ws.output is None or live_ws.output == ws.output)

        app_resolutions: list[AppResolution] = []
        for app_spec in ws.apps:
            decision = decision_index[(ws.name, app_spec.name)]
            timeout = app_spec.startup_timeout_s or default_timeout

            if decision.assigned_window_id is not None:
                window = snapshot.windows[decision.assigned_window_id]
                drift = _detect_drift(window, app_spec, ws.name, ws_by_name)
                status = ResolutionStatus.DRIFTED if drift else ResolutionStatus.MATCHED
            else:
                drift = []
                status = ResolutionStatus.OPTIONAL_MISSING if app_spec.optional else ResolutionStatus.MISSING

            if decision.is_ambiguous:
                status = ResolutionStatus.AMBIGUOUS

            app_resolutions.append(AppResolution(
                app_name=app_spec.name,
                workspace_name=ws.name,
                status=status,
                match_decision=decision,
                drift=drift,
                spec=app_spec,
                startup_timeout_s=timeout,
            ))

        workspace_resolutions.append(WorkspaceResolution(
            name=ws.name,
            exists=exists,
            output_correct=output_correct,
            desired_output=ws.output,
            current_output=live_ws.output if live_ws else None,
            focus=ws.focus,
            app_resolutions=app_resolutions,
        ))

    return Resolution(session_name=spec.name, workspace_resolutions=workspace_resolutions, warnings=[])
```

### Step 5.3: Update `_detect_drift` to take `AppSpec`

**File**: `src/nirip/resolve/resolver.py`

Change parameter from `NormalizedApp` to `AppSpec`:

```python
def _detect_drift(window: Window, app_spec: AppSpec, ws_name: str, ws_by_name: dict) -> list[DriftItem]:
    drift: list[DriftItem] = []
    # workspace check...
    # Use app_spec.placement instead of napp.placement
    for kind, win_attr, place_attr in _PROPERTY_CHECKS:
        current_val = getattr(window, win_attr, False)
        desired_val = getattr(app_spec.placement, place_attr)
        ...
```

### Step 5.4: Update matcher to work with `(ws_name, AppSpec)` tuples

**File**: `src/nirip/resolve/matcher.py`

The matcher's `assign_windows()` currently takes `list[NormalizedApp]`. Change to accept what we have:

```python
def assign_windows(
    apps: list[tuple[str, AppSpec]],  # (workspace_name, app_spec)
    windows: Iterable[Window],
) -> list[MatchDecision]:
    window_list = list(windows)
    all_candidates: list[list[MatchCandidate]] = []

    for ws_name, app_spec in apps:
        candidates = []
        for w in window_list:
            matched, conf, reasons = evaluate_rule(app_spec.match, w)
            if matched:
                candidates.append(MatchCandidate(window_id=w.id, confidence=conf, reasons=reasons))
        all_candidates.append(candidates)

    # ... rest of greedy assignment stays the same ...

    decisions: list[MatchDecision] = []
    for app_idx, (ws_name, app_spec) in enumerate(apps):
        ...
        decisions.append(MatchDecision(
            app_name=app_spec.name,
            workspace_name=ws_name,
            ...
        ))
    return decisions
```

### Step 5.5: Update `compile_plan()` to single-argument

**File**: `src/nirip/planning/compiler.py`

```python
def compile_plan(resolution: Resolution, options: SessionOptions) -> Plan:
    """Compile resolution into ordered execution plan."""
    steps: list[PlanStep] = []
    ...
    for wr in resolution.workspace_resolutions:
        ...
        for ar in wr.app_resolutions:
            if not _should_act(ar, options):
                continue

            wid = ar.match_decision.assigned_window_id

            # Use ar.spec directly — no more normalized.app_index lookup!
            if ar.status == ResolutionStatus.MISSING and ar.spec.spawn:
                steps.append(SpawnWindowStep(
                    ...,
                    command=ar.spec.spawn.command,
                    cwd=ar.spec.spawn.cwd,
                    env=ar.spec.spawn.env,
                    shell=ar.spec.spawn.shell,
                    ...
                ))
                steps.append(WaitForWindowStep(
                    ...,
                    match=ar.spec.match,
                    timeout_s=ar.startup_timeout_s,
                    ...
                ))

            # Placement from ar.spec.placement
            if ar.spec.placement.floating:
                ...
            if ar.spec.placement.column_width is not None:
                ...

        # Focus from wr.focus
        if wr.focus:
            steps.append(FocusWorkspaceStep(...))

    # Dependency wiring uses ar.spec.depends_on
    for wr in resolution.workspace_resolutions:
        for ar in wr.app_resolutions:
            if not ar.spec.depends_on:
                continue
            ...
```

### Step 5.6: Update facade

**File**: `src/nirip/facade/async_nirip.py`

```python
# Before
async def apply(self, spec: SessionSpec) -> ApplyResult:
    normalized = normalize(spec)
    resolution = resolve(normalized, self.snapshot)
    plan = compile_plan(resolution, normalized)
    ...

# After
async def apply(self, spec: SessionSpec) -> ApplyResult:
    resolution = resolve(spec, self.snapshot)
    plan = compile_plan(resolution, spec.options)
    if plan.is_empty:
        return ApplyResult(session_name=spec.name, success=True, steps=[], total_duration_s=0.0)
    ports = SessionPorts(state=self._state, client=self._client)
    return await execute_plan(plan, ports, spec.options)
```

Same for `diff()` and `plan()` methods.

### Step 5.7: Delete normalizer

**Files to delete**:
- `src/nirip/resolve/normalizer.py`

**Files to clean up**:
- `src/nirip/resolve/__init__.py` — remove `normalize` export if present
- `src/nirip/resolve/models.py` — remove `NormalizedApp`, `NormalizedWorkspace`, `NormalizedSession` classes

**Tests**:
- `test_normalizer.py` — **delete** (13 lines)
- All other tests importing `normalize` or `NormalizedApp` — update

### Step 5.8: Update `compile_diff()`

```python
def compile_diff(resolution: Resolution) -> SessionDiff:
    """Human-readable diff from resolution."""
    diff = SessionDiff(session_name=resolution.session_name, warnings=list(resolution.warnings))
    for wr in resolution.workspace_resolutions:
        ...
        for ar in wr.app_resolutions:
            label = f"{wr.name}/{ar.app_name}"
            if ar.status == ResolutionStatus.MATCHED:
                diff.already_matched.append(label)
            elif ar.status == ResolutionStatus.MISSING:
                diff.will_spawn.append(label)
            elif ar.status == ResolutionStatus.DRIFTED:
                if ar.needs_move:
                    diff.will_move.append(label)
                if any(d.kind != DriftKind.WRONG_WORKSPACE for d in ar.drift):
                    diff.drifted.append(label)  # renamed from will_adjust in Phase 3
            elif ar.status == ResolutionStatus.AMBIGUOUS:
                diff.errors.append(f"ambiguous match: {label}")
    return diff
```

**Verify**: `pytest tests/`

---

## Phase 6: Drop `SyncNirip`

**Goal**: Single public class (`AsyncNirip`) + module-level sync convenience functions.

### Step 6.1: Add module-level convenience functions

**File**: `src/nirip/__init__.py`

```python
from nirip.planning.models import Plan, SessionDiff

def plan_session(spec: SessionSpec, config: NiripConfig | None = None) -> Plan:
    """One-shot sync plan."""
    async def _run() -> Plan:
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.plan(spec)
    return asyncio.run(_run())

def diff_session(spec: SessionSpec, config: NiripConfig | None = None) -> SessionDiff:
    """One-shot sync diff."""
    async def _run() -> SessionDiff:
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.diff(spec)
    return asyncio.run(_run())
```

Update `__all__` to include `plan_session` and `diff_session`.

### Step 6.2: Remove `SyncNirip` from exports

**File**: `src/nirip/__init__.py`

Remove `SyncNirip` from `__all__` and imports.

### Step 6.3: Delete the file

**File to delete**: `src/nirip/facade/sync_nirip.py`

### Step 6.4: Update tests

Any test using `SyncNirip` → switch to `apply_session()` or `AsyncNirip` directly.

**Verify**: `pytest tests/`

---

## Phase 7: Integer Match Tiers

**Goal**: Replace float confidence with explicit `MatchTier` enum.

### Step 7.1: Define `MatchTier`

**File**: `src/nirip/resolve/models.py`

```python
from enum import IntEnum

class MatchTier(IntEnum):
    """Match quality. Higher = more specific = preferred in assignment."""
    NONE = 0
    WEAK = 1        # title_regex, any_of fallback
    MODERATE = 2    # title exact
    STRONG = 3      # app_id_regex
    EXACT = 4       # app_id exact, pid
```

Update `MatchCandidate`:
```python
class MatchCandidate(NiripModel):
    window_id: int
    tier: MatchTier
    reasons: list[str]
```

Update `MatchDecision`:
```python
class MatchDecision(NiripModel):
    app_name: str
    workspace_name: str
    assigned_window_id: int | None = None
    candidates: list[MatchCandidate]
    tier: MatchTier = MatchTier.NONE
    reasons: list[str]  # renamed from rationale in Phase 3

    @computed_field
    @property
    def is_ambiguous(self) -> bool:
        if len(self.candidates) < 2:
            return False
        top = max(c.tier for c in self.candidates)
        return sum(1 for c in self.candidates if c.tier == top) > 1

    @computed_field
    @property
    def is_matched(self) -> bool:
        return self.assigned_window_id is not None
```

### Step 7.2: Update `evaluate_rule()`

**File**: `src/nirip/resolve/matcher.py`

```python
from nirip.resolve.models import MatchTier

def evaluate_rule(rule: MatchRule, window: Window) -> tuple[bool, MatchTier, list[str]]:
    """Evaluate a match rule against a window."""
    best_tier = MatchTier.NONE
    reasons: list[str] = []
    failed = False

    if rule.app_id is not None:
        if window.app_id == rule.app_id:
            best_tier = max(best_tier, MatchTier.EXACT)
            reasons.append(f"app_id exact: {rule.app_id}")
        else:
            failed = True
            reasons.append(f"app_id mismatch: wanted {rule.app_id}, got {window.app_id}")

    if rule.app_id_regex is not None:
        if window.app_id and re.search(rule.app_id_regex, window.app_id):
            best_tier = max(best_tier, MatchTier.STRONG)
            reasons.append(f"app_id_regex: {rule.app_id_regex}")
        else:
            failed = True
            reasons.append(f"app_id_regex no match: {rule.app_id_regex}")

    if rule.title is not None:
        if window.title == rule.title:
            best_tier = max(best_tier, MatchTier.MODERATE)
            reasons.append(f"title exact: {rule.title}")
        else:
            failed = True
            reasons.append(f"title mismatch: wanted {rule.title}, got {window.title}")

    if rule.title_regex is not None:
        if window.title and re.search(rule.title_regex, window.title):
            best_tier = max(best_tier, MatchTier.WEAK)
            reasons.append(f"title_regex: {rule.title_regex}")
        else:
            failed = True
            reasons.append(f"title_regex no match: {rule.title_regex}")

    if rule.pid is not None:
        if getattr(window, "pid", None) == rule.pid:
            best_tier = max(best_tier, MatchTier.EXACT)
            reasons.append(f"pid: {rule.pid}")
        else:
            failed = True
            reasons.append(f"pid mismatch: wanted {rule.pid}, got {getattr(window, 'pid', None)}")

    if rule.any_of:
        any_results = [evaluate_rule(sub, window) for sub in rule.any_of]
        any_match = [r for r in any_results if r[0]]
        if any_match:
            best_tier = max(best_tier, max(r[1] for r in any_match))
            reasons.append("any_of matched")
        else:
            failed = True
            reasons.append("any_of had no matches")

    if rule.not_rule:
        not_match, _, _ = evaluate_rule(rule.not_rule, window)
        if not_match:
            failed = True
            reasons.append("not_rule matched; expected no match")
        else:
            reasons.append("not_rule satisfied")

    if failed:
        return False, MatchTier.NONE, reasons
    if best_tier == MatchTier.NONE:
        best_tier = MatchTier.WEAK  # matched but no criteria scored (shouldn't happen)
    return True, best_tier, reasons
```

### Step 7.3: Update `assign_windows()`

**File**: `src/nirip/resolve/matcher.py`

```python
def assign_windows(apps: list[tuple[str, AppSpec]], windows: Iterable[Window]) -> list[MatchDecision]:
    window_list = list(windows)

    all_candidates: list[list[MatchCandidate]] = []
    for ws_name, app_spec in apps:
        candidates = []
        for w in window_list:
            matched, tier, reasons = evaluate_rule(app_spec.match, w)
            if matched:
                candidates.append(MatchCandidate(window_id=w.id, tier=tier, reasons=reasons))
        all_candidates.append(candidates)

    # Greedy assignment — sort by tier descending
    triples: list[tuple[int, int, MatchTier]] = []
    for app_idx, candidates in enumerate(all_candidates):
        for c in candidates:
            triples.append((app_idx, c.window_id, c.tier))
    triples.sort(key=lambda t: t[2], reverse=True)

    assigned_app: set[int] = set()
    assigned_window: set[int] = set()
    app_to_window: dict[int, int] = {}

    for app_idx, window_id, _tier in triples:
        if app_idx in assigned_app or window_id in assigned_window:
            continue
        app_to_window[app_idx] = window_id
        assigned_app.add(app_idx)
        assigned_window.add(window_id)

    decisions: list[MatchDecision] = []
    for app_idx, (ws_name, app_spec) in enumerate(apps):
        candidates = all_candidates[app_idx]
        wid = app_to_window.get(app_idx)
        tier = MatchTier.NONE
        reasons: list[str] = []

        if wid is not None:
            tier = next(c.tier for c in candidates if c.window_id == wid)
            reasons.append(f"assigned window {wid} (tier {tier.name})")
        elif candidates:
            reasons.append(f"{len(candidates)} candidate(s) all claimed by higher-tier matches")
        else:
            reasons.append("no matching windows found")

        decisions.append(MatchDecision(
            app_name=app_spec.name,
            workspace_name=ws_name,
            assigned_window_id=wid,
            candidates=candidates,
            tier=tier,
            reasons=reasons,
        ))

    return decisions
```

### Step 7.4: Update any code reading `confidence`

Search for `.confidence` across codebase:
- `execution/handlers.py` — `WaitForWindowStep` handler uses `evaluate_rule()` return value; update tuple unpacking from `(matched, conf, reasons)` → `(matched, tier, reasons)` (only `matched` is used there, so trivial)
- CLI formatting — if displaying confidence, update to display tier name

**Tests to update**:
- `test_matcher.py` — update expected confidence values to tier enum values
- `test_matcher_resolver_planning.py` — same
- `test_resolver_drift.py` — if it checks confidence

**Verify**: `pytest tests/`

---

## Post-Refactor Verification

### Full test suite
```bash
pytest tests/ -v
```

### Type checking (if configured)
```bash
mypy src/nirip/ --strict
# or
pyright src/nirip/
```

### Manual smoke test
```bash
nirip diff examples/session.yaml
nirip plan examples/session.yaml
nirip apply examples/session.yaml --dry-run
```

### Verify no dead imports
```bash
ruff check src/nirip/ --select F401
```

---

## Final File Inventory (Post-Refactor)

```
src/nirip/
├── __init__.py              (~50 lines, +10)    — public API + sync helpers
├── __main__.py              (3 lines, unchanged)
├── _base.py                 (19 lines, unchanged)
├── config.py                (14 lines, unchanged)
├── errors.py                (43 lines, unchanged)
├── capture/
│   ├── __init__.py          (5 lines)
│   ├── capturer.py          (45 lines)
│   └── inference.py         (23 lines)
├── cli/
│   ├── __init__.py          (5 lines)
│   ├── commands.py          (58 lines)
│   ├── formatting.py        (~55 lines, minor renames)
│   └── main.py              (59 lines)
├── execution/
│   ├── __init__.py          (6 lines)
│   ├── executor.py          (61 lines, unchanged)
│   ├���─ handlers.py          (~165 lines, -103)   — table-driven
│   ├── models.py            (59 lines, unchanged)
│   ├── predicates.py        (~25 lines, -26)     — table-driven
│   └── runtime.py           (25 lines, unchanged)
├── facade/
│   ├── __init__.py          (6 lines)
│   └── async_nirip.py       (~60 lines, -13)     — no normalize()
│   [sync_nirip.py DELETED]
├── planning/
│   ├── __init__.py          (6 lines)
│   ├── compiler.py          (~250 lines, -68)    — single-arg, flat, _should_act
│   ├── models.py            (~115 lines, -40)    — 8 step types + enums
│   └── ordering.py          (42 lines, unchanged)
├── resolve/
│   ├── __init__.py          (7 lines)
│   ├── matcher.py           (~130 lines, -13)    — MatchTier, max aggregation
│   ├── models.py            (~95 lines, -39)     — no Normalized*, computed lists, MatchTier
│   └── resolver.py          (~130 lines, -6)     — takes SessionSpec, inline flatten
│   [normalizer.py DELETED]
└── spec/
    ├── __init__.py          (15 lines)
    ├── defaults.py          (19 lines, unchanged)
    ├── loader.py            (46 lines, unchanged)
    ├── models.py            (93 lines, unchanged)
    └── validators.py        (160 lines, unchanged)

TOTAL: ~1,896 lines across 33 files (was 2,290 across 35)
```

---

## Commit Strategy

One commit per phase. Each commit message references the design doc:

1. `refactor: flatten Resolution stored lists into computed properties`
2. `refactor: parameterize window-state and resize steps (13→8 types)`
3. `refactor: rename opaque terms (Ensure→Create, rationale→reasons, will_adjust→drifted)`
4. `refactor: separate analysis from policy (remove action_required from Resolution)`
5. `refactor: merge normalization into resolution (single-arg compile_plan)`
6. `refactor: drop SyncNirip, add module-level sync functions`
7. `refactor: replace float confidence with MatchTier enum`

Each commit is independently revertible. If any phase proves problematic mid-implementation, earlier phases still stand alone as improvements.
