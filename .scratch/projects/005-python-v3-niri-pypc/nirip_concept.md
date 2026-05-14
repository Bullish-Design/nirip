Overview: Nirip should be a **declarative, event-driven session manager for niri**, not just a Python wrapper around IPC commands. In pure Python, the core idea is to **mirror the Rust crate’s event-stream state model**, then build a planner/reconciler on top of that. Because you’re pinning to a specific `niri-ipc` version, we can optimize for correctness and clarity over cross-version compatibility.

A good one-line mission for Nirip would be:

**Nirip restores and reconciles named niri work sessions from a declarative spec by observing live compositor state and applying verified steps until the session converges.**

niri’s IPC model fits this well because the event stream gives full initial state followed by incremental updates, and the official crate’s `state` module is built around exactly that usage pattern. Requests are still processed one-by-one rather than atomically, so Nirip should be designed as a reconciler, not a fire-and-forget macro runner.

# 1. What Nirip is

Nirip is a Python library and CLI for defining, applying, inspecting, and capturing **niri sessions**.

A “session” in Nirip is not a tmux pane graph. It is a declarative description of:

* named workspaces
* intended app processes
* how windows are matched
* where matched windows should live
* optional layout/state preferences
* focus and startup policies
* rules for convergence and verification

The closest mental model is:

**tmuxp for GUI sessions on niri, but adapted to the realities of asynchronous Wayland windows.**

That means Nirip should promise:

* reproducible startup
* deterministic best-effort placement
* explicit matching and verification
* idempotent re-apply
* readable diffs between desired and live state

It should **not** promise exact pixel-perfect replay of every GUI layout in every app.

# 2. Design principles

## Declarative first

The user writes desired state. Nirip computes the steps.

## Event-driven, not sleep-driven

No fixed “sleep 2 seconds and hope.” Nirip should wait on observed state changes.

## Reconciliation over macros

Because niri processes requests separately, Nirip should continuously compare desired and actual state and advance only when preconditions are satisfied.

## Python-only, but strongly modeled

All core library classes should be Pydantic models where practical, especially for user-facing specs, internal plans, results, and state snapshots.

## Pinned protocol

Since you are pinning directly to a `niri-ipc` version, Nirip can treat the protocol as fixed for that release and keep the implementation clean.

## Observable execution

Every action should produce a structured record: attempted request, observed events, resulting state, success/failure.

# 3. Product surface

Nirip should have three layers.

## A. Python library

Used by users and higher-level tooling.

Example shape:

```python
from nirip import NiripClient, SessionSpec

client = NiripClient()
spec = SessionSpec.model_validate_yaml(open("work.yaml").read())
result = client.apply(spec)
```

## B. CLI

Primary operations:

* `nirip apply session.yaml`
* `nirip diff session.yaml`
* `nirip capture`
* `nirip inspect`
* `nirip doctor`
* `nirip watch`

## C. YAML session format

Human-authored, stable, easy to review in git.

# 4. Core architecture

The architecture should be split cleanly.

## 4.1 Protocol layer

Purpose: encode and decode the pinned `niri-ipc` request/response/event schema.

This layer should contain:

* request models
* response models
* event models
* object models for windows, workspaces, outputs, layers, keyboard layouts, etc.
* enum wrappers for actions and event types

Because this is Python-only and pinned, I would not over-engineer runtime version adapters. I would instead generate or hand-maintain a `protocol/vX_Y.py` module matching the chosen crate version.

Suggested package:

```text
nirip/protocol/
    __init__.py
    v26_04.py
```

Important: this layer should be almost entirely dumb serialization and validation.

## 4.2 Transport layer

Purpose: talk to the niri socket.

Responsibilities:

* connect to request socket
* send request, read response
* connect to event stream socket
* expose sync and internal async mechanisms
* timeouts
* structured transport errors
* connection lifecycle

Suggested package:

```text
nirip/transport.py
```

Public abstractions:

* `NiriRequestClient`
* `NiriEventStream`
* `NiripConnectionError`
* `NiripTimeoutError`
* `NiripProtocolError`

Even if the public library stays sync-first, I would likely implement the internals with `asyncio` and provide blocking wrappers.

## 4.3 State store

This is the heart of the library.

Purpose: maintain a canonical local mirror of live niri state by applying event-stream updates.

niri’s official crate has an `EventStreamState` abstraction plus smaller state parts like `WindowsState` and `WorkspacesState`; Nirip should mirror that design in Python even if it does not reuse the Rust code directly.

Suggested package:

```text
nirip/state/
    __init__.py
    store.py
    reducers.py
    selectors.py
    snapshot.py
```

### State model

I would maintain one top-level Pydantic model:

```python
from pydantic import BaseModel, Field

class WindowState(BaseModel):
    id: int
    title: str | None = None
    app_id: str | None = None
    workspace_id: int | None = None
    output: str | None = None
    is_focused: bool = False
    is_floating: bool = False
    is_urgent: bool = False
    focus_timestamp: int | None = None

class WorkspaceState(BaseModel):
    id: int
    idx: int | None = None
    name: str | None = None
    output: str | None = None
    is_active: bool = False
    active_window_id: int | None = None

class OutputState(BaseModel):
    name: str
    make: str | None = None
    model: str | None = None
    is_focused: bool = False

class NiripState(BaseModel):
    windows: dict[int, WindowState] = Field(default_factory=dict)
    workspaces: dict[int, WorkspaceState] = Field(default_factory=dict)
    outputs: dict[str, OutputState] = Field(default_factory=dict)
    focused_window_id: int | None = None
    focused_output: str | None = None
    overview_open: bool | None = None
```

The actual fields should mirror the pinned crate version closely.

### Reducers

Reducers should be explicit functions:

* `apply_windows_changed`
* `apply_window_opened_or_changed`
* `apply_window_closed`
* `apply_window_focus_changed`
* `apply_workspaces_changed`
* `apply_workspace_activated`
* `apply_workspace_active_window_changed`
* `apply_window_layouts_changed`
* `apply_keyboard_layouts_changed`
* etc.

And a single dispatcher:

```python
def apply_event(state: NiripState, event: Event) -> NiripState:
    ...
```

### Selectors

Selectors are crucial for planner logic:

* `get_workspace_by_name`
* `get_windows_on_workspace`
* `get_focused_window`
* `find_windows(match_rule)`
* `get_active_workspace_for_output`
* `find_recent_unmatched_windows`

Selectors should be treated as the public read API over live state.

## 4.4 Matching engine

Purpose: determine whether a live window corresponds to a desired app entry.

Suggested package:

```text
nirip/matching.py
```

This engine should support layered matching:

1. exact window id, if already known
2. pid, if spawn tracking can provide it
3. app_id
4. title regex
5. workspace/output hints
6. temporal proximity to spawn
7. user-defined tags

Core model:

```python
from pydantic import BaseModel

class MatchRule(BaseModel):
    app_id: str | None = None
    title: str | None = None
    title_regex: str | None = None
    workspace_name: str | None = None
    output_name: str | None = None
    pid: int | None = None
    newest_first: bool = True
```

Matching result:

```python
class MatchResult(BaseModel):
    matched_window_ids: list[int]
    confidence: float
    reason: str
```

Important design choice: matching must be explainable. Users need to know *why* a window was chosen.

## 4.5 Session spec

Purpose: express desired sessions declaratively.

Suggested package:

```text
nirip/spec/
    __init__.py
    session.py
    schema.py
    loader.py
```

### Core spec model

```python
from pydantic import BaseModel, Field

class SpawnSpec(BaseModel):
    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False

class WindowTargetSpec(BaseModel):
    workspace: str | None = None
    output: str | None = None
    floating: bool | None = None
    focus: bool = False
    fullscreen: bool | None = None
    maximized: bool | None = None

class AppSpec(BaseModel):
    name: str
    spawn: SpawnSpec
    match: MatchRule
    target: WindowTargetSpec = Field(default_factory=WindowTargetSpec)
    requires: list[str] = Field(default_factory=list)
    startup_timeout_s: float = 20.0
    settle_timeout_s: float = 5.0
    optional: bool = False

class WorkspaceSpec(BaseModel):
    name: str
    output: str | None = None
    activate: bool = False
    apps: list[AppSpec] = Field(default_factory=list)

class SessionOptions(BaseModel):
    startup_mode: str = "reconcile"
    stop_on_error: bool = True
    focus_final_target: bool = True
    default_startup_timeout_s: float = 20.0

class SessionSpec(BaseModel):
    name: str
    options: SessionOptions = Field(default_factory=SessionOptions)
    workspaces: list[WorkspaceSpec]
```

### YAML concept

```yaml
name: dev-day
options:
  startup_mode: reconcile
  focus_final_target: true

workspaces:
  - name: code
    output: DP-1
    activate: true
    apps:
      - name: editor
        spawn:
          command: ["kitty", "--class", "dev-editor", "nvim"]
        match:
          app_id: dev-editor
        target:
          workspace: code
          focus: true

      - name: docs
        spawn:
          command: ["firefox", "--new-window", "https://docs.rs"]
        match:
          app_id: firefox
          title_regex: "docs.rs"
        target:
          workspace: code

  - name: comms
    apps:
      - name: slack
        spawn:
          command: ["slack"]
        match:
          app_id: slack
        target:
          workspace: comms
```

## 4.6 Planning layer

Purpose: convert desired session spec plus observed live state into a sequence of safe steps.

Suggested package:

```text
nirip/planner.py
nirip/plan_models.py
```

This is where Nirip becomes more than a wrapper.

Plan inputs:

* `SessionSpec`
* `NiripState`
* current runtime registry of prior spawn attempts
* possibly prior apply result

Plan outputs:

```python
class PlanStep(BaseModel):
    id: str
    kind: str
    description: str
    preconditions: list[str] = []
    postconditions: list[str] = []
    metadata: dict[str, str | int | float | bool] = {}

class Plan(BaseModel):
    session_name: str
    steps: list[PlanStep]
```

Typical step kinds:

* ensure workspace exists
* activate workspace
* spawn app
* wait for window match
* move window to workspace
* move window to output
* set floating/fullscreen/maximized
* focus window
* verify workspace settled

Planner rules should be deterministic and conservative.

## 4.7 Executor / reconciler

Purpose: run the plan against live state, observe results, retry where valid, and stop on unrecoverable divergence.

Suggested package:

```text
nirip/executor.py
```

Execution is a state machine.

For each step:

1. verify preconditions from state
2. issue request if needed
3. read events until:

   * success predicate becomes true
   * timeout
   * failure predicate
4. record structured outcome
5. continue or stop

Key point: success should be determined by **state**, not by “IPC request returned ok.”

### Example

For `spawn_app`:

* send spawn request
* record local timestamp and maybe child pid if locally spawned
* wait for a new window matching `AppSpec.match`
* bind that window id to the app instance
* only then consider the step complete

### Reconcile mode

Reconcile mode should avoid respawning apps that already match the desired state.

That means:

* if a matching window already exists in the right workspace, skip spawn
* if matching window exists but is misplaced, move it
* if multiple matches exist, surface ambiguity

This is the most tmuxp-like behavior.

# 5. Runtime registry

Nirip needs an ephemeral runtime registry during apply.

Suggested model:

```python
class AppRuntimeState(BaseModel):
    app_name: str
    spawned: bool = False
    matched_window_id: int | None = None
    started_at_monotonic: float | None = None
    completed: bool = False
    error: str | None = None

class ApplyRuntime(BaseModel):
    apps: dict[str, AppRuntimeState] = Field(default_factory=dict)
```

This registry is not the compositor state. It is Nirip’s internal bookkeeping.

# 6. Public API concept

I would make the public API very small.

```python
class NiripClient:
    def inspect(self) -> NiripState: ...
    def diff(self, spec: SessionSpec) -> "SessionDiff": ...
    def plan(self, spec: SessionSpec) -> "Plan": ...
    def apply(self, spec: SessionSpec) -> "ApplyResult": ...
    def capture(self) -> "CapturedSession": ...
```

And a live controller:

```python
class LiveNiri:
    def current_state(self) -> NiripState: ...
    def watch(self): ...
    def request(self, request: Request) -> Response: ...
```

# 7. CLI concept

## `nirip inspect`

Print current state in a human-readable way:

* outputs
* active workspaces
* windows grouped by workspace
* key identifiers useful for matching

## `nirip capture`

Create a starter YAML spec from the current session.

This should not aim for perfect replay. It should generate a useful scaffold:

* workspace names
* app_ids
* titles
* likely match rules
* current placement

## `nirip diff`

Show:

* which apps already match
* which would be spawned
* which windows would be moved
* which ambiguities exist

## `nirip apply`

Run the plan and stream progress.

## `nirip doctor`

Check:

* can connect to niri
* event stream works
* request stream works
* spec validity
* likely match ambiguities
* unsupported features in current spec

## `nirip watch`

Continuously print state/event summaries for debugging specs.

# 8. What “capture” should mean

This is important.

A tmuxp-style user will want “save my current setup.” Nirip can support that, but it should be explicit that capture produces a **starting template**, not a guaranteed exact replay artifact.

Captured spec should include:

* session name
* workspace names
* output hints
* per-window app_id
* per-window title and title regex suggestion
* placement target
* comments or metadata for manual cleanup

Potential capture output model:

```python
class CapturedAppSpec(BaseModel):
    inferred_name: str
    app_id: str | None = None
    title: str | None = None
    title_regex: str | None = None
    workspace: str | None = None
    output: str | None = None
```

# 9. Error model

Nirip should have a very explicit error taxonomy.

```python
class NiripError(Exception): ...
class NiripTransportError(NiripError): ...
class NiripProtocolError(NiripError): ...
class NiripMatchError(NiripError): ...
class NiripAmbiguousMatchError(NiripMatchError): ...
class NiripTimeoutError(NiripError): ...
class NiripPlanningError(NiripError): ...
class NiripExecutionError(NiripError): ...
```

Every failed apply should produce an `ApplyResult`, not just raise blindly.

```python
class StepResult(BaseModel):
    step_id: str
    success: bool
    error: str | None = None
    observed_window_ids: list[int] = Field(default_factory=list)

class ApplyResult(BaseModel):
    session_name: str
    success: bool
    steps: list[StepResult]
    final_state: NiripState | None = None
```

# 10. Matching philosophy

Matching is where most of the real-world pain will be.

Nirip should strongly prefer **stable identifiers**:

* `app_id`
* explicit window class parameters when the app supports them
* possibly workspace-specific titles
* specific browser profiles or app launch arguments

Nirip docs should actively teach users to launch apps in match-friendly ways.

For example:

* terminal windows with custom class/app id
* browser profiles
* editor instances with explicit titles if possible

This is a product decision, not just an implementation detail.

# 11. Scope and non-goals

## In scope

* workspace-oriented session restoration
* event-driven spawn/match/place/focus
* diff/apply/capture
* idempotent reconcile
* human-authored YAML
* Python library and CLI

## Out of scope for v1

* exact tree/column geometry replay unless the IPC supports it cleanly
* magic app-specific integrations
* general desktop automation beyond niri session management
* broad multi-version compatibility
* non-niri compositors

# 12. Internal package layout

A clean initial layout:

```text
nirip/
  __init__.py
  client.py
  transport.py
  planner.py
  executor.py
  matching.py
  errors.py
  runtime.py

  protocol/
    __init__.py
    v26_04.py

  state/
    __init__.py
    store.py
    reducers.py
    selectors.py
    snapshot.py

  spec/
    __init__.py
    session.py
    loader.py

  cli/
    __init__.py
    main.py
    apply.py
    diff.py
    capture.py
    inspect.py
    doctor.py
    watch.py

  testing/
    fixtures.py
    fake_niri.py
```

# 13. Testing strategy

This should be strong from day one.

## Unit tests

* protocol parsing
* each reducer/event handler
* selectors
* matcher behavior
* planner output

## Replay tests

Store recorded event streams and verify:

* final state
* plan generation
* apply convergence

## Fake transport tests

A fake niri transport that returns controlled responses and event sequences.

## Spec golden tests

Input YAML, expected plan, expected diff, expected captured output.

The `state`-style architecture makes replay tests especially natural because the event stream is the real source of truth.

# 14. Suggested implementation phases

## Phase 1: foundation

* protocol models for pinned crate version
* transport
* state store
* selectors
* `inspect` and `watch`

Deliverable: reliable live state mirror.

## Phase 2: session spec and diff

* Pydantic session models
* YAML loader
* matching engine
* diff planner
* `doctor`

Deliverable: validate and preview intended actions.

## Phase 3: apply/reconcile

* executor
* runtime registry
* timeout/retry logic
* `apply`

Deliverable: restore sessions.

## Phase 4: capture

* current state to starter YAML
* inferred match rules
* comments/metadata

Deliverable: bootstrap specs from real setups.

## Phase 5: polish

* richer diagnostics
* better ambiguity handling
* docs and examples
* fixtures from real-world workflows

# 15. Opinionated product choices I would make

I would choose these up front:

First, **sync public API, async internal engine**.

Second, **YAML as the canonical session format**.

Third, **all user-facing models as Pydantic**.

Fourth, **state-driven success checks only**.

Fifth, **reconcile mode as the default**, not “always respawn.”

Sixth, **capture as a scaffold generator**, not a promise of exact restoration.

# 16. A sample end-to-end flow

When the user runs:

```bash
nirip apply day.yaml
```

Nirip should:

1. parse and validate the spec
2. connect to niri request and event channels
3. build the initial `NiripState` from the event stream
4. compute a plan from desired vs current state
5. execute each step, waiting for confirming state changes
6. report final success or structured failure
7. optionally write an execution log

That flow matches niri’s event-stream model and avoids fragile sleep-based automation.

# 17. The key insight for Nirip

The key design insight is:

**Nirip is not an IPC wrapper. Nirip is a session reconciler whose source of truth is a live event-derived state store.**

Everything else follows from that:

* why reducers matter
* why matching matters
* why planner/executor separation matters
* why tmuxp is an inspiration, not a blueprint

# 18. Recommended v1 definition

I would define v1 as:

“A Python library and CLI that can inspect live niri state, read a declarative YAML session spec, compute a diff, and reconcile the current desktop so that named apps appear on their intended workspaces with verified matching and focus behavior.”

That is ambitious enough to be useful and narrow enough to ship.

If you want, I’ll turn this into a concrete repository skeleton next, including the initial package layout and the first Pydantic model files.
