# Nirip: Declarative Session Manager for Niri

A tmuxp-like workspace orchestrator for the Niri Wayland compositor, built on `niri-pypc` and `niri-state`.

---

## The one-paragraph version

**Nirip** is a Python library and CLI that restores, reconciles, and captures named desktop sessions on the Niri compositor. Users declare workspace layouts in YAML — which apps go where, how to match them, what to launch if they're missing. Nirip reads live compositor state through `niri-state`, computes a plan to converge the desktop toward the declared layout, and executes that plan step-by-step with event-confirmed verification. It is a **session reconciler**, not a macro runner.

---

## 1. What Nirip is

Nirip is the declarative layer on top of a two-library stack:

```
┌─────────────────────────────────────────┐
│               nirip                     │
│  session specs, matching, planning,     │
│  execution, capture, CLI                │
├─────────────────────────────────────────┤
│            niri-state (v0.2.0)          │
│  live state mirror, snapshots,          │
│  selectors, health, subscriptions       │
├─────────────────────────────────────────┤
│            niri-pypc (v0.3.1)           │
│  typed IPC protocol, transport,         │
│  request/reply client, event stream     │
├─────────────────────────────────────────┤
│               Niri compositor           │
│  Unix socket + event stream             │
└─────────────────────────────────────────┘
```

**niri-pypc** already handles: typed protocol models (Window, Workspace, Output, 110+ actions), async transport, request/reply client, persistent event stream, externally-tagged serde codec — all pinned to niri-ipc 25.11.

**niri-state** already handles: live state mirror via event reduction, immutable `Snapshot` with computed indexes, selectors for windows/workspaces/outputs/focus/keyboard/overview, health tracking (BOOTSTRAPPING → LIVE → STALE → CLOSED), subscriber broadcast, reconciliation, invariant checking, auto-resync, async waiters (`wait_until`, `wait_for_selector`, `watch`).

**Nirip** needs to handle: session spec format, matching engine, diff/plan computation, step-by-step execution with verification, session capture, managed state tracking, and CLI.

---

## 2. Design principles

### Declarative first
Users write desired state in YAML. Nirip computes the steps. Users never script IPC sequences.

### Event-driven, not sleep-driven
No `sleep(2)` and hope. Nirip uses `niri-state`'s subscription system and waiters to observe actual state changes before proceeding.

### Reconciliation over macros
Default mode is reconcile: if a matching window already exists in the right place, skip it. Only spawn/move what's actually missing or misplaced. Every `apply` is idempotent.

### Leverage the stack
Nirip does not reimplement protocol handling, state tracking, or event reduction. It consumes `Snapshot` objects from `niri-state` and dispatches `Action` requests through `niri-pypc`. The boundary is clean: nirip owns session semantics, the libraries own compositor semantics.

### Observable execution
Every action produces a structured record. Users can `diff` before `apply`, watch progress during execution, and inspect results after. Matching decisions are always explainable.

---

## 3. Session spec format

The session spec is the user-authored YAML file describing a desired desktop layout. It is the primary user interface of nirip.

### 3.1 Core models

```python
from pydantic import BaseModel, Field

class MatchRule(BaseModel):
    """How to find an existing window that fills this role."""
    app_id: str | None = None             # exact app_id match
    app_id_regex: str | None = None       # regex app_id match
    title: str | None = None              # exact title match
    title_regex: str | None = None        # regex title match
    pid: int | None = None                # exact PID match (rare, mostly internal)
    any: list["MatchRule"] | None = None  # OR: any sub-rule matches
    not_rule: "MatchRule" | None = None   # negate a sub-rule
    # Multiple flat fields are implicitly ANDed

class SpawnSpec(BaseModel):
    """How to launch a window if no match is found."""
    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False                   # if True, run via sh -c

class PlacementSpec(BaseModel):
    """Where a window should end up."""
    floating: bool = False
    focus: bool = False
    column_width: float | str | None = None   # 0.0-1.0 proportion, or "px:800"
    window_height: float | str | None = None  # 0.0-1.0 proportion, or "px:600"

class AppSpec(BaseModel):
    """A single window role within a workspace."""
    name: str                                     # human label, e.g. "editor"
    match: MatchRule                               # how to find it
    spawn: SpawnSpec | None = None                 # how to launch it (None = match-only)
    placement: PlacementSpec = Field(default_factory=PlacementSpec)
    optional: bool = False                         # if True, don't fail when missing
    startup_timeout_s: float = 20.0                # max wait after spawn
    depends_on: list[str] = Field(default_factory=list)  # other app names in this workspace

class WorkspaceSpec(BaseModel):
    """A named workspace and its desired window layout."""
    name: str
    output: str | None = None                      # pin to a specific output
    apps: list[AppSpec] = Field(default_factory=list)

class SessionOptions(BaseModel):
    """Global options for session apply behavior."""
    mode: str = "reconcile"                # "reconcile" | "clean"
    match_existing: bool = True            # try to match running windows
    launch_missing: bool = True            # spawn apps that don't match
    stop_on_error: bool = True             # abort remaining steps on failure
    move_unmatched: bool = False           # move non-session windows out of managed workspaces
    default_startup_timeout_s: float = 20.0

class SessionSpec(BaseModel):
    """Top-level session declaration."""
    name: str
    description: str = ""
    options: SessionOptions = Field(default_factory=SessionOptions)
    workspaces: list[WorkspaceSpec]
```

### 3.2 YAML example

```yaml
name: dev-day
description: "Full development environment"
options:
  mode: reconcile
  match_existing: true
  launch_missing: true

workspaces:
  - name: code
    output: DP-1
    apps:
      - name: editor
        match:
          app_id: dev-editor
        spawn:
          command: ["kitty", "--class", "dev-editor", "-e", "nvim"]
          cwd: ~/projects/current
        placement:
          focus: true

      - name: terminal
        match:
          app_id: dev-term
        spawn:
          command: ["kitty", "--class", "dev-term"]
          cwd: ~/projects/current

      - name: docs
        match:
          app_id: firefox
          title_regex: "docs\\.rs|MDN"
        spawn:
          command: ["firefox", "--new-window", "https://docs.rs"]

  - name: comms
    apps:
      - name: slack
        match:
          app_id: Slack
        spawn:
          command: ["slack"]

      - name: discord
        match:
          app_id: discord
        spawn:
          command: ["discord"]
        optional: true

  - name: media
    apps:
      - name: spotify
        match:
          app_id: spotify
        spawn:
          command: ["spotify"]
        optional: true
```

### 3.3 Format notes

- YAML is the canonical format. TOML support may be added later but YAML is the default.
- `match` fields are composable: flat fields are implicitly ANDed, `any` provides OR, `not_rule` provides negation.
- `spawn` is optional — an app with only `match` will be found if running but never launched.
- `placement.column_width` and `placement.window_height` accept proportions (0.0–1.0) or pixel strings ("px:800").
- `depends_on` allows ordering within a workspace: "terminal" can depend on "editor" to ensure editor spawns first.

---

## 4. Architecture

### 4.1 Package layout

```
src/nirip/
  __init__.py              # public API re-exports
  client.py                # NiripClient: top-level orchestrator
  errors.py                # error hierarchy

  spec/
    __init__.py
    models.py              # SessionSpec, WorkspaceSpec, AppSpec, etc.
    loader.py              # YAML parsing + validation
    defaults.py            # default option merging

  matching/
    __init__.py
    engine.py              # match evaluation against live state
    result.py              # MatchResult, MatchOutcome models

  planning/
    __init__.py
    planner.py             # plan(spec, snapshot) -> Plan
    models.py              # PlanStep, Plan, PlanDiff
    differ.py              # compute diff without execution

  execution/
    __init__.py
    executor.py            # run plan steps against live state
    models.py              # StepResult, ExecutionResult
    actions.py             # translate plan steps to niri-pypc actions

  capture/
    __init__.py
    capturer.py            # snapshot -> SessionSpec scaffold
    inference.py           # infer match rules from live windows

  state/
    __init__.py
    managed.py             # track which windows nirip placed (ephemeral + persistent)

  cli/
    __init__.py
    main.py                # CLI entrypoint (typer or click)
    commands.py            # apply, diff, capture, inspect, doctor, watch
```

### 4.2 Dependency flow

```
cli/ ──────────────► client.py
                        │
            ┌───────────┼───────────────┐
            ▼           ▼               ▼
        spec/       planning/       capture/
            │           │               │
            └─────┬─────┘               │
                  ▼                     │
             matching/ ◄────────────────┘
                  │
                  ▼
            execution/
                  │
                  ▼
             state/managed
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
   niri-state            niri-pypc
   (snapshots,           (actions,
    selectors,            requests,
    waiters)              client)
```

---

## 5. Matching engine

The matching engine determines whether a live window corresponds to a declared app role. This is the most important piece of nirip's logic — correct matching makes reconciliation work; bad matching causes chaos.

### 5.1 Match evaluation

```python
class MatchOutcome(BaseModel):
    """Result of evaluating a MatchRule against a single window."""
    matched: bool
    window_id: int
    confidence: float          # 0.0-1.0, higher = more specific match
    reasons: list[str]         # human-readable trace of what matched/failed

class MatchResult(BaseModel):
    """Result of matching an AppSpec against all live windows."""
    app_name: str
    candidates: list[MatchOutcome]     # all windows evaluated
    best_match: MatchOutcome | None    # highest-confidence match, if any
    ambiguous: bool                     # True if multiple high-confidence matches
```

### 5.2 Match evaluation rules

Given a `MatchRule` and a `Window` (from `niri-state` snapshot):

1. `app_id` — exact string match against `window.app_id`
2. `app_id_regex` — regex match against `window.app_id`
3. `title` — exact string match against `window.title`
4. `title_regex` — regex match against `window.title`
5. `pid` — exact match against `window.pid`
6. Multiple flat fields — all must match (implicit AND)
7. `any` — at least one sub-rule must match (OR)
8. `not_rule` — the sub-rule must NOT match (negation)

Confidence scoring:
- `app_id` exact match: 1.0
- `app_id_regex` match: 0.9
- `title` exact match: 0.8
- `title_regex` match: 0.7
- PID match: 1.0
- AND/OR compositions: minimum/maximum of sub-scores
- Multiple criteria increase confidence (more specific = more certain)

### 5.3 Match context

The matching engine receives a `Snapshot` from `niri-state` and uses its selectors:

```python
from niri_state.api.selectors import windows, workspaces

# Get all windows to evaluate
all_windows = windows.list_windows(snapshot)

# Optionally scope to a workspace
ws = workspaces.get_workspace_by_name(snapshot, "code")  # via custom selector
ws_windows = windows.list_windows_on_workspace(snapshot, ws.id)
```

---

## 6. Planning layer

The planner takes a `SessionSpec` and a `Snapshot` and produces a `Plan` — an ordered list of steps to converge the desktop toward the desired state.

### 6.1 Plan models

```python
class StepKind(StrEnum):
    ENSURE_WORKSPACE = "ensure_workspace"
    MATCH_WINDOW = "match_window"
    SPAWN_WINDOW = "spawn_window"
    WAIT_FOR_WINDOW = "wait_for_window"
    MOVE_WINDOW_TO_WORKSPACE = "move_window_to_workspace"
    MOVE_WINDOW_TO_FLOATING = "move_window_to_floating"
    MOVE_WINDOW_TO_TILING = "move_window_to_tiling"
    SET_COLUMN_WIDTH = "set_column_width"
    SET_WINDOW_HEIGHT = "set_window_height"
    FOCUS_WINDOW = "focus_window"
    FOCUS_WORKSPACE = "focus_workspace"

class PlanStep(BaseModel):
    id: str                              # unique step ID
    kind: StepKind
    app_name: str | None = None          # which AppSpec this serves
    workspace_name: str | None = None    # target workspace
    description: str                     # human-readable summary
    depends_on: list[str] = Field(default_factory=list)  # step IDs
    metadata: dict[str, Any] = Field(default_factory=dict)

class Plan(BaseModel):
    session_name: str
    steps: list[PlanStep]
    match_summary: dict[str, MatchResult]  # app_name -> match result
    warnings: list[str] = Field(default_factory=list)
```

### 6.2 Planning algorithm

For each workspace in the session spec:

1. **Ensure workspace exists** — if no workspace with this name exists in the snapshot, emit `ENSURE_WORKSPACE` step (will use `SetWorkspaceNameAction` on an empty workspace or rely on niri's auto-creation).

2. **Match existing windows** — for each app in the workspace, run the matching engine against all live windows. Record results.

3. **For matched windows:**
   - If the window is already on the correct workspace: skip (or emit placement adjustments if needed).
   - If the window is on a different workspace: emit `MOVE_WINDOW_TO_WORKSPACE`.
   - If floating state is wrong: emit `MOVE_WINDOW_TO_FLOATING` or `MOVE_WINDOW_TO_TILING`.

4. **For unmatched apps (when `launch_missing` is true):**
   - If `spawn` is defined: emit `SPAWN_WINDOW` followed by `WAIT_FOR_WINDOW`.
   - If `spawn` is not defined and `optional` is false: emit a warning.

5. **Apply placement preferences:**
   - Column width, window height adjustments.
   - Focus target (last step).

6. **Dependency ordering** — respect `depends_on` within each workspace. Topological sort steps so dependencies execute first.

### 6.3 Diff (plan without execution)

`nirip diff session.yaml` computes a plan and displays it without executing:

```python
class PlanDiff(BaseModel):
    """Human-readable diff between desired and current state."""
    already_matched: list[str]       # "editor: matched window 42 (app_id=dev-editor)"
    will_spawn: list[str]            # "terminal: will spawn ['kitty', '--class', 'dev-term']"
    will_move: list[str]             # "docs: window 87 → workspace 'code'"
    will_adjust: list[str]           # "editor: set column width to 0.6"
    warnings: list[str]              # "discord: no match found, marked optional"
    errors: list[str]                # "slack: no match and no spawn command"
```

---

## 7. Execution engine

The executor runs plan steps against live compositor state, using `niri-state` for verification and `niri-pypc` for actions.

### 7.1 Execution flow

```python
class StepOutcome(StrEnum):
    COMPLETED = "completed"    # executed and verified
    SKIPPED = "skipped"        # already satisfied
    FAILED = "failed"          # action failed or verification failed
    TIMED_OUT = "timed_out"    # verification event not received in time

class StepResult(BaseModel):
    step: PlanStep
    outcome: StepOutcome
    message: str
    window_id: int | None = None       # resolved window ID, if applicable
    duration_s: float = 0.0

class ExecutionResult(BaseModel):
    session_name: str
    success: bool
    steps: list[StepResult]
    completed: int
    skipped: int
    failed: int
    timed_out: int
    total_duration_s: float
```

### 7.2 Step execution pattern

For each step, the executor follows the same pattern:

1. **Check preconditions** — read current `snapshot` from `niri-state`, verify the step's dependencies are satisfied.
2. **Check if already done** — if the desired state already exists, mark `SKIPPED`.
3. **Execute action** — translate the step to a `niri-pypc` action and send it via `NiriClient.request()`.
4. **Wait for verification** — use `niri-state`'s `wait_until` or `wait_for_selector` to observe the expected state change in a subsequent snapshot. Timeout after `startup_timeout_s`.
5. **Record result** — capture outcome, timing, and any resolved window IDs.

### 7.3 Action translation

Each `StepKind` maps to specific `niri-pypc` actions:

| StepKind | niri-pypc Action |
|---|---|
| `ENSURE_WORKSPACE` | `FocusWorkspaceAction(reference=Name(name))` + verify workspace exists |
| `SPAWN_WINDOW` | `SpawnAction(command=...)` |
| `WAIT_FOR_WINDOW` | No action — wait on `niri-state` for matching window to appear |
| `MOVE_WINDOW_TO_WORKSPACE` | `MoveWindowToWorkspaceAction(window_id=..., reference=Name(...))` |
| `MOVE_WINDOW_TO_FLOATING` | `MoveWindowToFloatingAction(id=...)` |
| `MOVE_WINDOW_TO_TILING` | `MoveWindowToTilingAction(id=...)` |
| `SET_COLUMN_WIDTH` | `SetColumnWidthAction(id=..., change=SetProportion(...))` |
| `SET_WINDOW_HEIGHT` | `SetWindowHeightAction(id=..., change=SetProportion(...))` |
| `FOCUS_WINDOW` | `FocusWindowAction(id=...)` |
| `FOCUS_WORKSPACE` | `FocusWorkspaceAction(reference=Name(...))` |

### 7.4 Integration with niri-state

The executor holds a reference to `NiriState` and uses its subscription system:

```python
from niri_state import NiriState
from niri_state.api.waiters import wait_until, wait_for_selector
from niri_state.api.selectors import windows, workspaces

async def execute_spawn_and_wait(
    state: NiriState,
    client: NiriClient,
    app: AppSpec,
    workspace_name: str,
    timeout: float,
) -> StepResult:
    # Send spawn action
    await client.request(ActionRequest(
        payload=Action(root=SpawnAction(command=app.spawn.command))
    ))

    # Wait for a new window matching the app's rule
    def window_appeared(snapshot: Snapshot) -> bool:
        for w in windows.list_windows(snapshot):
            if evaluate_match(app.match, w).matched:
                return True
        return False

    try:
        snapshot = await wait_until(state, window_appeared, timeout=timeout)
        matched = find_matched_window(snapshot, app.match)
        return StepResult(outcome=StepOutcome.COMPLETED, window_id=matched.id, ...)
    except WaitTimeoutError:
        return StepResult(outcome=StepOutcome.TIMED_OUT, ...)
```

---

## 8. Managed state

Nirip tracks which windows it has placed during a session apply. This is needed for:
- Knowing what to clean up on re-apply
- Avoiding re-matching windows nirip didn't place
- Supporting `move_unmatched` (moving non-session windows out of managed workspaces)

### 8.1 Runtime registry (ephemeral)

```python
class AppRuntimeState(BaseModel):
    app_name: str
    workspace_name: str
    matched_window_id: int | None = None
    spawned: bool = False
    completed: bool = False
    error: str | None = None

class SessionRuntime(BaseModel):
    """Ephemeral state during a single apply operation."""
    session_name: str
    apps: dict[str, AppRuntimeState] = Field(default_factory=dict)
    started_at: float | None = None
```

### 8.2 Persistent tracking (optional)

For multi-apply workflows, nirip can persist a lightweight record of managed windows:

```python
class ManagedSession(BaseModel):
    """Persisted after apply for later re-apply or teardown."""
    session_name: str
    applied_at: str                        # ISO timestamp
    managed_windows: dict[str, int]        # app_name -> window_id
    managed_workspaces: list[str]          # workspace names
```

Stored as JSON in `$XDG_STATE_HOME/nirip/sessions/<name>.json`. This is optional — nirip works fine without it by re-matching from scratch.

---

## 9. Capture

Capture reads the current compositor state and generates a starter YAML session spec. It is a **scaffold generator**, not a promise of exact restoration.

### 9.1 Capture logic

```python
async def capture(state: NiriState) -> SessionSpec:
    snapshot = state.snapshot

    workspaces_spec = []
    for ws in workspaces.list_workspaces(snapshot):
        if ws.name is None:
            continue  # skip unnamed workspaces

        apps = []
        for w in windows.list_windows_on_workspace(snapshot, ws.id):
            app = AppSpec(
                name=infer_app_name(w),           # derive from app_id
                match=infer_match_rule(w),         # app_id + optional title hint
                # spawn is left empty — user fills in
            )
            apps.append(app)

        workspaces_spec.append(WorkspaceSpec(
            name=ws.name,
            output=ws.output,
            apps=apps,
        ))

    return SessionSpec(
        name="captured",
        workspaces=workspaces_spec,
    )
```

### 9.2 Match rule inference

For each captured window:
- Always include `app_id` if present (most reliable identifier)
- Include `title_regex` as a comment/suggestion if the title contains useful identifiers
- Note when multiple windows share the same `app_id` (user needs to differentiate)

The captured YAML includes comments guiding the user to add `spawn` commands and refine match rules.

---

## 10. CLI

The CLI is nirip's primary user interface. Built with `typer` or `click`.

### 10.1 Commands

```
nirip apply <session.yaml>     Apply a session spec (reconcile by default)
nirip diff <session.yaml>      Show what would change without applying
nirip capture [-o file.yaml]   Generate a session spec from current state
nirip inspect                  Print current compositor state summary
nirip doctor                   Verify niri connection, spec validity, match sanity
nirip watch                    Stream state changes for debugging
nirip status                   Show managed sessions and their window states
```

### 10.2 `nirip apply` flow

1. Load and validate the session spec
2. Connect to niri via `NiriState.open()`
3. Wait for initial snapshot (bootstrapping → live)
4. Compute plan from spec + snapshot
5. Display plan summary, ask for confirmation (unless `--yes`)
6. Execute steps, streaming progress
7. Report final result
8. Optionally persist managed state

### 10.3 `nirip inspect` output

```
Outputs:
  DP-1 (2560x1440 @ 144Hz)  [focused]
  eDP-1 (1920x1080 @ 60Hz)

Workspaces:
  1: code     (DP-1)  [active]
    - kitty (dev-editor)  "~/projects – nvim"  [focused]
    - kitty (dev-term)    "~/projects – zsh"
    - firefox             "docs.rs – MDN Web Docs"
  2: comms    (DP-1)
    - Slack               "Slack | #general"
  3: media    (eDP-1)  [active]
    - spotify             "Spotify"
```

---

## 11. Public API

The library API is intentionally small. Most users interact via CLI.

```python
class NiripClient:
    """Top-level orchestrator for nirip operations."""

    def __init__(self, config: NiripConfig | None = None): ...

    async def inspect(self) -> Snapshot:
        """Return current compositor state snapshot."""

    async def diff(self, spec: SessionSpec) -> PlanDiff:
        """Compute what would change without applying."""

    async def plan(self, spec: SessionSpec) -> Plan:
        """Compute the full execution plan."""

    async def apply(self, spec: SessionSpec) -> ExecutionResult:
        """Apply a session spec: plan + execute + verify."""

    async def capture(self) -> SessionSpec:
        """Generate a session spec from current state."""

    async def doctor(self, spec: SessionSpec | None = None) -> DoctorReport:
        """Check connection health, spec validity, match ambiguities."""

    async def close(self) -> None:
        """Shut down connections."""
```

### Sync wrappers

For simple scripting, provide synchronous wrappers:

```python
from nirip import load_session, apply_session

spec = load_session("dev-day.yaml")
result = apply_session(spec)
```

These wrap the async API with `asyncio.run()`.

---

## 12. Error hierarchy

```python
class NiripError(Exception):
    """Base for all nirip errors."""

class SpecError(NiripError):
    """Invalid session spec (parse error, validation failure)."""

class MatchError(NiripError):
    """Window matching failure."""

class AmbiguousMatchError(MatchError):
    """Multiple windows match with similar confidence."""

class PlanningError(NiripError):
    """Plan generation failed (unresolvable conflicts)."""

class ExecutionError(NiripError):
    """Step execution failed."""

class TimeoutError(ExecutionError):
    """Window didn't appear within timeout."""

class CaptureError(NiripError):
    """Capture failed."""
```

Nirip does not wrap `niri-pypc` or `niri-state` errors — those propagate directly. Nirip's errors cover only session-level semantics.

---

## 13. Configuration

```python
class NiripConfig(BaseModel, frozen=True):
    """Nirip-level configuration."""
    state_config: NiriStateConfig | None = None     # pass through to niri-state
    session_dir: Path = Path("~/.config/nirip/sessions")
    state_dir: Path = Path("~/.local/state/nirip")
    default_timeout_s: float = 20.0
    confirm_before_apply: bool = True
```

Nirip inherits all connection/transport config from `niri-state` → `niri-pypc`. No duplication.

---

## 14. Testing strategy

### Unit tests
- Spec parsing and validation (valid YAML, invalid YAML, edge cases)
- Match rule evaluation against mock `Window` objects
- Plan generation from spec + mock snapshot
- Diff computation

### Snapshot replay tests
- Record real `Snapshot` objects from niri sessions
- Verify matching, planning, and diff against recorded state
- Golden-file tests: input YAML + snapshot → expected plan

### Integration tests (requires running niri)
- Full apply cycle with real compositor
- Capture and re-apply roundtrip
- Reconcile idempotency (apply twice = same result)

### Mock transport tests
- Use `niri-state`'s architecture to inject fake snapshots
- Test executor logic without a real compositor

---

## 15. Implementation phases

### Phase 1: Foundation
- Session spec models (Pydantic)
- YAML loader with validation
- Matching engine (evaluate MatchRule against Window)
- Basic `inspect` command using `niri-state` snapshot + selectors

**Deliverable:** Parse session YAML, connect to niri, display state.

### Phase 2: Planning and diff
- Planner: spec + snapshot → Plan
- Differ: Plan → human-readable diff
- `nirip diff` command

**Deliverable:** Preview what would happen without touching anything.

### Phase 3: Execution
- Executor: run Plan steps with event-verified confirmation
- Action translation (PlanStep → niri-pypc Action)
- Integration with `niri-state` waiters for verification
- Managed state tracking
- `nirip apply` command

**Deliverable:** Actually restore sessions.

### Phase 4: Capture
- Snapshot → SessionSpec scaffold
- Match rule inference from live windows
- YAML output with guiding comments
- `nirip capture` command

**Deliverable:** Bootstrap specs from existing setups.

### Phase 5: Polish
- `nirip doctor` (connection check, spec validation, match ambiguity detection)
- `nirip watch` (stream state changes)
- `nirip status` (show managed sessions)
- Better error messages and diagnostics
- Documentation and examples

---

## 16. Key integration patterns

### Reading state

```python
from niri_state import NiriState
from niri_state.api.selectors import windows, workspaces, outputs, focus

async with NiriState() as state:
    snap = state.snapshot
    focused = focus.get_focused_window(snap)
    all_ws = workspaces.list_workspaces(snap)
    ws_windows = windows.list_windows_on_workspace(snap, ws_id)
```

### Sending actions

```python
from niri_pypc import NiriClient
from niri_pypc.types.generated.request import ActionRequest
from niri_pypc.types.generated.action import Action, SpawnAction, FocusWorkspaceAction
from niri_pypc.types.generated.models import WorkspaceReferenceArg, NameWorkspaceReferenceArg

async with NiriClient.connect() as client:
    # Spawn a window
    await client.request(ActionRequest(
        payload=Action(root=SpawnAction(command=["kitty"]))
    ))

    # Focus a workspace by name
    await client.request(ActionRequest(
        payload=Action(root=FocusWorkspaceAction(
            reference=WorkspaceReferenceArg(root=NameWorkspaceReferenceArg(payload="code"))
        ))
    ))
```

### Waiting for state changes

```python
from niri_state.api.waiters import wait_until

# Wait for a window with app_id "dev-editor" to appear
snapshot = await wait_until(
    state,
    lambda snap: any(
        w.app_id == "dev-editor"
        for w in snap.windows.values()
    ),
    timeout=20.0,
)
```

---

## 17. Scope and non-goals

### In scope (v1)
- Workspace-oriented session restore and reconciliation
- Event-driven spawn → match → place → verify cycle
- Diff / apply / capture workflow
- YAML session specs
- Python library and CLI
- Idempotent reconciliation

### Out of scope (v1)
- Exact column/tile geometry replay (niri IPC doesn't fully support this yet)
- App-specific integrations (restoring browser tabs, editor sessions, etc.)
- Multi-version niri compatibility (pinned to niri-ipc 25.11)
- Non-niri compositors
- Daemon mode / auto-apply on events
- tmux-style session switching (nirip is apply-on-demand, not a persistent manager)

### Future possibilities
- Session groups / profiles (apply multiple session specs)
- Conditional workspace specs (only apply on multi-monitor setups)
- Integration with sidebard for context-aware session switching
- Watch mode: continuously reconcile toward declared state
