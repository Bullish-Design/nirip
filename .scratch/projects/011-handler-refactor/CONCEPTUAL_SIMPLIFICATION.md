# Conceptual Simplification: Reducing Mental Overhead

## Guiding Principle

A developer learning this library should be able to hold the entire architecture in their head after reading one file (the facade) and skimming two others (models + compiler). Every concept should either be self-evident from its name or justified by the complexity it removes elsewhere.

---

## Change 1: Merge Normalization into Resolution

### Problem

The pipeline currently has 6 phases. "Normalization" is phase 1, but it does only three things:
1. Flatten `workspace.apps[]` into a flat list with `workspace_name` attached
2. Copy `default_startup_timeout_s` into apps that don't specify their own
3. Build a convenience index (`"ws_name/app_name" -> app`)

A newcomer sees `normalize()` called before `resolve()` and must ask: "What's being normalized? What was abnormal?" The answer is disappointing — it's just reshaping.

### Before

```python
# facade/async_nirip.py
async def apply(self, spec: SessionSpec) -> ApplyResult:
    normalized = normalize(spec)              # Phase 1: what does this do?
    resolution = resolve(normalized, self.snapshot)  # Phase 2
    plan = compile_plan(resolution, normalized)      # Phase 3
    ...
```

```python
# resolve/normalizer.py (43 lines)
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
                startup_timeout_s=(app_spec.startup_timeout_s or spec.options.default_startup_timeout_s),
                depends_on=app_spec.depends_on,
            )
            apps.append(na)
            app_names.append(app_spec.name)
            app_index[f"{ws.name}/{app_spec.name}"] = na

        workspaces.append(
            NormalizedWorkspace(name=ws.name, output=ws.output, focus=ws.focus, app_names=app_names)
        )

    return NormalizedSession(
        name=spec.name, description=spec.description, options=spec.options,
        workspaces=workspaces, apps=apps, app_index=app_index,
    )
```

The developer must learn:
- `NormalizedApp` (vs `AppSpec`)
- `NormalizedWorkspace` (vs `WorkspaceSpec`)
- `NormalizedSession` (vs `SessionSpec`)
- The `normalize()` function
- That `resolver.resolve()` takes `NormalizedSession`, not `SessionSpec`

### After

```python
# facade/async_nirip.py
async def apply(self, spec: SessionSpec) -> ApplyResult:
    resolution = resolve(spec, self.snapshot)         # Phase 1: compare spec to reality
    plan = compile_plan(resolution, spec)             # Phase 2: decide what to do
    ...
```

```python
# resolve/resolver.py
def resolve(spec: SessionSpec, snapshot: Snapshot) -> Resolution:
    """Resolve a session spec against a live snapshot."""
    app_index = _build_app_index(spec)  # private helper, same flattening logic
    ...
```

The flattening becomes a private implementation detail of `resolve()`. The `NormalizedApp` model stays (it's useful internally for carrying `workspace_name` + resolved timeout), but it's renamed to something honest like `_ResolvedAppRef` or kept private.

### Impact to Codebase

| File | Change |
|------|--------|
| `resolve/normalizer.py` | **Deleted** (43 lines removed) |
| `resolve/models.py` | `NormalizedSession`, `NormalizedWorkspace`, `NormalizedApp` → either deleted or made private |
| `resolve/resolver.py` | `resolve()` takes `SessionSpec` directly; internal flattening inlined |
| `planning/compiler.py` | `compile_plan()` takes `Resolution` + `SessionSpec` instead of `Resolution` + `NormalizedSession` |
| `facade/async_nirip.py` | Remove `normalize()` call |
| `facade/sync_nirip.py` | Same |
| `__init__.py` | Remove `normalize` from exports (if exported) |
| Tests | Update any tests that directly call `normalize()` |

### Pros
- One fewer phase to learn (6 → 5)
- Three fewer public types to understand
- The pipeline reads naturally: "resolve spec against state, compile plan, execute"
- Removes the confusing "normalized" terminology

### Cons
- Internal flattening still exists — just hidden. If a developer needs to debug resolution, they'll encounter it inside `resolver.py`
- `compiler.py` currently uses `normalized.app_index` and `normalized.workspaces` — these need to be accessible somehow (pass spec + a private index, or have Resolution carry what the compiler needs)

### Implications
- The compiler needs access to spawn commands, timeouts, and placement specs. Currently it gets these from `NormalizedSession`. After this change, it either:
  - (a) Gets them from `SessionSpec` directly (slightly more verbose to traverse), or
  - (b) Resolution carries the relevant bits (e.g., `AppResolution` gains a `spawn: SpawnSpec | None` field)
- Option (b) is cleaner — Resolution already knows which apps need spawning, so it can carry the spawn info forward. This feeds naturally into Change 3 below.

### Opportunities: Self-Contained Resolution → Single-Argument Compiler

The most powerful consequence of merging normalization is that it opens the path to `compile_plan(resolution)` — a single-argument function. This is worth expanding on because it's the difference between "we shuffled code around" and "the architecture became fundamentally simpler."

#### What the compiler currently needs from `NormalizedSession`

Examining `compile_plan(resolution, normalized)`, the compiler reaches into `normalized` for exactly these things:

```python
# 1. Look up app details by name (8 times in the function)
napp = normalized.app_index[f"{wr.name}/{ar.app_name}"]

# From napp, it reads:
napp.spawn              # SpawnSpec: command, cwd, env, shell
napp.match              # MatchRule: for WaitForWindowStep
napp.startup_timeout_s  # float: wait timeout
napp.placement.floating     # bool
napp.placement.fullscreen   # bool
napp.placement.maximized    # bool
napp.placement.column_width # float | str | None
napp.placement.window_height # float | str | None
napp.placement.focus        # bool
napp.depends_on             # list[str]

# 2. Iterate workspaces for focus steps + dependency wiring
for nws in normalized.workspaces:
    nws.focus       # bool: should this workspace be focused?
    nws.app_names   # list[str]: for dependency graph construction
```

#### The key insight

`AppResolution` already carries `app_name`, `workspace_name`, `drift`, and `match_decision`. It knows *which* app it's about and *what's wrong*. The only thing it's missing is *what the user wants* — the spec's placement, spawn, and match data.

If `AppResolution` carried a reference to the app's spec (or the relevant subset), the compiler would never need to look anything up externally.

#### What this looks like

```python
# resolve/models.py — AppResolution gains spec context
class AppResolution(NiripModel):
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    match_decision: MatchDecision
    drift: list[DriftItem]

    # --- NEW: spec data that the compiler needs ---
    spawn: SpawnSpec | None          # how to launch this app
    match_rule: MatchRule            # how to recognize it after launch
    placement: PlacementSpec         # desired window state
    startup_timeout_s: float         # how long to wait
    depends_on: list[str]            # inter-app ordering

# WorkspaceResolution gains the one field it needs
class WorkspaceResolution(NiripModel):
    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    focus: bool                      # NEW: should we focus this workspace?
    app_resolutions: list[AppResolution]
```

```python
# resolve/resolver.py — attach spec data during resolution
ar = AppResolution(
    app_name=app_spec.name,
    workspace_name=ws.name,
    status=status,
    match_decision=decision,
    drift=drift,
    # Carry forward what the compiler will need:
    spawn=app_spec.spawn,
    match_rule=app_spec.match,
    placement=app_spec.placement,
    startup_timeout_s=app_spec.startup_timeout_s or spec.options.default_startup_timeout_s,
    depends_on=app_spec.depends_on,
)
```

```python
# planning/compiler.py — now takes ONE argument
def compile_plan(resolution: Resolution) -> Plan:
    steps: list[PlanStep] = []
    ...
    for wr in resolution.workspace_resolutions:
        ...
        for ar in wr.app_resolutions:
            if not _should_act(ar, resolution.options):
                continue

            # Everything we need is RIGHT HERE on `ar`
            if ar.needs_spawn and ar.spawn:
                steps.append(SpawnWindowStep(
                    ..., command=ar.spawn.command, cwd=ar.spawn.cwd, ...
                ))
                steps.append(WaitForWindowStep(
                    ..., match=ar.match_rule, timeout_s=ar.startup_timeout_s, ...
                ))

            if ar.placement.floating:
                ...
            if ar.placement.column_width is not None:
                ...

        if wr.focus:
            steps.append(FocusWorkspaceStep(...))
    ...
```

#### What the pipeline becomes

```python
# Before: 3 calls, 2 intermediate values, developer must trace data flow
async def apply(self, spec: SessionSpec) -> ApplyResult:
    normalized = normalize(spec)                        # what is this?
    resolution = resolve(normalized, self.snapshot)     # ok, analysis
    plan = compile_plan(resolution, normalized)         # why does it need normalized again?
    return await execute_plan(plan, ports, spec.options)

# After: 2 calls, 1 intermediate value, linear data flow
async def apply(self, spec: SessionSpec) -> ApplyResult:
    resolution = resolve(spec, self.snapshot)           # compare spec to reality
    plan = compile_plan(resolution)                     # turn analysis into steps
    return await execute_plan(plan, ports)
```

A developer reading this can immediately understand the pipeline without asking "what's in `normalized` that isn't in `resolution`?" The answer is: nothing. Resolution IS the complete analysis.

#### Why this matters for mental overhead

The current two-argument `compile_plan(resolution, normalized)` forces the developer to maintain a mental model of which data lives where:
- "resolution tells me what's wrong"
- "normalized tells me what to do about it"
- "the compiler cross-references them by name"

With a single-argument compiler:
- "resolution tells me everything: what's wrong AND what the fix looks like"
- "the compiler just translates that into steps"

This is the difference between a pipeline where each stage passes forward *everything the next stage needs* (clean dataflow) vs one where stages reach back to earlier data (graph dependency). Linear pipelines are dramatically easier to reason about.

#### What about `SessionOptions`?

The compiler currently gets options implicitly through `normalized.options`. After this change, Resolution would carry `options: SessionOptions` as a top-level field (it already has `session_name` — options is the same kind of session-level metadata).

Alternatively, if we apply Change 5 (separate analysis from decision), the compiler gets options as a second argument specifically for policy: `compile_plan(resolution, options)`. This is still cleaner than the current situation because the second argument is a small, obvious config object — not a full parallel data structure.

#### Cost

`AppResolution` grows from 6 fields to 11. It becomes a "fat" analysis object. This is a real tradeoff:

| Concern | Assessment |
|---------|-----------|
| Memory | Negligible — these are Pydantic models with shared references, not deep copies |
| Serialization size | Larger JSON if someone serializes Resolution (e.g., `nirip plan --json`) |
| Conceptual purity | Resolution now mixes "what I observed" with "what the user wants" |
| Alternative | Could use a reference/pointer: `app_spec: AppSpec` field on AppResolution |

The "reference" approach is cleanest — `AppResolution` gets a single `spec: AppSpec` field that points to the original spec object. The compiler reads `ar.spec.spawn`, `ar.spec.placement`, etc. No data duplication, clear provenance.

```python
class AppResolution(NiripModel):
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    match_decision: MatchDecision
    drift: list[DriftItem]
    spec: AppSpec              # original spec, carried forward for compiler
    startup_timeout_s: float   # resolved (spec value or session default)
```

This adds exactly 2 fields to `AppResolution` while eliminating the entire `NormalizedSession` type and the `normalize()` function.

---

## Change 2: Parameterize Window-State Steps (13 → 9 types)

### Problem

Four step types — `SetFloatingStep`, `SetTilingStep`, `SetFullscreenStep`, `SetMaximizedStep` — are structurally identical: "set a boolean property on a window." Each requires its own:
- Model class (in `planning/models.py`)
- Handler case (in `execution/handlers.py`)
- Predicate case (in `execution/predicates.py`)
- Compiler emission logic (in `planning/compiler.py`)
- Entry in the `PlanStep` discriminated union

A developer scanning the step types sees 13 cases and must determine which are "different in kind" vs "different in parameter." That's unnecessary cognitive load.

### Before

```python
# planning/models.py — 4 separate classes
class SetFloatingStep(StepBase):
    kind: Literal["set_floating"] = "set_floating"
    window_id: int | None = None

class SetTilingStep(StepBase):
    kind: Literal["set_tiling"] = "set_tiling"
    window_id: int | None = None

class SetFullscreenStep(StepBase):
    kind: Literal["set_fullscreen"] = "set_fullscreen"
    window_id: int | None = None
    fullscreen: bool

class SetMaximizedStep(StepBase):
    kind: Literal["set_maximized"] = "set_maximized"
    window_id: int | None = None
    maximized: bool
```

```python
# execution/handlers.py — 4 near-identical handler blocks (~80 lines)
case SetFloatingStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    wid_int = wid
    await _request(ports.client, actions.move_window_to_floating(wid_int))
    try:
        await _wait(ports.state, lambda snap: (w := snap.windows.get(wid_int)) is not None and w.is_floating, timeout=1.5)
    except WaitTimeoutError:
        pass
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window set floating", window_id=wid_int)

case SetTilingStep():
    # ... same pattern, different action + predicate ...
case SetFullscreenStep():
    # ... same pattern, different action + predicate ...
case SetMaximizedStep():
    # ... same pattern, different action + predicate ...
```

```python
# execution/predicates.py — 4 near-identical predicate blocks
case SetFloatingStep():
    if step.window_id is None: return False
    w = snapshot.windows.get(step.window_id)
    return w is not None and w.is_floating
case SetTilingStep():
    if step.window_id is None: return False
    w = snapshot.windows.get(step.window_id)
    return w is not None and not w.is_floating
case SetFullscreenStep():
    if step.window_id is None: return False
    w = snapshot.windows.get(step.window_id)
    return w is not None and getattr(w, "is_fullscreen", False) == step.fullscreen
case SetMaximizedStep():
    if step.window_id is None: return False
    w = snapshot.windows.get(step.window_id)
    return w is not None and getattr(w, "is_maximized", False) == step.maximized
```

### After

```python
# planning/models.py — 1 class replaces 4
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
```

```python
# execution/handlers.py — 1 handler replaces 4 (~20 lines)
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

case SetWindowStateStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    await _request(ports.client, _STATE_ACTIONS[step.property](wid))
    check = _STATE_CHECKS[step.property]
    try:
        await _wait(
            ports.state,
            lambda snap: (w := snap.windows.get(wid)) is not None and check(w) == step.value,
            timeout=1.5,
        )
    except WaitTimeoutError:
        pass
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message=f"{step.property} set", window_id=wid)
```

```python
# execution/predicates.py — 1 case replaces 4
case SetWindowStateStep():
    if step.window_id is None:
        return False
    w = snapshot.windows.get(step.window_id)
    if w is None:
        return False
    return _STATE_CHECKS[step.property](w) == step.value
```

```python
# planning/compiler.py — emission becomes:
if napp.placement.floating:
    steps.append(SetWindowStateStep(
        id=next_id("state"), window_id=wid, property=WindowProperty.FLOATING,
        description=f"set {ar.app_name} floating", app_name=ar.app_name,
        workspace_name=ws_name, depends_on=deps,
    ))
elif needs_tiling_correction:
    steps.append(SetWindowStateStep(
        id=next_id("state"), window_id=wid, property=WindowProperty.TILING,
        description=f"set {ar.app_name} tiling", app_name=ar.app_name,
        workspace_name=ws_name, depends_on=deps,
    ))
```

### Impact to Codebase

| File | Change |
|------|--------|
| `planning/models.py` | Remove 4 classes, add 1 class + 1 enum. Net: -25 lines |
| `execution/handlers.py` | Remove 4 cases (~80 lines), add 1 case + 2 tables (~25 lines). Net: -55 lines |
| `execution/predicates.py` | Remove 4 cases (~16 lines), add 1 case (~5 lines). Net: -11 lines |
| `planning/compiler.py` | Minor adjustments to step emission |
| `cli/formatting.py` | Update any step-kind display logic |
| Tests | Update step type references |

### Pros
- 13 step types → 9 (fewer concepts to learn)
- The pattern is immediately obvious: "toggle property X on window Y"
- Adding new window properties (e.g., `is_pinned`) requires zero new classes — just a new enum value + table entry
- Removes ~90 lines of duplicated code across 3 files

### Cons
- Loses some type-level specificity — you can't `isinstance(step, SetFloatingStep)` anymore
- The discriminated union `PlanStep` becomes slightly less self-documenting in serialized form (`"set_window_state"` vs `"set_floating"`)
- `value: bool = True` with `property=TILING` means "set tiling = true" which is semantically "set floating = false" — slightly indirect

### Implications
- Serialized plans (if stored/displayed) will show `{"kind": "set_window_state", "property": "floating"}` instead of `{"kind": "set_floating"}`. This is arguably clearer in context but less grep-friendly.
- The `_emit_float_tiling` helper in compiler.py becomes trivial — may be inlined.

### Opportunities: A Declarative Step Registry

The parameterization doesn't just reduce 4 types to 1 — it reveals a deeper pattern that could reshape how step execution works entirely.

#### Collapsing sizing steps too

`SetColumnWidthStep` and `SetWindowHeightStep` share the same structure: "resize a window along an axis by proportion or pixels." They differ only in which niri action they call.

```python
# Before: 2 separate step types, 2 handler cases
class SetColumnWidthStep(StepBase):
    kind: Literal["set_column_width"] = "set_column_width"
    window_id: int | None = None
    proportion: float | None = None
    pixels: int | None = None

class SetWindowHeightStep(StepBase):
    kind: Literal["set_window_height"] = "set_window_height"
    window_id: int | None = None
    proportion: float | None = None
    pixels: int | None = None

# After: 1 step type
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

Combined with the state parameterization, the step type count goes from 13 → 8:
1. `CreateWorkspaceStep` (was `EnsureWorkspaceStep`)
2. `MoveWorkspaceToOutputStep`
3. `SpawnWindowStep`
4. `WaitForWindowStep`
5. `MoveWindowToWorkspaceStep`
6. `SetWindowStateStep` (replaces 4 types)
7. `ResizeWindowStep` (replaces 2 types)
8. `FocusWindowStep` / `FocusWorkspaceStep` (these 2 are genuinely different — window vs workspace)

That's 9 total, but `FocusWindowStep` and `FocusWorkspaceStep` could arguably merge into `FocusStep(target: "window" | "workspace")` — bringing it to 8.

#### The step registry pattern

Once steps are parameterized, the handler dispatch can become table-driven rather than a giant match statement:

```python
# execution/registry.py — declare handler behavior as data

@dataclass
class StepHandler:
    """Declarative handler specification."""
    prepare: Callable[[PlanStep, SessionRuntime], int | None]  # resolve window ID
    action: Callable[[PlanStep, int, NiriClient], Coroutine]   # send request
    verify: Callable[[PlanStep, int, Snapshot], bool] | None   # check success
    timeout: float = 1.5

_HANDLERS: dict[str, StepHandler] = {
    "set_window_state": StepHandler(
        prepare=_resolve_window_id,
        action=lambda step, wid, client: _request(client, _STATE_ACTIONS[step.property](wid)),
        verify=lambda step, wid, snap: _STATE_CHECKS[step.property](snap.windows.get(wid)) == step.value,
    ),
    "resize_window": StepHandler(
        prepare=_resolve_window_id,
        action=_do_resize,
        verify=None,  # no verification for resize (niri doesn't report exact sizes)
    ),
    "focus_window": StepHandler(
        prepare=_resolve_window_id,
        action=lambda step, wid, client: _request(client, actions.focus_window(wid)),
        verify=None,
    ),
}
```

```python
# execution/executor.py — generic execute loop
async def execute_step(step: PlanStep, ports: SessionPorts, runtime: SessionRuntime) -> StepResult:
    handler = _HANDLERS.get(step.kind)
    if handler is None:
        return _execute_special(step, ports, runtime)  # spawn, wait — these are unique

    wid = handler.prepare(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")

    await handler.action(step, wid, ports.client)

    if handler.verify:
        try:
            await _wait(ports.state, lambda snap: handler.verify(step, wid, snap), handler.timeout)
        except WaitTimeoutError:
            pass

    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message=f"{step.kind} done", window_id=wid)
```

#### What this enables

1. **Adding new step types requires zero handler code** — just define the step model + register an entry in `_HANDLERS`. A developer extending nirip sees one place to look and one pattern to follow.

2. **The "special" steps become explicit** — `SpawnWindowStep` and `WaitForWindowStep` are genuinely different (they involve subprocess management and polling, not RPC-then-verify). Making them the *exception* rather than peers of 11 other identical-pattern handlers clarifies the architecture: "most steps are RPC→verify; these two are special."

3. **Predicates and handlers unify** — `is_already_satisfied()` currently duplicates the verification logic. With a registry, the verify function IS the predicate:

```python
def is_already_satisfied(step: PlanStep, snapshot: Snapshot) -> bool:
    handler = _HANDLERS.get(step.kind)
    if handler is None or handler.verify is None:
        return False
    wid = getattr(step, "window_id", None)
    if wid is None:
        return False
    return handler.verify(step, wid, snapshot)
```

No more parallel match statements that must stay in sync.

4. **Testing becomes declarative** — instead of testing each handler case, you test the generic executor once + test each handler's action/verify functions in isolation. The surface area for bugs shrinks.

#### Why not go all the way to a plugin system?

The registry is internal — it's not an extension point for users. Niri has a fixed set of actions; we're not building a framework for arbitrary compositor commands. The registry is a code organization tool, not an architecture decision. It stays private, stays simple, and could be replaced with a match statement again if needed.

---

## Change 3: Flatten Resolution's "What's Wrong" Into a Single List

### Problem

Currently, to answer "what needs to happen?", a developer must check:
- `resolution.workspace_resolutions[*].app_resolutions` (nested, per-workspace)
- `resolution.unmatched_apps` (flat list, duplicates from above)
- `resolution.ambiguous_apps` (flat list, duplicates from above)
- `resolution.warnings` (string list, different shape)

Then `SessionDiff` re-derives the same info into yet another shape. The developer has 4 places to look and 2 representations of the same data.

### Before

```python
# resolve/models.py
class Resolution(NiripModel):
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]  # nested: ws -> [app_resolution]
    unmatched_apps: list[AppResolution]               # flat subset of above
    ambiguous_apps: list[AppResolution]               # flat subset of above
    warnings: list[str]                               # different type entirely
```

```python
# resolve/resolver.py — manually maintains 3 lists in parallel
workspace_resolutions: list[WorkspaceResolution] = []
unmatched: list[AppResolution] = []
ambiguous: list[AppResolution] = []

for nws in normalized.workspaces:
    ...
    for app_name in nws.app_names:
        ...
        app_resolutions.append(ar)

        if status == ResolutionStatus.MISSING:
            unmatched.append(ar)         # duplicate reference
        if status == ResolutionStatus.AMBIGUOUS:
            ambiguous.append(ar)         # duplicate reference
    ...
```

### After

```python
# resolve/models.py
class Resolution(NiripModel):
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]  # keeps structure for display
    warnings: list[str]

    @computed_field
    @property
    def unmatched_apps(self) -> list[AppResolution]:
        """Apps that need spawning."""
        return [ar for wr in self.workspace_resolutions
                for ar in wr.app_resolutions
                if ar.status == ResolutionStatus.MISSING]

    @computed_field
    @property
    def ambiguous_apps(self) -> list[AppResolution]:
        """Apps with ambiguous matches."""
        return [ar for wr in self.workspace_resolutions
                for ar in wr.app_resolutions
                if ar.status == ResolutionStatus.AMBIGUOUS]

    @computed_field
    @property
    def actionable_apps(self) -> list[AppResolution]:
        """All apps requiring action, in one flat view."""
        return [ar for wr in self.workspace_resolutions
                for ar in wr.app_resolutions
                if ar.action_required]
```

```python
# resolve/resolver.py — no more parallel list maintenance
for nws in normalized.workspaces:
    ...
    for app_name in nws.app_names:
        ...
        app_resolutions.append(ar)
        # That's it. No duplicates to maintain.
    ...
```

### Impact to Codebase

| File | Change |
|------|--------|
| `resolve/models.py` | Remove 2 stored fields, add 3 computed properties |
| `resolve/resolver.py` | Remove 2 temporary lists + their append logic (~6 lines) |
| `planning/compiler.py` | No change (already iterates `workspace_resolutions`) |
| `facade/async_nirip.py` | No change |
| Tests | Any tests asserting on `resolution.unmatched_apps` still work (computed property) |

### Pros
- Single source of truth (workspace_resolutions)
- `resolution.actionable_apps` answers the #1 question a developer asks
- Cannot get out of sync — computed from the same data
- Backward-compatible API (computed properties look the same to callers)

### Cons
- Computed properties re-traverse on each access. For the sizes involved (typically <20 apps), this is negligible.
- Slightly harder to construct in tests (must build full workspace_resolutions to test unmatched_apps)

### Implications
- This is a non-breaking change. External callers still see `.unmatched_apps` and `.ambiguous_apps`. Only the internal storage changes.

### Opportunities: Flattening the Compiler's Inner Loop

The `actionable_apps` computed property doesn't just make Resolution easier to inspect — it fundamentally changes how the compiler can be structured.

#### The current compiler structure

Today, `compile_plan()` has a doubly-nested loop:

```python
def compile_plan(resolution: Resolution, normalized: NormalizedSession) -> Plan:
    steps = []
    for wr in resolution.workspace_resolutions:       # outer: workspaces
        # workspace-level steps (ensure, move to output)...
        for ar in wr.app_resolutions:                 # inner: apps within workspace
            if not ar.action_required:
                continue
            napp = normalized.app_index[f"{wr.name}/{ar.app_name}"]
            # ... emit steps for this app ...

    # Second pass: workspace focus
    for nws in normalized.workspaces:
        if nws.focus:
            steps.append(FocusWorkspaceStep(...))

    # Third pass: inter-app dependencies
    for nws in normalized.workspaces:
        for app_name in nws.app_names:
            napp = normalized.app_index[f"{nws.name}/{app_name}"]
            if not napp.depends_on:
                continue
            # ... wire up dependency edges ...
```

The developer must understand:
- The nested iteration order matters (workspace steps must precede app steps)
- The second pass exists because focus must come after all apps are placed
- The third pass exists because dependencies cross apps

#### What a flat `actionable_apps` enables

With `resolution.actionable_apps` + workspace-level info on `WorkspaceResolution`, the compiler can separate concerns more clearly:

```python
def compile_plan(resolution: Resolution) -> Plan:
    steps = []

    # Phase A: workspace infrastructure
    ws_step_ids = _emit_workspace_steps(resolution.workspace_resolutions, steps)

    # Phase B: per-app actions (flat iteration — no nesting)
    for ar in resolution.actionable_apps:
        ws_deps = [ws_step_ids[ar.workspace_name]] if ar.workspace_name in ws_step_ids else []
        _emit_app_steps(ar, steps, ws_deps)

    # Phase C: inter-app dependency edges
    _wire_dependencies(resolution, steps)

    # Phase D: focus (always last)
    _emit_focus_steps(resolution.workspace_resolutions, steps)

    return Plan(session_name=resolution.session_name, steps=topological_sort(steps))
```

Each phase is a separate function with a clear responsibility. The developer can understand the compiler by reading 4 function signatures without diving into nested loops.

#### Why this matters beyond code length

The current compiler is 319 lines in one function with 3 passes over nested data. A developer trying to understand "how does dependency ordering work?" must read through workspace steps and app emission to find the third pass at line 203+.

With flat iteration, each concern is isolated:
- "How are workspaces handled?" → `_emit_workspace_steps()`
- "What steps does an app get?" → `_emit_app_steps()`
- "How do dependencies work?" → `_wire_dependencies()`
- "When does focus happen?" → `_emit_focus_steps()`

A developer can jump directly to the function they care about.

#### The deeper opportunity: app steps become self-contained

When iterating a flat `actionable_apps` list, each `AppResolution` carries everything about itself (status, drift, spec reference from Change 1). The `_emit_app_steps()` function takes a single `AppResolution` and emits all its steps without referencing external data structures:

```python
def _emit_app_steps(ar: AppResolution, steps: list[PlanStep], deps: list[str]) -> None:
    """Emit all steps for one app. Self-contained — uses only ar's data."""
    placement_deps = list(deps)

    if ar.status == ResolutionStatus.MISSING and ar.spec.spawn:
        spawn_id, wait_id = _emit_spawn(ar, steps, deps)
        placement_deps = [wait_id]

    if ar.needs_move:
        _emit_move(ar, steps, placement_deps)

    _emit_placement(ar, steps, placement_deps)
```

This is trivially testable: construct an `AppResolution`, call `_emit_app_steps()`, assert on the generated steps. No need to build an entire Resolution + NormalizedSession to test one app's compilation.

#### Interaction with Change 5

If `action_required` moves to the compiler (Change 5), then `actionable_apps` is also computed in the compiler rather than on Resolution. This is fine — the compiler can filter:

```python
actionable = [ar for ar in resolution.all_apps if _should_act(ar, options)]
for ar in actionable:
    _emit_app_steps(ar, steps, ...)
```

The flat iteration pattern works regardless of where the filtering happens.

---

## Change 4: Drop `SyncNirip` as a Public Class

### Problem

`SyncNirip` (55 lines) is a method-for-method wrapper around `AsyncNirip` (74 lines) that calls `self._runner.run(...)` on each method. It doubles the public API surface and forces users to make an async/sync decision at the class level. Meanwhile, the module already exports `apply_session()` as a sync convenience function.

### Before

```python
# facade/sync_nirip.py — 55 lines of pure delegation
class SyncNirip:
    def __init__(self, *, state: NiriState, client: NiriClient, config: NiripConfig | None = None) -> None:
        self._async = AsyncNirip(state=state, client=client, config=config)
        self._runner = asyncio.Runner()

    @classmethod
    def open(cls, config: NiripConfig | None = None) -> SyncNirip:
        runner = asyncio.Runner()
        state = runner.run(NiriState.open())
        client = NiriClient.create()
        instance = cls.__new__(cls)
        instance._async = AsyncNirip(state=state, client=client, config=config)
        instance._runner = runner
        return instance

    def diff(self, spec: SessionSpec) -> SessionDiff:
        return self._runner.run(self._async.diff(spec))

    def plan(self, spec: SessionSpec) -> Plan:
        return self._runner.run(self._async.plan(spec))

    def apply(self, spec: SessionSpec) -> ApplyResult:
        return self._runner.run(self._async.apply(spec))

    def capture(self, *, name: str | None = None) -> CapturedSession:
        return self._runner.run(self._async.capture(name=name))

    def close(self) -> None:
        self._runner.run(self._async.close())
        self._runner.close()

    def __enter__(self) -> SyncNirip:
        return self
    def __exit__(self, *_args: Any) -> None:
        self.close()
```

A developer sees two classes in the docs/exports and must choose. They're identical in capability — only the calling convention differs.

### After

```python
# __init__.py — module-level sync convenience functions (already partially exist)
def apply_session(spec: SessionSpec, config: NiripConfig | None = None) -> ApplyResult:
    """One-shot sync apply. Handles connection lifecycle."""
    async def _run():
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.apply(spec)
    return asyncio.run(_run())

def plan_session(spec: SessionSpec, config: NiripConfig | None = None) -> Plan:
    """One-shot sync plan."""
    async def _run():
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.plan(spec)
    return asyncio.run(_run())

def diff_session(spec: SessionSpec, config: NiripConfig | None = None) -> SessionDiff:
    """One-shot sync diff."""
    async def _run():
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.diff(spec)
    return asyncio.run(_run())
```

Users who need a persistent connection use `AsyncNirip` in an async context. Users who want a one-shot operation use the module-level functions. No class to choose.

### Impact to Codebase

| File | Change |
|------|--------|
| `facade/sync_nirip.py` | **Deleted** (55 lines) |
| `__init__.py` | Add/update 3 module-level functions (~20 lines) |
| `cli/commands.py` | If using `SyncNirip`, switch to `AsyncNirip` (CLI is already async) |
| Tests | Any tests using `SyncNirip` switch to module functions or `AsyncNirip` |

### Pros
- Halves the public API surface (1 class instead of 2)
- No "which do I pick?" decision for newcomers
- Module-level functions are the simplest possible interface
- CLI is already async, so no internal user of `SyncNirip` that can't switch

### Cons
- Users who want a persistent sync connection (hold open across multiple operations) lose that affordance
- `asyncio.run()` creates a new event loop per call — slight overhead for rapid repeated calls
- Some users may be allergic to `async/await` and appreciate the sync class

### Implications
- If a user genuinely needs persistent sync access (e.g., REPL usage, Jupyter notebook), they can:
  - Use `asyncio.run()` with `async with AsyncNirip.open() as n: ...`
  - Or we keep a minimal `SyncNirip` but don't export it prominently
- The CLI (the primary consumer) is already fully async and doesn't use `SyncNirip`

### Opportunities
- With only `AsyncNirip` as the public class, documentation can focus entirely on the async interface
- The module functions (`apply_session`, `plan_session`, `diff_session`) become the "5-second quickstart"

---

## Change 5: Separate Analysis from Decision in Resolution

### Problem

`AppResolution` conflates observation with policy:

```python
class AppResolution(NiripModel):
    status: ResolutionStatus      # observation: what IS the state?
    match_decision: MatchDecision  # observation: which window matched?
    drift: list[DriftItem]         # observation: what's different?
    action_required: bool          # POLICY: should we do something?
```

The `action_required` field depends on:
- `status` (MISSING → maybe launch)
- `normalized.options.launch_missing` (user's preference)
- `napp.optional` (spec-level flag)

This means resolution's output changes based on runtime options — it's not a pure observation. A developer debugging "why did it spawn this app?" must trace through the resolver to understand how `action_required` was computed.

### Before

```python
# resolve/resolver.py
if decision.assigned_window_id is not None:
    window = snapshot.windows[decision.assigned_window_id]
    drift = _detect_drift(window, napp, nws.name, ws_by_name)
    status = ResolutionStatus.DRIFTED if drift else ResolutionStatus.MATCHED
    action_required = bool(drift)  # policy baked into analysis
else:
    drift = []
    if napp.optional:
        status = ResolutionStatus.OPTIONAL_MISSING
        action_required = False    # policy baked into analysis
    else:
        status = ResolutionStatus.MISSING
        action_required = normalized.options.launch_missing  # policy from options
```

```python
# planning/compiler.py — must check action_required
for ar in wr.app_resolutions:
    if not ar.action_required:
        continue
    ...
```

### After

```python
# resolve/resolver.py — pure analysis, no policy
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
    # no action_required — that's the compiler's job
)
```

```python
# planning/compiler.py — policy lives here
def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
    """Determine if this app needs action. Policy decision."""
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
            return False  # can't act on ambiguous

for ar in wr.app_resolutions:
    if not _should_act(ar, options):
        continue
    ...
```

### Impact to Codebase

| File | Change |
|------|--------|
| `resolve/models.py` | Remove `action_required` field from `AppResolution` |
| `resolve/resolver.py` | Remove policy logic (~5 lines), simplify status assignment |
| `planning/compiler.py` | Add `_should_act()` helper (~10 lines), use it instead of `ar.action_required` |
| `resolve/models.py` | `Resolution.has_drift` computed property needs updating |
| `cli/formatting.py` | If it references `action_required`, update |
| Tests | Update assertions |

### Pros
- Resolution becomes a pure observation — "here's what I see." Easier to test, reason about, and debug.
- Policy is explicit and in one place (the compiler). A developer can read `_should_act()` to understand all the rules.
- Adding new policies (e.g., "don't adjust floating if app was just spawned") has an obvious home.
- `resolve()` no longer needs `options` access — it only needs the spec and snapshot.

### Cons
- `has_drift` and `fully_converged` on `Resolution` become slightly more complex (must consider status instead of pre-computed `action_required`)
- The `SessionDiff` computation (which also uses `action_required`) needs similar adjustment
- One more function for a developer to find when tracing "why did it do X?"

### Implications
- This pairs well with Change 1 (merge normalization): if Resolution doesn't need options, then the resolver doesn't need the full `NormalizedSession` — it only needs the spec's structure and the snapshot.
- `needs_spawn` computed property on `AppResolution` (which depends on `action_required`) must move to the compiler or be removed.

### Opportunities: What-If Analysis and Composable Policies

Separating analysis from decision doesn't just clarify responsibility — it enables capabilities that are impossible with the current design.

#### "What-if" mode: one resolution, many plans

Today, changing `launch_missing: false` to `true` requires re-running the entire pipeline (re-connecting to niri, re-snapshotting, re-matching windows). This is because `action_required` is baked into Resolution at analysis time.

With pure analysis + separate policy, a single resolution can produce multiple plans:

```python
# CLI could expose this as: nirip plan --what-if launch_missing=false
resolution = resolve(spec, snapshot)  # expensive: talks to compositor

# Cheap: just different policy application
plan_launch = compile_plan(resolution, options=SessionOptions(launch_missing=True))
plan_no_launch = compile_plan(resolution, options=SessionOptions(launch_missing=False))

print(f"With launch_missing=True:  {plan_launch.step_count} steps")
print(f"With launch_missing=False: {plan_no_launch.step_count} steps")
```

This is useful for:
- `nirip plan --what-if` — show what would happen with different options
- Interactive mode — let user toggle options and see plan changes instantly
- Testing — verify that options affect planning correctly without mocking niri

#### Composable policy functions

With `_should_act()` as an explicit, isolated function, policies become composable. Today's policy is simple (5 cases), but future needs might include:

```python
# Future: policy functions can be composed
def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
    """Base policy."""
    ...

def _should_act_conservative(ar: AppResolution, options: SessionOptions) -> bool:
    """Conservative: only fix drift, never spawn."""
    if ar.status == ResolutionStatus.MISSING:
        return False
    return _should_act(ar, options)

def _should_act_aggressive(ar: AppResolution, options: SessionOptions) -> bool:
    """Aggressive: act on ambiguous matches too (pick highest confidence)."""
    if ar.status == ResolutionStatus.AMBIGUOUS:
        return ar.match_decision.confidence > 0.8
    return _should_act(ar, options)
```

The compiler could accept a policy function as a parameter:

```python
def compile_plan(
    resolution: Resolution,
    options: SessionOptions,
    policy: Callable[[AppResolution, SessionOptions], bool] = _should_act,
) -> Plan:
```

This is not over-engineering — it's making explicit what's currently implicit. The current system has exactly one policy, hardcoded. This makes it pluggable without adding complexity to the common case (the default is the current behavior).

#### Resolution becomes cacheable

A pure-observation Resolution (no policy influence) is a stable snapshot of "here's the state of the world right now." This has implications:

1. **Caching**: If the compositor state hasn't changed (no new windows, no moves), the Resolution is still valid. With `action_required` baked in, the cache must be invalidated if options change.

2. **Serialization**: A pure Resolution serializes to a stable document. You can save it (`nirip status --json > state.json`), load it later, and apply different policies without re-connecting to the compositor.

3. **Diffing resolutions**: Compare two Resolutions over time to see what changed in the compositor state, independent of what you planned to do about it.

#### Resolution becomes testable without options

Currently, to test resolution logic you must construct a `NormalizedSession` which includes `options`. This conflates "test that drift detection works" with "test that options affect action decisions." With separation:

```python
# Before: test must set up options just to test drift detection
def test_drift_detected():
    spec = make_session(options=SessionOptions(launch_missing=True))  # why is this here?
    normalized = normalize(spec)
    resolution = resolve(normalized, snapshot)
    assert resolution.workspace_resolutions[0].app_resolutions[0].action_required  # testing policy, not drift!

# After: test drift detection in isolation
def test_drift_detected():
    resolution = resolve(spec, snapshot)
    ar = resolution.workspace_resolutions[0].app_resolutions[0]
    assert ar.status == ResolutionStatus.DRIFTED
    assert ar.drift[0].kind == DriftKind.WRONG_WORKSPACE  # testing observation only

# Separate test for policy
def test_drifted_app_requires_action():
    ar = make_app_resolution(status=ResolutionStatus.DRIFTED)
    assert _should_act(ar, SessionOptions()) is True

def test_missing_app_respects_launch_option():
    ar = make_app_resolution(status=ResolutionStatus.MISSING)
    assert _should_act(ar, SessionOptions(launch_missing=True)) is True
    assert _should_act(ar, SessionOptions(launch_missing=False)) is False
```

Tests become smaller, more focused, and more descriptive.

#### The `needs_spawn` and `needs_move` computed properties

Currently `AppResolution` has:

```python
@computed_field
@property
def needs_spawn(self) -> bool:
    return self.status == ResolutionStatus.MISSING and self.action_required

@computed_field
@property
def needs_move(self) -> bool:
    return any(d.kind == DriftKind.WRONG_WORKSPACE for d in self.drift)
```

With `action_required` removed, `needs_spawn` must change. Two options:

1. **Move to compiler**: `needs_spawn` is really a policy question ("should we spawn this?"), so it belongs in `_should_act()` territory. The compiler already knows the status — it can just check `ar.status == ResolutionStatus.MISSING` directly.

2. **Keep as pure observation**: Rename to `is_missing` — a pure fact. The compiler checks `if ar.is_missing and _should_act(ar, options) and ar.spec.spawn:`.

`needs_move` stays on `AppResolution` — it's a pure observation ("drift includes workspace mismatch"). No policy involved.

---

## Change 6: Rename Opaque Terms

### Problem

Several terms require explanation that their name doesn't provide:

| Term | Used where | A newcomer thinks | Actually means |
|------|-----------|-------------------|----------------|
| `NormalizedSession` | resolve layer | "Was the spec malformed?" | "Flattened with defaults applied" |
| `Resolution` | resolve layer | "A decision was made" | "Analysis of current vs desired state" |
| `drift` (resolver) vs `will_adjust` (diff) | two layers | Two different concepts? | Same concept, inconsistent naming |
| `EnsureWorkspaceStep` | planning | "Check if it exists?" | "Create workspace if missing" |
| `reasons` vs `rationale` | matcher models | Different things? | Both mean "explanation for this decision" |
| `confidence` | matcher | "Probabilistic score" | "Strict priority tier for greedy assignment" |

### Before/After for Each

**1. `EnsureWorkspaceStep` → `CreateWorkspaceStep`**
```python
# Before
class EnsureWorkspaceStep(StepBase):
    kind: Literal["ensure_workspace"] = "ensure_workspace"

# After
class CreateWorkspaceStep(StepBase):
    kind: Literal["create_workspace"] = "create_workspace"
```
The step only fires when the workspace doesn't exist (the compiler already checks `if not wr.exists`). It's a creation step. "Ensure" hides the action behind a hedge.

**2. `reasons` → `match_reasons` (or unify with `rationale`)**
```python
# Before
class MatchCandidate(NiripModel):
    window_id: int
    confidence: float
    reasons: list[str]       # why did this window match?

class MatchDecision(NiripModel):
    ...
    rationale: list[str]     # why was this decision made?

# After — pick one term
class MatchCandidate(NiripModel):
    window_id: int
    confidence: float
    reasons: list[str]       # why this window matched the rule

class MatchDecision(NiripModel):
    ...
    reasons: list[str]       # why this assignment was chosen
```

**3. `will_adjust` → `will_correct_drift` (or just `drifted`)**
```python
# Before (SessionDiff)
will_adjust: list[str]     # what does "adjust" mean?

# After
drifted: list[str]         # matches terminology used in Resolution
```

**4. `confidence: float` → `match_strength: int` (or keep float but rename)**
```python
# Before
class MatchCandidate(NiripModel):
    confidence: float  # 1.0, 0.9, 0.8, 0.7... hand-coded tiers

# After
class MatchCandidate(NiripModel):
    match_strength: int  # 4=pid/exact_app_id, 3=regex_app_id, 2=exact_title, 1=regex_title
```

### Impact to Codebase

These are all search-and-replace renames. No logic changes.

| Rename | Files affected |
|--------|---------------|
| `EnsureWorkspaceStep` → `CreateWorkspaceStep` | models, compiler, handlers, predicates, tests |
| `rationale` → `reasons` | models, matcher, any display code |
| `will_adjust` → `drifted` | SessionDiff model, compiler, CLI formatting |
| `confidence` → `match_strength` | MatchCandidate, MatchDecision, matcher, resolver |

### Pros
- Self-documenting code — fewer "what does this mean?" moments
- Consistent terminology across layers
- No behavioral change — pure naming

### Cons
- Breaking change for any external consumers of the models (serialized JSON changes)
- Renaming `confidence` to an integer changes the type, which affects the greedy assignment comparator
- Churn in tests and any documentation

### Implications
- If models are serialized (e.g., `plan --json` output), field names in JSON change. This is a breaking API change if there are downstream consumers.
- The `confidence` → integer change is more invasive than the others. Could be done separately or deferred.

### Opportunities
- A clean terminology pass makes writing documentation much easier — each term has exactly one meaning.

---

## Change 7: Simplify Match Confidence to Integer Tiers

### Problem

The matching system uses float confidence values (1.0, 0.9, 0.8, 0.7, 0.4) that suggest probabilistic reasoning, but they're actually just a strict priority ordering for the greedy assignment algorithm. The floats add false precision — there's no meaningful difference between 0.89 and 0.91 in this system.

### Before

```python
# resolve/matcher.py
if window.app_id == rule.app_id:
    scores.append(1.0)
    reasons.append(f"app_id exact match: {rule.app_id}")

if window.app_id and re.search(rule.app_id_regex, window.app_id):
    scores.append(0.9)
    reasons.append(f"app_id_regex match: {rule.app_id_regex}")

if window.title == rule.title:
    scores.append(0.8)
    reasons.append(f"title exact match: {rule.title}")

if window.title and re.search(rule.title_regex, window.title):
    scores.append(0.7)
    reasons.append(f"title_regex match: {rule.title_regex}")
```

```python
# When multiple criteria match, confidence = min(scores)
# This means: app_id(1.0) + title_regex(0.7) → confidence 0.7
# That's counterintuitive — more criteria matched, but confidence DROPPED
```

The `min()` aggregation is arguably wrong. An app_id exact match + title regex should be *stronger* than title regex alone, not weaker. But the system works because in practice, the greedy assignment just needs a relative ordering.

### After

```python
# resolve/matcher.py

class MatchTier(IntEnum):
    """Match quality tier. Higher = more specific = preferred in assignment."""
    WEAK = 1        # title_regex only, any_of fallback
    MODERATE = 2    # title exact match
    STRONG = 3      # app_id_regex match
    EXACT = 4       # app_id exact match, pid match

def evaluate_rule(rule: MatchRule, window: Window) -> tuple[bool, MatchTier, list[str]]:
    """Returns (matched, tier, reasons). Tier is the BEST criterion that matched."""
    best_tier = MatchTier.WEAK
    reasons: list[str] = []
    failed = False

    if rule.app_id is not None:
        if window.app_id == rule.app_id:
            best_tier = max(best_tier, MatchTier.EXACT)
            reasons.append(f"app_id exact: {rule.app_id}")
        else:
            failed = True

    if rule.app_id_regex is not None:
        if window.app_id and re.search(rule.app_id_regex, window.app_id):
            best_tier = max(best_tier, MatchTier.STRONG)
            reasons.append(f"app_id_regex: {rule.app_id_regex}")
        else:
            failed = True

    if rule.title is not None:
        if window.title == rule.title:
            best_tier = max(best_tier, MatchTier.MODERATE)
            reasons.append(f"title exact: {rule.title}")
        else:
            failed = True

    if rule.title_regex is not None:
        if window.title and re.search(rule.title_regex, window.title):
            best_tier = max(best_tier, MatchTier.WEAK)
            reasons.append(f"title_regex: {rule.title_regex}")
        else:
            failed = True

    if rule.pid is not None:
        if getattr(window, "pid", None) == rule.pid:
            best_tier = max(best_tier, MatchTier.EXACT)
            reasons.append(f"pid: {rule.pid}")
        else:
            failed = True

    if failed:
        return False, MatchTier.WEAK, reasons
    return True, best_tier, reasons
```

```python
# Greedy assignment uses tier directly — higher tier wins
triples.sort(key=lambda t: t[2], reverse=True)  # same logic, clearer semantics
```

### Impact to Codebase

| File | Change |
|------|--------|
| `resolve/matcher.py` | Replace float scores with `MatchTier` enum, change aggregation from `min(scores)` to `max(tiers)` |
| `resolve/models.py` | `MatchCandidate.confidence: float` → `MatchCandidate.tier: MatchTier` (or `strength: int`) |
| `resolve/models.py` | `MatchDecision.confidence: float` → same |
| `resolve/models.py` | `is_ambiguous` threshold (`> 0.6`) → `>= MatchTier.MODERATE` |
| CLI formatting | Any confidence display |
| Tests | Update expected values |

### Pros
- Honest representation — the system uses discrete tiers, not continuous probabilities
- `max(tiers)` is correct semantics: "the best reason we matched" (vs `min(scores)` which penalizes multi-criteria matches)
- Enum values are self-documenting (`MatchTier.EXACT` vs magic `1.0`)
- `is_ambiguous` becomes clearer: "two candidates both have STRONG or better tier"

### Cons
- Loses ability to express "app_id_regex that matched 90% of the pattern." (But this never existed anyway — it was always 0.9 or nothing.)
- Breaking change if confidence values are exposed in JSON output
- Slightly more complex for the `any_of` composite rule (take max tier of sub-matches)

### Implications
- The `min(scores)` bug (multi-criteria match → lower confidence) gets fixed as a side effect
- The `is_ambiguous` heuristic (`> 0.6` threshold) becomes a tier comparison, which is actually more correct — ambiguity means "two windows both matched at a strong tier"

### Opportunities: Structured Tie-Breaking and Diagnostic Clarity

Integer tiers don't just simplify the scoring — they make the assignment algorithm's decisions transparent and extensible.

#### Tier-aware tie-breaking

With floats, two candidates scoring 0.9 are "equally good" and the assignment picks whichever appears first in the iteration order (non-deterministic in practice). With explicit tiers, we can add structured tie-breaking that's visible and testable:

```python
# Before: tie = arbitrary ordering
triples.sort(key=lambda t: t[2], reverse=True)  # float confidence only

# After: tier + structured sub-criteria
@dataclass(order=True)
class MatchScore:
    """Sortable match quality. Higher = preferred."""
    tier: MatchTier
    on_target_workspace: bool = False  # prefer windows already on the right workspace
    criteria_count: int = 0            # prefer matches with more criteria satisfied

# Sort by (tier DESC, on_target_workspace DESC, criteria_count DESC)
triples.sort(key=lambda t: t[2], reverse=True)
```

This solves a real problem: if two Firefox windows both match `app_id: "firefox"` at tier EXACT, which one should be assigned to the "browser" app on workspace "main"? The one already on workspace "main" is the obvious answer — but the current float system can't express this preference.

```python
# Concrete scenario:
# - Window A: app_id="firefox", workspace="main"    → confidence 1.0
# - Window B: app_id="firefox", workspace="scratch"  → confidence 1.0
# - App spec: name="browser", match: {app_id: "firefox"}, workspace: "main"
#
# Current behavior: arbitrary (A or B depending on iteration order)
# With tie-breaking: prefers A (already on target workspace = less work)
```

#### Clearer ambiguity detection

The current `is_ambiguous` uses a magic threshold:

```python
@computed_field
@property
def is_ambiguous(self) -> bool:
    return sum(1 for c in self.candidates if c.confidence > 0.6) > 1
```

"More than one candidate with confidence above 0.6" is opaque. What's special about 0.6? Why not 0.5 or 0.7?

With tiers, ambiguity has a clear definition:

```python
@computed_field
@property
def is_ambiguous(self) -> bool:
    """True if multiple candidates matched at the same tier."""
    if len(self.candidates) < 2:
        return False
    top_tier = max(c.tier for c in self.candidates)
    at_top = sum(1 for c in self.candidates if c.tier == top_tier)
    return at_top > 1
```

A developer reads this and immediately understands: "ambiguous means we can't distinguish between candidates because they matched with the same quality." No magic numbers, no "what does 0.6 mean?"

#### Diagnostic output becomes human-readable

When displaying match decisions (e.g., `nirip status --verbose`), tiers are immediately meaningful:

```
# Before (floats):
app "editor" → window 42 (confidence: 0.90)
  candidates: [42 (0.90), 67 (0.70)]

# After (tiers):
app "editor" → window 42 (match: STRONG — app_id_regex)
  candidates: [42 (STRONG), 67 (WEAK — title_regex only)]
```

The user immediately understands why window 42 won — it matched at a higher tier. With floats, "0.90 vs 0.70" requires the user to know the scoring rubric.

#### The `any_of` and `not` composites become clearer

Currently, `any_of` takes `max(r[1] for r in any_match)` — the highest float among sub-rule matches. With tiers:

```python
# Before
if rule.any_of:
    any_results = [evaluate_rule(sub, window) for sub in rule.any_of]
    any_match = [r for r in any_results if r[0]]
    if any_match:
        scores.append(max(r[1] for r in any_match))  # max float... why not min? why not average?

# After
if rule.any_of:
    any_results = [evaluate_rule(sub, window) for sub in rule.any_of]
    any_match = [r for r in any_results if r[0]]
    if any_match:
        best_tier = max(best_tier, max(r[1] for r in any_match))  # best sub-rule tier propagates
```

The semantics are the same, but with tiers the choice of `max` is self-evidently correct: "the `any_of` group's quality is determined by its best sub-rule." With floats, a reviewer might ask "should this be averaged?" — with tiers, that question doesn't arise because tiers don't average.

#### Migration path

The change can be done incrementally:

1. **Step 1**: Add `MatchTier` enum alongside existing floats. Map current float → tier.
2. **Step 2**: Change `evaluate_rule()` to return tier. Add `tier` field to `MatchCandidate`.
3. **Step 3**: Remove float `confidence` field, update `is_ambiguous`.
4. **Step 4**: Add tie-breaking criteria.

Steps 1-3 are mechanical. Step 4 is an enhancement enabled by the cleaner model.

---

---

## Cumulative Impact: All 7 Changes Together

### Current State

```
Source:  2,290 lines across 35 files
Tests:     767 lines across 22 files
Public API exports: 11 symbols (including both AsyncNirip and SyncNirip)
Pipeline phases: 6 (load → normalize → resolve → compile → execute → report)
Step types: 13
Model types a developer must learn: ~25
```

### Projected State

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Source lines | 2,290 | ~1,900 | -390 (~17%) |
| Source files | 35 | 33 | -2 (normalizer.py, sync_nirip.py deleted) |
| Pipeline phases | 6 | 5 | -1 (normalization merged) |
| Step types | 13 | 8-9 | -4 to -5 |
| Public exports | 11 | 9 | -2 (SyncNirip, normalize gone) |
| Model classes in resolve/models.py | 9 | 7 | -2 (NormalizedSession, NormalizedApp gone as public) |
| Handler cases in match statement | 13 | 8-9 | -4 to -5 |
| Predicate cases | 6 | 3 | -3 |

### Line-by-Line Breakdown

| File | Current | Projected | Delta | Notes |
|------|---------|-----------|-------|-------|
| `resolve/normalizer.py` | 42 | **0 (deleted)** | -42 | Change 1: merged into resolver |
| `resolve/models.py` | 134 | ~110 | -24 | Changes 1,3,5: remove NormalizedSession/App, remove stored lists, remove action_required |
| `resolve/resolver.py` | 136 | ~125 | -11 | Changes 1,5: inline flattening preamble, remove policy logic |
| `resolve/matcher.py` | 143 | ~130 | -13 | Change 7: MatchTier enum replaces float logic, simpler aggregation |
| `planning/models.py` | 155 | ~110 | -45 | Change 2: 4 state classes + 2 sizing classes → 2 parameterized classes |
| `planning/compiler.py` | 318 | ~250 | -68 | Changes 1,3,5: single-arg, flat iteration, _should_act extracted, _emit_float_tiling inlined |
| `execution/handlers.py` | 268 | ~165 | -103 | Change 2: 6 handler cases collapse to 2 + table-driven dispatch |
| `execution/predicates.py` | 51 | ~25 | -26 | Change 2: 4 cases → 1 table lookup |
| `facade/sync_nirip.py` | 54 | **0 (deleted)** | -54 | Change 4: deleted |
| `facade/async_nirip.py` | 73 | ~60 | -13 | Change 1: remove normalize() call, simpler pipeline |
| `__init__.py` | 40 | ~45 | +5 | Change 4: add module-level sync functions |
| `cli/formatting.py` | 57 | ~57 | 0 | Change 6: rename `will_adjust` → `drifted` (same length) |
| Other files | ~819 | ~819 | 0 | Unchanged |
| **Total source** | **2,290** | **~1,896** | **-394** |

### Concept Count Reduction

A developer learning the library encounters these concepts. "Before" counts what they must understand to trace a full `apply()` call:

| Category | Before | After |
|----------|--------|-------|
| **Pipeline phases** | 6 (load, normalize, resolve, compile, execute, report) | 5 (load, resolve, compile, execute, report) |
| **Public classes** | 3 (SessionSpec, AsyncNirip, SyncNirip) | 2 (SessionSpec, AsyncNirip) |
| **Internal model types** | NormalizedApp, NormalizedWorkspace, NormalizedSession, MatchCandidate, MatchDecision, AppResolution, WorkspaceResolution, Resolution, DriftItem, DriftKind, ResolutionStatus, Plan, SessionDiff, StepBase + 13 step types, StepOutcome, StepResult, ApplyResult, SessionPorts, SessionRuntime, AppRuntimeState = **~35** | Same minus 3 Normalized types, minus 5 step types, add 2 enums (WindowProperty, MatchTier) = **~29** |
| **Functions to trace** | normalize(), resolve(), compile_plan(resolution, normalized), compile_diff(), execute_plan(), execute_step() + 13 handler cases = **~20 significant functions** | resolve(), compile_plan(resolution), _should_act(), compile_diff(), execute_plan(), execute_step() + 8 handler cases = **~14 significant functions** |
| **Terms requiring explanation** | normalized, resolution, confidence, action_required, drift vs will_adjust, ensure, reasons vs rationale = **7** | resolution, drift, match tier = **3** |

### What the Pipeline Looks Like After

```python
# The entire pipeline in one function — a developer reads this once and understands everything:

async def apply(self, spec: SessionSpec) -> ApplyResult:
    resolution = resolve(spec, self.snapshot)     # "what is vs what should be"
    plan = compile_plan(resolution)               # "what to do about it"
    return await execute_plan(plan, self._ports)  # "do it"
```

Each stage:
1. `resolve(spec, snapshot) → Resolution` — Pure analysis. Matches windows to apps, detects drift. Carries spec data forward.
2. `compile_plan(resolution) → Plan` — Policy + ordering. Decides what action to take (via `_should_act`), emits steps, topological sorts.
3. `execute_plan(plan, ports) → ApplyResult` — Mechanical. For each step: check if satisfied, send RPC, verify.

### Architectural Invariants After All Changes

1. **Linear dataflow**: Each stage's output is the complete input to the next. No reaching back.
2. **Single source of truth**: Resolution's `workspace_resolutions` is THE data. Everything else is computed from it.
3. **Analysis ≠ policy**: Resolution observes. The compiler decides. The executor acts.
4. **One pattern for window steps**: All window-affecting steps are "resolve ID → send action → verify state." Special steps (spawn, wait) are explicitly exceptional.
5. **Flat iteration**: The compiler iterates `actionable_apps` once. No nested workspace→app loops for step emission.

### Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Regression in matching behavior | Low | Change 7's `max(tiers)` vs `min(scores)` is the only logic change. Existing matcher tests cover this. |
| Breaking serialized output | Medium | Changes 2, 6, 7 alter JSON keys (`set_floating` → `set_window_state`, `confidence` → `tier`, etc.). Affects `nirip plan --json`. |
| Test churn | High (but acceptable) | ~15 of 22 test files reference models that change. Most updates are mechanical renames. |
| Performance regression | Negligible | Computed properties on Resolution iterate <20 items. No hot paths affected. |
| Harder debugging | Low | Flat iteration + explicit policy actually makes debugging easier (one place to check each concern). |

### What a Developer's First 10 Minutes Look Like

**Before (current)**:
1. Open `__init__.py` — see `AsyncNirip` and `SyncNirip`. Which do I use?
2. Open `AsyncNirip.apply()` — see `normalize()`, `resolve()`, `compile_plan()`. What's normalize? Why does compile need both?
3. Open `normalizer.py` — it just flattens things. Why is this a separate phase?
4. Open `handlers.py` — 268 lines, 13 cases. Many look identical. Which are important?
5. Open `models.py` — 13 step types. Do I need to understand all of them?
6. Get confused by `action_required` — where does this logic live? In resolve? In planning? Both?

**After (all changes)**:
1. Open `__init__.py` — see `AsyncNirip` + three module functions. Clear.
2. Open `AsyncNirip.apply()` — see `resolve()`, `compile_plan()`. Two steps. Linear.
3. Open `handlers.py` — ~165 lines. 3 unique handlers (spawn, wait, move) + a table-driven generic handler. Immediately clear which are "different."
4. Open `models.py` — 8 step types. `SetWindowStateStep` with a `WindowProperty` enum. Self-evident.
5. Open `compiler.py` — `_should_act()` is 10 lines of match statement. All policy in one place.

Time to understanding drops from "read 6+ files, cross-reference 2 data structures" to "read 3 files, follow linear dataflow."

---

## Summary: Dependency Graph Between Changes

```
Change 1 (Merge normalization)
    └── enables simpler resolve() signature
    └── pairs with Change 5 (if Resolution doesn't need options)

Change 2 (Parameterize window states)
    └── standalone, no dependencies
    └── subsumes the 011 handler extraction plan for these 4 types

Change 3 (Flatten Resolution lists)
    └── standalone, backward-compatible
    └── pairs with Change 5 (actionable_apps replaces action_required iteration)

Change 4 (Drop SyncNirip)
    └── standalone, no dependencies

Change 5 (Separate analysis from decision)
    └── depends on Change 1 (resolver shouldn't need options)
    └── pairs with Change 3 (actionable_apps computed in compiler, not resolver)

Change 6 (Rename terms)
    └── standalone, can be done incrementally

Change 7 (Integer match tiers)
    └── standalone, but pairs with Change 6 (renaming confidence)
```

## Recommended Execution Order

1. **Change 3** — Non-breaking, backward-compatible. Low risk, immediate clarity win.
2. **Change 2** — Structural but isolated to planning+execution layers. High code reduction.
3. **Change 6** — Pure renames. Do alongside other changes to avoid double-churn.
4. **Change 5** — Conceptual clarification. Prepares ground for Change 1.
5. **Change 1** — Requires Change 5 first (otherwise resolver still needs options). Biggest mental-model win.
6. **Change 4** — Can be done anytime. Social/API decision more than technical.
7. **Change 7** — Nice-to-have. Fixes a subtle bug but has most churn for least user-facing benefit.
