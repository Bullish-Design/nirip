# Nirip: Refined Architecture Concept

A declarative session reconciler for the Niri Wayland compositor, built on `niri-pypc` and `niri-state`.

---

## 1. What changed and why

This document refines the original concept after a deep code review of both the nirip implementation and its dependency libraries. The original concept's pipeline design (normalize → resolve → plan → execute) is correct. What's wrong is the implementation's relationship to its dependencies and its internal modeling discipline.

**Three root problems drive every change below:**

1. **Nirip ignores its own dependencies.** It defines `SnapshotLike`, `WindowLike`, and `ActionClient` protocols instead of consuming `niri-state.Snapshot`, `niri-pypc.Window`, and `niri-pypc.NiriClient` directly. This creates phantom abstractions that duplicate what the dependencies already provide, while preventing nirip from actually operating against a live compositor.

2. **The plan model is structurally dishonest.** `PlanStep` is a string enum plus optional fields plus a freeform `metadata` dict. By the time execution begins, the data required to spawn a process or verify a window has been lost. A `SPAWN_WINDOW` step doesn't carry the command. A `WAIT_FOR_WINDOW` step doesn't carry the match rule or timeout.

3. **Matching is locally greedy, not globally consistent.** Each declared app independently picks its best window. Nothing prevents two apps from claiming the same window. For a session reconciler, this is a correctness bug.

Everything below flows from fixing these three problems.

---

## 2. Design principles

Unchanged from the original concept. Restated for completeness:

- **Declarative first.** Users write desired state in YAML. Nirip computes the steps.
- **Event-driven, not sleep-driven.** Uses `niri-state` waiters to observe actual state changes.
- **Reconciliation over macros.** Default mode is reconcile: skip what's already correct.
- **Leverage the stack.** Nirip owns session semantics. The libraries own compositor semantics.
- **Observable execution.** Every action produces a structured record.
- **Aggressive validation.** Spec problems caught at load time, not execution time.
- **Async-first, sync facade.** Internal engine is async. Thin sync wrapper for CLI/scripting.

**New principles:**

- **Concrete by default, injectable for testing.** The default runtime uses real `NiriState` and `NiriClient`. Tests inject fakes through explicit constructor parameters.
- **Typed intent over stringly-typed metadata.** Plan steps are a discriminated union of concrete step types. Invalid states are unrepresentable.
- **Globally consistent assignment.** Window matching produces a bipartite assignment, not independent local maxima.

---

## 3. Stack relationship

```
┌──────────────────────────────────────────────────────┐
│                       nirip                          │
│  session specs, matching, resolution, planning,      │
│  execution, capture, facade, CLI                     │
├──────────────────────────────────────────────────────┤
│               niri-state                             │
│  live state mirror, snapshots, selectors,            │
│  health, subscriptions, waiters                      │
├──────────────────────────────────────────────────────┤
│               niri-pypc                              │
│  typed IPC protocol, transport, request/reply        │
│  client, event stream, generated action types,       │
│  action builders                                     │
├──────────────────────────────────────────────────────┤
│                  Niri compositor                     │
│  Unix socket + event stream                          │
└──────────────────────────────────────────────────────┘
```

### Concrete dependency usage

**From niri-pypc, nirip uses:**
- `NiriClient` — to send compositor commands
- `actions.*` — the action builder module (spawn, focus_workspace, move_window_to_workspace, fullscreen_window, move_window_to_floating, move_window_to_tiling, set_column_width, set_window_height, focus_window, move_workspace_to_monitor, etc.)
- `Window`, `Workspace`, `Output` — the generated protocol types
- `NiriConfig` — connection configuration
- `ActionRequest` — the request wrapper type

**From niri-state, nirip uses:**
- `NiriState` — live state engine (connect, snapshot, subscribe, close)
- `Snapshot` — immutable compositor state with computed indexes
- `NiriStateConfig` — state engine configuration
- Selectors: `windows.list_windows`, `windows.list_windows_on_workspace`, `windows.get_window`, `workspaces.list_workspaces`, `workspaces.get_workspace`, `outputs.list_outputs`, `focus.get_focused_window`, `focus.get_focused_workspace`
- Waiters: `wait_until`, `wait_for_selector`, `watch`
- `HealthState` — to check liveness before operations
- `WaitTimeoutError` — to catch waiter timeouts

**From asyncio, nirip uses:**
- `asyncio.create_subprocess_exec` — to spawn applications from `SpawnSpec`

Nirip does **not** define protocol abstractions (`SnapshotLike`, `WindowLike`, `ActionClient`) in production code. These types come from the dependencies. Test doubles implement the same concrete interfaces or use dependency injection at the constructor level.

---

## 4. Internal pipeline

Unchanged from the original concept. The three-stage pipeline with explicit intermediate representations:

```
  YAML File
      │ parse + validate
      ▼
  SessionSpec
      │ apply defaults, flatten, validate
      ▼
  NormalizedSession
      │ match against Snapshot (global assignment)
      ▼
  Resolution
      ╱         ╲
     ▼           ▼
  SessionDiff   Plan (discriminated union steps)
  (display)        │ execute with verification
                   ▼
                ApplyResult
```

---

## 5. Model discipline

### 5.1 Shared base model

Every nirip model inherits from a shared base that enforces strictness:

```python
from pydantic import BaseModel, ConfigDict

class NiripModel(BaseModel):
    """Base for all nirip models. Rejects unknown fields, immutable by default."""
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=True,
    )
```

Rationale: the current codebase silently ignores typos in YAML and internal dictionaries because Pydantic defaults to `extra="ignore"`. For a declarative session format, that's a correctness bug. `frozen=True` makes all models immutable by default, which is correct for spec, normalization, resolution, planning, and execution result types.

**Exceptions:** `SessionRuntime` and `AppRuntimeState` (ephemeral execution tracking) use `frozen=False` because they accumulate state during a single apply.

### 5.2 Alias handling

`MatchRule` uses `any` as the YAML key (natural for users) and `any_of` as the Python attribute (avoids shadowing the builtin). This is handled with Pydantic's `validation_alias`:

```python
class MatchRule(NiripModel):
    any_of: list["MatchRule"] | None = Field(None, validation_alias="any")
    not_rule: "MatchRule" | None = Field(None, validation_alias="not")
```

---

## 6. Session spec format

### 6.1 Core models

Structurally identical to the original concept with these refinements:

```python
class MatchRule(NiripModel):
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
    any_of: list["MatchRule"] | None = Field(None, validation_alias="any")
    not_rule: "MatchRule" | None = Field(None, validation_alias="not")

    @model_validator(mode="after")
    def _validate_not_empty(self) -> "MatchRule":
        """Reject match rules with zero matching criteria."""
        ...


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
    def _validate_mutual_exclusion(self) -> "PlacementSpec":
        """floating and fullscreen are mutually exclusive."""
        ...


class AppSpec(NiripModel):
    name: str
    match: MatchRule
    spawn: SpawnSpec | None = None
    placement: PlacementSpec = Field(default_factory=PlacementSpec)
    optional: bool = False
    startup_timeout_s: float = 20.0
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

### 6.2 YAML format

Unchanged from the original concept. See concept document section 4.2.

### 6.3 Spec validation

Unchanged from the original concept. All validation rules apply. The key change is that **validation results are always surfaced**, never silently dropped:

```python
class ValidationResult(NiripModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    valid: bool
    errors: list[str]
    warnings: list[str]


class ValidatedSpec(NiripModel):
    """A spec that has passed validation, bundled with its validation report."""
    spec: SessionSpec
    validation: ValidationResult
```

The loader returns `ValidatedSpec`, not bare `SessionSpec`. Warnings are always available to the caller. The CLI displays them. The facade logs them.

---

## 7. Normalization layer

### 7.1 Models

```python
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
    app_index: dict[str, NormalizedApp]  # "workspace/app" -> NormalizedApp
```

### 7.2 Normalization passes

1. **Default merging** — apply `SessionOptions.default_startup_timeout_s` to apps without overrides.
2. **Flattening** — extract apps from nested workspace structure into flat list with `workspace_name`.
3. **Reference validation** — verify `depends_on` targets exist within the same workspace.
4. **Index construction** — build `app_index` for fast access during matching.

Unchanged from original concept.

---

## 8. Matching engine

### 8.1 Rule evaluation

The rule evaluator is a pure function: `(MatchRule, Window) -> (matched: bool, confidence: float, reasons: list[str])`.

Confidence scoring unchanged from original concept:

| Criterion | Confidence |
|---|---|
| `pid` exact | 1.0 |
| `app_id` exact | 1.0 |
| `app_id_regex` | 0.9 |
| `title` exact | 0.8 |
| `title_regex` | 0.7 |
| AND composition | minimum of sub-scores |
| OR composition | maximum of sub-scores |

### 8.2 Global assignment (new)

The current implementation evaluates each app independently against all windows. This allows two apps to claim the same window — a correctness bug for a session reconciler.

The refined matching phase produces a **globally consistent 1:1 assignment** using a greedy assignment algorithm:

```python
def assign_windows(
    apps: list[NormalizedApp],
    windows: Iterable[Window],
) -> list[MatchDecision]:
    """Produce a globally consistent app→window assignment.

    Algorithm:
    1. Evaluate every (app, window) pair → confidence matrix.
    2. Sort all candidate pairs by confidence descending, then by
       scoring priority (previously bound > PID > app_id > title).
    3. Greedily assign: take the highest-confidence unassigned pair,
       mark both app and window as claimed.
    4. Unassigned apps get status MISSING.
    5. Apps with multiple high-confidence candidates after assignment
       are flagged as AMBIGUOUS in rationale (but still assigned to best).
    """
```

This is a greedy bipartite assignment. It's not optimal in the general case (Hungarian algorithm would be), but for session management where most matches are unambiguous, greedy-by-confidence is correct, fast, and explainable. The key invariant is: **no window is assigned to more than one app**.

### 8.3 Match decision model

```python
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
        high = [c for c in self.candidates if c.confidence > 0.6]
        return len(high) > 1

    @computed_field
    @property
    def is_matched(self) -> bool:
        return self.assigned_window_id is not None
```

Note: `best` renamed to `assigned_window_id` for clarity about what the field means after global assignment.

---

## 9. Resolution layer

### 9.1 Models

Unchanged from original concept, with one fix:

**Drift detection when target workspace doesn't exist.** The current implementation only records `WRONG_WORKSPACE` drift if the target workspace already exists. If a matching window exists elsewhere and the desired workspace is missing, the app is classified as MATCHED when it should be DRIFTED. The fix:

```python
# In resolver: if window matched but desired workspace doesn't exist yet,
# still record WRONG_WORKSPACE drift. The planner will emit ENSURE_WORKSPACE
# before MOVE_WINDOW_TO_WORKSPACE, and dependency ordering handles sequencing.
```

### 9.2 Resolution algorithm

For each workspace in the normalized session:

1. **Check workspace existence** — does a workspace with this name exist in the snapshot?
2. **Check output placement** — if output declared, is workspace on correct output?
3. **Global window assignment** — run the assignment algorithm (section 8.2) across all apps and all windows. Each app gets at most one window; each window is claimed by at most one app.
4. **Detect drift** — for each matched window, compare current state against desired placement. Record `DriftItem` entries. **Importantly:** if the desired workspace doesn't exist yet, a matched window on any other workspace gets `WRONG_WORKSPACE` drift.
5. **Classify status** — MATCHED (no drift), DRIFTED (has drift items), MISSING (no match), AMBIGUOUS (multiple high-confidence but assigned to best), OPTIONAL_MISSING.
6. **Collect ambiguities** — for reporting, not blocking.

---

## 10. Planning layer — typed plan steps (major change)

### 10.1 Discriminated union step model

The original `PlanStep` is a string enum plus optional fields plus `metadata: dict`. This allows invalid states: a spawn step without a command, a wait step without a timeout, a move step without a window ID.

The refined model uses a **discriminated union of concrete step types**:

```python
from typing import Annotated, Literal
from pydantic import Discriminator


class StepBase(NiripModel):
    """Common fields for all plan steps."""
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    app_name: str | None = None
    workspace_name: str | None = None


class EnsureWorkspaceStep(StepBase):
    kind: Literal["ensure_workspace"] = "ensure_workspace"
    target_output: str | None = None


class MoveWorkspaceToOutputStep(StepBase):
    kind: Literal["move_workspace_to_output"] = "move_workspace_to_output"
    target_output: str


class SpawnWindowStep(StepBase):
    kind: Literal["spawn_window"] = "spawn_window"
    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False


class WaitForWindowStep(StepBase):
    kind: Literal["wait_for_window"] = "wait_for_window"
    match: MatchRule
    timeout_s: float


class MoveWindowToWorkspaceStep(StepBase):
    kind: Literal["move_window_to_workspace"] = "move_window_to_workspace"
    window_id: int
    target_workspace: str


class SetFloatingStep(StepBase):
    kind: Literal["set_floating"] = "set_floating"
    window_id: int


class SetTilingStep(StepBase):
    kind: Literal["set_tiling"] = "set_tiling"
    window_id: int


class SetFullscreenStep(StepBase):
    kind: Literal["set_fullscreen"] = "set_fullscreen"
    window_id: int
    fullscreen: bool  # True to enter, False to exit


class SetMaximizedStep(StepBase):
    kind: Literal["set_maximized"] = "set_maximized"
    window_id: int
    maximized: bool


class SetColumnWidthStep(StepBase):
    kind: Literal["set_column_width"] = "set_column_width"
    window_id: int
    proportion: float | None = None
    pixels: int | None = None


class SetWindowHeightStep(StepBase):
    kind: Literal["set_window_height"] = "set_window_height"
    window_id: int
    proportion: float | None = None
    pixels: int | None = None


class FocusWindowStep(StepBase):
    kind: Literal["focus_window"] = "focus_window"
    window_id: int


class FocusWorkspaceStep(StepBase):
    kind: Literal["focus_workspace"] = "focus_workspace"


# Discriminated union
PlanStep = Annotated[
    EnsureWorkspaceStep
    | MoveWorkspaceToOutputStep
    | SpawnWindowStep
    | WaitForWindowStep
    | MoveWindowToWorkspaceStep
    | SetFloatingStep
    | SetTilingStep
    | SetFullscreenStep
    | SetMaximizedStep
    | SetColumnWidthStep
    | SetWindowHeightStep
    | FocusWindowStep
    | FocusWorkspaceStep,
    Discriminator("kind"),
]
```

**Why this matters:**
- A `SpawnWindowStep` **must** carry the command. It's a required field.
- A `WaitForWindowStep` **must** carry the match rule and timeout. No data is lost between compilation and execution.
- A `MoveWindowToWorkspaceStep` **must** carry the window ID and target workspace. The executor doesn't need to fish through metadata dicts.
- Serialization and display work naturally because Pydantic handles discriminated unions.
- The `kind` literal field serves as both the discriminator tag and a human-readable step type identifier.

### 10.2 Plan model

```python
class Plan(NiripModel):
    session_name: str
    steps: list[PlanStep]
    resolution: Resolution
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def requires_spawn(self) -> bool:
        return any(isinstance(s, SpawnWindowStep) for s in self.steps)

    @computed_field
    @property
    def step_count(self) -> int:
        return len(self.steps)

    @computed_field
    @property
    def is_empty(self) -> bool:
        return len(self.steps) == 0
```

### 10.3 Plan compilation

The compiler transforms a `Resolution` into a `Plan`. The algorithm is the same as the original concept (section 10.2), with these refinements:

- **Spawn steps carry full SpawnSpec data.** The compiler copies `command`, `cwd`, `env`, `shell` from the `NormalizedApp.spawn` into the `SpawnWindowStep`.
- **Wait steps carry the match rule and timeout.** Copied from the `NormalizedApp`.
- **depends_on is honored.** Apps with `depends_on` references produce steps that depend on the referenced app's completion steps. This uses the topological sort already implemented in `ordering.py`.
- **Focus steps are emitted.** `PlacementSpec.focus: true` → `FocusWindowStep` at the end. `WorkspaceSpec.focus: true` → `FocusWorkspaceStep` at the end.
- **Column width and window height steps are emitted.** `PlacementSpec.column_width` → `SetColumnWidthStep`. `PlacementSpec.window_height` → `SetWindowHeightStep`. These are parsed from the `"px:800"` or `0.6` format at compilation time.

### 10.4 SessionDiff

Unchanged from original concept. It's a human-readable view derived from the Resolution, not the Plan.

---

## 11. Execution engine (major change)

### 11.1 Runtime ports

The executor operates against three runtime services:

```python
@dataclass
class SessionPorts:
    """Runtime services for session execution."""
    state: NiriState         # live state: snapshots, waiters
    client: NiriClient       # compositor commands
```

Process spawning uses `asyncio.create_subprocess_exec` directly — no protocol abstraction needed for something this simple.

### 11.2 Step execution

Each concrete step type has a dedicated execution function. No dispatch through string enums or metadata dicts:

```python
async def execute_step(
    step: PlanStep,
    ports: SessionPorts,
    runtime: SessionRuntime,
) -> StepResult:
    """Dispatch and execute a single plan step."""
    match step:
        case EnsureWorkspaceStep():
            return await _ensure_workspace(step, ports)
        case SpawnWindowStep():
            return await _spawn_window(step, ports, runtime)
        case WaitForWindowStep():
            return await _wait_for_window(step, ports, runtime)
        case MoveWindowToWorkspaceStep():
            return await _move_window(step, ports)
        case SetFloatingStep():
            return await _set_floating(step, ports)
        case SetTilingStep():
            return await _set_tiling(step, ports)
        case SetFullscreenStep():
            return await _set_fullscreen(step, ports)
        case SetMaximizedStep():
            return await _set_maximized(step, ports)
        case SetColumnWidthStep():
            return await _set_column_width(step, ports)
        case SetWindowHeightStep():
            return await _set_window_height(step, ports)
        case FocusWindowStep():
            return await _focus_window(step, ports)
        case FocusWorkspaceStep():
            return await _focus_workspace(step, ports)
        case MoveWorkspaceToOutputStep():
            return await _move_workspace(step, ports)
```

### 11.3 Step execution pattern

Each step handler follows the same pattern:

1. **Check if already satisfied** — read `ports.state.snapshot`, evaluate a predicate. If already done, return `StepOutcome.SKIPPED`.
2. **Build and send action** — use `niri_pypc.actions.*` builders to construct an `ActionRequest`, send via `ports.client.request(action)`.
3. **Wait for verification** — use `niri_state.api.waiters.wait_until()` to observe the expected state change in the live snapshot stream. Include a failure predicate for early detection of impossible states.
4. **Record result** — capture outcome, timing, resolved window IDs.

Example — spawn and wait:

```python
async def _spawn_window(
    step: SpawnWindowStep,
    ports: SessionPorts,
    runtime: SessionRuntime,
) -> StepResult:
    t0 = time.monotonic()

    # Build command
    if step.shell:
        cmd = step.command if isinstance(step.command, str) else " ".join(step.command)
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", cmd,
            cwd=step.cwd,
            env={**os.environ, **step.env} if step.env else None,
        )
    else:
        cmd = step.command if isinstance(step.command, list) else [step.command]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=step.cwd,
            env={**os.environ, **step.env} if step.env else None,
        )

    # Record PID for later matching
    if step.app_name and step.app_name in runtime.apps:
        runtime.apps[step.app_name].spawn_pid = proc.pid
        runtime.apps[step.app_name].spawned = True

    return StepResult(
        step=step,
        outcome=StepOutcome.COMPLETED,
        message=f"spawned process {proc.pid}",
        duration_s=time.monotonic() - t0,
    )


async def _wait_for_window(
    step: WaitForWindowStep,
    ports: SessionPorts,
    runtime: SessionRuntime,
) -> StepResult:
    t0 = time.monotonic()

    def window_appeared(snapshot: Snapshot) -> bool:
        for w in snapshot.windows.values():
            if _evaluate_match(step.match, w):
                return True
        return False

    try:
        snapshot = await wait_until(
            ports.state,
            window_appeared,
            config=ports.state._config,  # or pass config explicitly
            timeout=step.timeout_s,
        )
        # Find the matched window
        matched_id = next(
            w.id for w in snapshot.windows.values()
            if _evaluate_match(step.match, w)
        )
        # Record binding
        if step.app_name and step.app_name in runtime.apps:
            runtime.apps[step.app_name].matched_window_id = matched_id

        return StepResult(
            step=step,
            outcome=StepOutcome.COMPLETED,
            message=f"window {matched_id} appeared",
            window_id=matched_id,
            duration_s=time.monotonic() - t0,
        )
    except WaitTimeoutError:
        return StepResult(
            step=step,
            outcome=StepOutcome.TIMED_OUT,
            message=f"window did not appear within {step.timeout_s}s",
            duration_s=time.monotonic() - t0,
        )
```

### 11.4 Action translation

Each step maps directly to `niri_pypc.actions.*` builders:

| Step Type | niri-pypc builder |
|---|---|
| `EnsureWorkspaceStep` | `actions.focus_workspace(name)` (materializes the workspace) |
| `MoveWorkspaceToOutputStep` | `actions.move_workspace_to_monitor(output, reference=workspace_by_name(name))` |
| `SpawnWindowStep` | `asyncio.create_subprocess_exec(...)` (not IPC — direct process spawn) |
| `WaitForWindowStep` | No action — `wait_until()` on state |
| `MoveWindowToWorkspaceStep` | `actions.move_window_to_workspace(target, window_id=id)` |
| `SetFloatingStep` | `actions.move_window_to_floating(id=window_id)` |
| `SetTilingStep` | `actions.move_window_to_tiling(id=window_id)` |
| `SetFullscreenStep` | `actions.fullscreen_window(id=window_id)` (toggle) |
| `SetMaximizedStep` | `actions.maximize_window_to_edges(id=window_id)` (toggle) |
| `SetColumnWidthStep` | `actions.set_column_width(size_set_proportion(p))` or `actions.set_column_width(size_set_fixed(px))` |
| `SetWindowHeightStep` | `actions.set_window_height(size_set_proportion(p))` or `actions.set_window_height(size_set_fixed(px))` |
| `FocusWindowStep` | `actions.focus_window(id=window_id)` |
| `FocusWorkspaceStep` | `actions.focus_workspace(name)` |

Note: `SpawnWindowStep` uses `asyncio.create_subprocess_exec` because niri's `Spawn` action runs commands as children of niri (not nirip), which means nirip loses the PID for matching. By spawning directly, nirip knows the process PID and can use it for match scoring during `WaitForWindowStep`.

**Open question:** niri's `Spawn` action may be preferable in some contexts (e.g., if niri manages process lifecycle). We should support both modes: `shell: true` could use `actions.spawn_sh()`, while the default uses subprocess. This decision can be deferred — start with subprocess for PID tracking, add niri-spawn as an option later.

### 11.5 Execution models

```python
class StepOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class StepResult(NiripModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
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
        return [s for s in self.steps if s.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT)]
```

---

## 12. Public API — AsyncNirip (major change)

### 12.1 Real runtime by default

```python
class AsyncNirip:
    """Primary async API for nirip operations.

    Owns real connections to niri-state and niri-pypc by default.
    Accepts injected dependencies for testing.
    """

    def __init__(
        self,
        *,
        state: NiriState,
        client: NiriClient,
        config: NiripConfig | None = None,
    ) -> None:
        self._state = state
        self._client = client
        self._config = config or NiripConfig()

    @classmethod
    async def open(cls, config: NiripConfig | None = None) -> "AsyncNirip":
        """Connect to niri and initialize state."""
        cfg = config or NiripConfig()
        state = await NiriState.open()
        client = NiriClient.create()
        return cls(state=state, client=client, config=cfg)

    @property
    def snapshot(self) -> Snapshot:
        """Current compositor state."""
        return self._state.snapshot

    @property
    def health(self) -> HealthState:
        """Current state engine health."""
        return self._state.health()

    async def diff(self, spec: SessionSpec) -> SessionDiff:
        """Compute what would change without applying."""
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        return compile_diff(resolution)

    async def plan(self, spec: SessionSpec) -> Plan:
        """Compute the full execution plan."""
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        return compile_plan(resolution, normalized)

    async def apply(self, spec: SessionSpec) -> ApplyResult:
        """Apply a session spec: plan + execute + verify."""
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        plan = compile_plan(resolution, normalized)

        if plan.is_empty:
            return ApplyResult(
                session_name=spec.name,
                success=True,
                steps=[],
                total_duration_s=0.0,
            )

        ports = SessionPorts(state=self._state, client=self._client)
        return await execute_plan(plan, ports, spec.options)

    async def capture(self, *, name: str | None = None) -> CapturedSession:
        """Generate a session spec scaffold from current state."""
        return capture_from_snapshot(self.snapshot, name=name)

    async def doctor(self, spec: SessionSpec | None = None) -> DoctorReport:
        """Check connection health, spec validity, match ambiguities."""
        ...

    async def close(self) -> None:
        """Shut down connections."""
        await self._state.close()
        await self._client.close()

    async def __aenter__(self) -> "AsyncNirip":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
```

**Key difference from current implementation:** `AsyncNirip` owns real `NiriState` and `NiriClient` instances. The `open()` classmethod connects both. There is no `bind_snapshot()` method — the snapshot comes from the live state engine.

For testing, construct `AsyncNirip` directly with injected fakes:

```python
# In tests
nirip = AsyncNirip(state=fake_state, client=fake_client)
```

### 12.2 SyncNirip

Thin sync wrapper unchanged from original concept. Each method wraps the async counterpart with `asyncio.run()`.

### 12.3 Convenience functions

```python
def load_session(path: str | Path) -> ValidatedSpec:
    """Load and validate a session spec from YAML."""
    ...

def apply_session(spec: SessionSpec) -> ApplyResult:
    """One-shot: connect, apply, close."""
    async def _run() -> ApplyResult:
        async with await AsyncNirip.open() as nirip:
            return await nirip.apply(spec)
    return asyncio.run(_run())
```

---

## 13. Capture

Unchanged from original concept. Capture reads the current snapshot and generates a starter YAML scaffold. It stays humble: `app_id`-based match rules, no spawn commands, comments guiding refinement.

The only change is that capture uses `niri-state` selectors directly instead of protocol abstractions:

```python
async def capture(self, *, name: str | None = None) -> CapturedSession:
    snapshot = self.snapshot
    workspaces_spec = []

    for ws in workspaces.list_workspaces(snapshot):
        if ws.name is None:
            continue

        apps = []
        for w in windows.list_windows_on_workspace(snapshot, ws.id):
            apps.append(AppSpec(
                name=infer_app_name(w),
                match=infer_match_rule(w),
            ))

        workspaces_spec.append(WorkspaceSpec(
            name=ws.name,
            output=ws.output,
            apps=apps,
        ))

    return CapturedSession(
        spec=SessionSpec(name=name or "captured", workspaces=workspaces_spec),
        notes=generate_capture_notes(workspaces_spec),
    )
```

---

## 14. Error hierarchy

Mostly unchanged. One refinement: operational failures during apply are **always** structured `StepResult` outcomes, never exceptions. Exceptions are reserved for:

- **Spec errors** — invalid YAML, validation failures (caught at load time)
- **Connection errors** — can't reach niri (caught at open time)
- **Programming errors** — invalid API usage, lifecycle violations

```python
class NiripError(Exception):
    """Base for all nirip errors."""

class SpecError(NiripError):
    """Invalid session spec."""

class SpecValidationError(SpecError):
    """Spec validation failed."""

class PlanningError(NiripError):
    """Plan compilation failed."""

class CycleError(PlanningError):
    """Dependency cycle detected."""

class CaptureError(NiripError):
    """Capture operation failed."""

class NiripConnectionError(NiripError):
    """Cannot connect to niri."""
```

Removed from original: `MatchError`, `AmbiguousMatchError`, `ExecutionError`, `StepTimeoutError`. These are now represented as Resolution statuses and StepResult outcomes respectively, not exceptions.

---

## 15. Configuration

```python
class NiripConfig(NiripModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_dir: Path = Path("~/.config/nirip/sessions")
    state_dir: Path = Path("~/.local/state/nirip")
    default_timeout_s: float = 20.0
    confirm_before_apply: bool = True
```

Nirip does not wrap or duplicate `NiriConfig` or `NiriStateConfig`. Those are passed through to the underlying libraries when constructing `NiriState` and `NiriClient`.

---

## 16. Package layout

```
src/nirip/
  __init__.py              # public API re-exports
  __main__.py              # python -m nirip
  _base.py                 # NiripModel base class
  config.py                # NiripConfig
  errors.py                # error hierarchy

  spec/
    __init__.py
    models.py              # SessionSpec, WorkspaceSpec, AppSpec, MatchRule, etc.
    loader.py              # YAML parsing + validation → ValidatedSpec
    validators.py          # aggressive safety validation → ValidationResult
    defaults.py            # default option merging

  resolve/
    __init__.py
    normalizer.py          # spec → NormalizedSession
    matcher.py             # MatchRule evaluation, global window assignment
    resolver.py            # NormalizedSession + Snapshot → Resolution
    models.py              # NormalizedSession, MatchDecision, Resolution, etc.

  planning/
    __init__.py
    compiler.py            # Resolution → Plan, Resolution → SessionDiff
    ordering.py            # topological sort
    models.py              # PlanStep union, Plan, SessionDiff

  execution/
    __init__.py
    executor.py            # Plan + SessionPorts → ApplyResult
    handlers.py            # per-step-type execution functions
    predicates.py          # Snapshot predicates for skip-checking
    runtime.py             # SessionRuntime, AppRuntimeState
    models.py              # StepResult, StepOutcome, ApplyResult, SessionPorts

  capture/
    __init__.py
    capturer.py            # Snapshot → CapturedSession
    inference.py           # infer MatchRules from live Windows

  facade/
    __init__.py
    async_nirip.py         # AsyncNirip
    sync_nirip.py          # SyncNirip

  cli/
    __init__.py
    main.py                # CLI entrypoint
    commands.py            # apply, diff, capture, doctor, inspect
```

**Changes from original:**
- Added `_base.py` for shared `NiripModel`.
- `execution/actions.py` renamed to `execution/handlers.py` — it contains step execution handlers, not action construction. Action construction uses `niri_pypc.actions.*` directly.
- No `execution/actions.py` wrapping niri-pypc builders — those are already ergonomic.

---

## 17. CLI

Unchanged from original concept. Commands: `apply`, `diff`, `capture`, `inspect`, `doctor`, `watch`, `status`.

The key difference is that CLI commands now actually work because `AsyncNirip.open()` connects to a real compositor:

```python
async def cmd_apply(session_file: str, yes: bool = False) -> None:
    validated = load_spec_from_file(session_file)

    if validated.validation.warnings:
        for w in validated.validation.warnings:
            print(f"  ⚠ {w}")

    async with await AsyncNirip.open() as nirip:
        if not yes:
            diff = await nirip.diff(validated.spec)
            print(format_diff(diff))
            if diff.has_drift and not confirm("Apply?"):
                return

        result = await nirip.apply(validated.spec)
        print(format_result(result))
```

---

## 18. Testing strategy

### Pure function tests (no niri needed)
- **Spec parsing/validation** — YAML → SessionSpec, all edge cases, `extra="forbid"` rejects unknown keys.
- **Normalization** — default merging, flattening, reference resolution.
- **Match rule evaluation** — every criterion type, AND/OR/NOT, confidence scoring.
- **Global assignment** — multiple apps, shared candidates, 1:1 invariant.
- **Resolution** — all status types, drift detection including missing-workspace case.
- **Plan compilation** — resolution → typed steps, dependency ordering, data propagation.
- **Diff computation** — resolution → human-readable output.

### Fake-state tests (injected dependencies)
- **Executor** — inject a fake `NiriState` with controllable snapshots and a recording `NiriClient`. Verify correct actions sent, correct predicates checked.
- **Facade** — inject fakes into `AsyncNirip` constructor. Test full pipeline without compositor.

### Integration tests (requires running niri)
- Full apply cycle with real compositor.
- Capture and re-apply roundtrip.
- Reconcile idempotency.

### Snapshot replay tests
- Record real snapshots, replay matching/resolution/planning against them.
- Golden-file tests: input YAML + snapshot → expected plan/diff.

---

## 19. Implementation phases

### Phase 1: Foundation + Spec
- `_base.py` (NiripModel), `errors.py`, `config.py`
- `spec/` — all models with `extra="forbid"`, loader returning `ValidatedSpec`, validators with surfaced warnings
- Tests for all spec models and validation

### Phase 2: Matching + Resolution
- `resolve/normalizer.py` — unchanged
- `resolve/matcher.py` — rule evaluation (unchanged) + global assignment (new)
- `resolve/resolver.py` — resolution with fixed drift detection
- Tests for global assignment invariant, drift when workspace missing

### Phase 3: Planning
- `planning/models.py` — discriminated union step types
- `planning/compiler.py` — emit typed steps with full data, honor `depends_on` and focus
- `planning/ordering.py` — unchanged
- Tests for data propagation (spawn steps carry command, wait steps carry match rule)

### Phase 4: Execution + Facade
- `execution/` — real executor with `SessionPorts`, step handlers, predicates
- `facade/async_nirip.py` — owns `NiriState` + `NiriClient`, real `open()`
- `facade/sync_nirip.py` — thin wrapper
- Tests with injected fakes

### Phase 5: Capture + CLI + Polish
- `capture/` — unchanged logic, uses niri-state selectors directly
- `cli/` — working commands with real compositor connection
- `doctor`, `inspect`, `watch`, `status` commands

---

## 20. Decisions summary

| # | Decision | Rationale |
|---|---|---|
| 1 | **Concrete dependencies, not protocols** | NiriState and NiriClient are the default runtime. Inject fakes for testing via constructor. No SnapshotLike/WindowLike/ActionClient protocols in production code. |
| 2 | **Discriminated union plan steps** | Each step type carries exactly the data it needs. Invalid states are unrepresentable. Dispatch is a structural match, not string comparison. |
| 3 | **Global window assignment** | No window claimed by two apps. Greedy-by-confidence is correct for the common case and explainable. |
| 4 | **NiripModel base with extra="forbid"** | Typos in YAML and internal dicts are rejected, not silently ignored. |
| 5 | **ValidatedSpec bundles spec + warnings** | Validation warnings are never dropped. Always available to CLI, facade, doctor. |
| 6 | **Subprocess spawn for PID tracking** | Direct process spawn gives nirip the PID for match scoring. niri's Spawn action runs under niri, losing the PID. |
| 7 | **SessionPorts dataclass** | Clean grouping of runtime services (state + client) without wrapper ceremony. |
| 8 | **Drift detection for missing workspaces** | A matched window on the wrong workspace is DRIFTED even if the target workspace doesn't exist yet. |
| 9 | **Operational failures as StepResult** | Exceptions for programmer errors and connection failures. Structured outcomes for runtime behavior. |
| 10 | **No execution/actions.py wrapper** | niri-pypc's `actions.*` builders are already ergonomic. Don't wrap them. |
