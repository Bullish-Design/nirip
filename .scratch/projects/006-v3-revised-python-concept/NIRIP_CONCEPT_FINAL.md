# Nirip: Declarative Session Reconciler for Niri

A declarative workspace orchestrator for the Niri Wayland compositor, built on `niri-pypc` and `niri-state`.

---

## The one-paragraph version

**Nirip** is a Python library and CLI that restores, reconciles, and captures named desktop sessions on the Niri compositor. Users declare workspace layouts in YAML — which apps go where, how to match them, what to launch if they're missing. Nirip reads live compositor state through `niri-state`, resolves which windows match the declared intent, compiles a convergence plan, and executes it step-by-step with event-confirmed verification. It is a **session reconciler**, not a macro runner.

---

## 1. What Nirip is

Nirip is the declarative layer on top of a two-library stack:

```
┌──────────────────────────────────────────────────────┐
│                       nirip                          │
│  session specs, matching, resolution, planning,      │
│  execution, capture, facade, CLI                     │
├──────────────────────────────────────────────────────┤
│               niri-state (v0.2.0)                    │
│  live state mirror, snapshots, selectors,            │
│  health, subscriptions, waiters                      │
├──────────────────────────────────────────────────────┤
│               niri-pypc (v0.3.1)                     │
│  typed IPC protocol, transport, request/reply        │
│  client, event stream, generated action types        │
├──────────────────────────────────────────────────────┤
│                  Niri compositor                     │
│  Unix socket + event stream                          │
└──────────────────────────────────────────────────────┘
```

**niri-pypc** already handles: typed protocol models (Window, Workspace, Output, 110+ actions), async transport, request/reply client, persistent event stream, externally-tagged serde codec — all pinned to niri-ipc 25.11.

**niri-state** already handles: live state mirror via event reduction, immutable `Snapshot` with computed indexes, selectors for windows/workspaces/outputs/focus/keyboard/overview, health tracking (BOOTSTRAPPING -> LIVE -> STALE -> CLOSED), subscriber broadcast, reconciliation, invariant checking, auto-resync, async waiters (`wait_until`, `wait_for_selector`, `watch`).

**Nirip** owns only session semantics: spec format, spec validation, normalization, matching, resolution, plan compilation, step-by-step execution with verification, session capture, and CLI. Nirip does not reimplement protocol handling, state tracking, or event reduction.

---

## 2. Design principles

### Declarative first
Users write desired state in YAML. Nirip computes the steps. Users never script IPC sequences.

### Event-driven, not sleep-driven
No `sleep(2)` and hope. Nirip uses `niri-state`'s subscription system and waiters to observe actual state changes before proceeding.

### Reconciliation over macros
Default mode is reconcile: if a matching window already exists in the right place, skip it. Only spawn/move what's actually missing or misplaced. Every `apply` is idempotent.

### Leverage the stack
Nirip consumes `Snapshot` objects from `niri-state` and dispatches `Action` requests through `niri-pypc`. The boundary is clean: nirip owns session semantics, the libraries own compositor semantics.

### Observable execution
Every action produces a structured record. Users can `diff` before `apply`, watch progress during execution, and inspect results after. Matching decisions are always explainable.

### Aggressive validation
Spec problems are caught at load time, not at execution time. Empty match rules, weak-only matchers, and inter-app match conflicts are surfaced before anything runs.

### Async-first, sync facade
The internal engine is async (matching the async dependencies). A thin sync wrapper provides convenience for CLI and simple scripting.

---

## 3. Internal pipeline

Nirip uses a **three-stage internal pipeline** with explicit intermediate representations at each stage. This design makes `diff` a first-class view of the Resolution (not a reformatted Plan), makes Resolution independently testable without plan compilation, and catches spec problems during normalization before matching begins.

```
                         ┌─────────────┐
                         │  YAML File  │
                         └──────┬──────┘
                                │ parse + validate
                                ▼
                         ┌─────────────┐
                         │ SessionSpec │
                         └──────┬──────┘
                                │ apply defaults, flatten
                                │ workspace refs, validate
                                │ inter-app conflicts
                                ▼
                    ┌───────────────────────┐
                    │  NormalizedSession    │
                    │  (spec after defaults,│
                    │   inheritance, and    │
                    │   reference resolution│
                    └───────────┬───────────┘
                                │ match against Snapshot
                                ▼
                    ┌───────────────────────┐
                    │     Resolution        │
                    │  (what matched, what  │
                    │   is missing, what    │
                    │   drifted, what is    │
                    │   ambiguous)          │
                    └───────────┬───────────┘
                           ╱          ╲
                          ╱            ╲
                         ▼              ▼
               ┌──────────────┐  ┌────────────┐
               │ SessionDiff  │  │   Plan     │
               │ (display)    │  │ (ordered   │
               │              │  │  steps)    │
               └──────────────┘  └─────┬──────┘
                                       │ execute with
                                       │ verification
                                       ▼
                                ┌─────────────┐
                                │ ApplyResult │
                                └─────────────┘
```

### Stage 1: Normalization
The spec after defaults, inheritance, and reference resolution. Catches spec problems (missing defaults, conflicting references, validation failures) before matching begins.

### Stage 2: Resolution
Which live entities match which declared apps, which are missing, which have drifted from desired state, and which are ambiguous. This is the standalone intermediate representation that powers both `diff` (display the Resolution) and `plan` (compile the Resolution into steps).

### Stage 3: Plan compilation
The Resolution is compiled into an ordered list of imperative steps with dependencies. The plan is a pure data structure — displayable, serializable, diffable.

### Execution
The executor takes a compiled Plan and runs it against live state. Verification predicates are attached at execution time, not stored in the plan model.

---

## 4. Session spec format

The session spec is the user-authored YAML file describing a desired desktop layout. It is the primary user interface of nirip.

### 4.1 Core models

```python
from pydantic import BaseModel, Field, model_validator


class MatchRule(BaseModel):
    """How to find an existing window that fills this role.

    Multiple flat fields are implicitly ANDed.
    A MatchRule with zero criteria is rejected at validation time.
    """
    app_id: str | None = None             # exact app_id match
    app_id_regex: str | None = None       # regex app_id match
    title: str | None = None              # exact title match
    title_regex: str | None = None        # regex title match
    pid: int | None = None                # exact PID match (rare, mostly internal)
    any: list["MatchRule"] | None = None  # OR: any sub-rule matches
    not_rule: "MatchRule" | None = None   # negate a sub-rule

    @model_validator(mode="after")
    def validate_not_empty(self) -> "MatchRule":
        """Reject match rules with zero matching criteria."""
        has_criteria = any([
            self.app_id, self.app_id_regex,
            self.title, self.title_regex,
            self.pid is not None,
            self.any, self.not_rule,
        ])
        if not has_criteria:
            raise ValueError(
                "MatchRule must have at least one matching criterion. "
                "A match rule with no criteria would match every window."
            )
        return self


class SpawnSpec(BaseModel):
    """How to launch a window if no match is found."""
    command: list[str] | str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False                   # if True, run via sh -c


class PlacementSpec(BaseModel):
    """Where and how a window should be placed."""
    floating: bool = False
    fullscreen: bool = False
    maximized: bool = False
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
    focus: bool = False                            # focus this workspace after apply
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

### 4.2 YAML example

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
          column_width: 0.6

      - name: terminal
        match:
          app_id: dev-term
        spawn:
          command: ["kitty", "--class", "dev-term"]
          cwd: ~/projects/current
        depends_on: [editor]

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

### 4.3 Format notes

- YAML is the canonical format. TOML support may be added later but YAML is the default.
- `match` fields are composable: flat fields are implicitly ANDed, `any` provides OR, `not_rule` provides negation.
- `spawn` is optional — an app with only `match` will be found if running but never launched.
- `placement.column_width` and `placement.window_height` accept proportions (0.0-1.0) or pixel strings ("px:800").
- `depends_on` allows ordering within a workspace: "terminal" can depend on "editor" to ensure editor spawns first.
- Apps are nested under workspaces in YAML because users think "workspace X should have apps A, B, C." Internally, the normalizer flattens apps into a list with workspace references if the engine prefers it.
- Output affinity is a workspace-level concern only. There is no per-app output in v1. Workspaces declare their output; apps inherit.

---

## 5. Spec validation

Spec validation is **aggressive and safety-oriented**. Problems are caught at load time, not at match time or execution time.

### 5.1 Validation rules

**MatchRule validation:**
- A `MatchRule` with zero matching criteria is rejected at parse time (model validator).
- A `MatchRule` with only `title_regex` and no `app_id` or `app_id_regex` produces a warning unless the app is marked `optional: true`. Title-only matching is fragile.
- Regex patterns are compiled at validation time; invalid regex is a parse error.

**Cross-app conflict detection:**
- The validator checks for inter-app match conflicts within a session: two apps with identical `app_id` and no differentiating criteria will produce an error.
- Apps on different workspaces with the same match criteria produce a warning (the matching engine will resolve this, but the user should be aware).

**Structural validation:**
- `depends_on` references must resolve to app names within the same workspace.
- Workspace names must be unique within a session.
- App names must be unique within a workspace.
- `placement.floating` and `placement.fullscreen` are mutually exclusive.

**SpawnSpec validation:**
- `command` must be non-empty.
- `cwd` paths are validated for basic syntax (tilde expansion, absolute path).

### 5.2 Validation output

```python
class ValidationResult(BaseModel):
    """Result of spec validation."""
    valid: bool
    errors: list[str]       # fatal: spec cannot be used
    warnings: list[str]     # non-fatal: spec is valid but risky
```

Validation runs automatically on YAML load. Errors prevent any further processing. Warnings are displayed but don't block execution.

---

## 6. Architecture

### 6.1 Package layout

```
src/nirip/
  __init__.py              # public API re-exports
  config.py                # NiripConfig
  errors.py                # error hierarchy

  facade/
    __init__.py
    async_nirip.py         # AsyncNirip: primary async API
    sync_nirip.py          # SyncNirip: thin sync wrappers

  spec/
    __init__.py
    models.py              # SessionSpec, WorkspaceSpec, AppSpec, MatchRule, etc.
    loader.py              # YAML parsing + validation
    validators.py          # aggressive safety validation
    defaults.py            # default option merging

  resolve/
    __init__.py
    normalizer.py          # spec -> NormalizedSession (defaults applied, refs resolved)
    matcher.py             # MatchRule evaluation against Window
    resolver.py            # NormalizedSession + Snapshot -> Resolution
    models.py              # NormalizedSession, MatchDecision, Resolution, AppResolution

  planning/
    __init__.py
    compiler.py            # Resolution -> Plan (ordered steps)
    ordering.py            # topological sort, dependency handling
    models.py              # Plan, PlanStep, StepKind, SessionDiff

  execution/
    __init__.py
    executor.py            # Plan runner with verification
    actions.py             # PlanStep -> niri-pypc Action translation
    predicates.py          # Snapshot predicates for step verification
    runtime.py             # SessionRuntime, AppRuntimeState
    models.py              # StepResult, StepOutcome, ApplyResult

  capture/
    __init__.py
    capturer.py            # Snapshot -> scaffold SessionSpec
    inference.py           # infer MatchRules from live Windows

  cli/
    __init__.py
    main.py                # CLI entrypoint
    commands.py            # apply, diff, capture, inspect, doctor, watch
```

### 6.2 Package design rationale

**`resolve/` is standalone** — matching is independently testable without plan compilation. The Resolution model is a genuinely different concern from the Plan. In a two-stage design, diff is an awkward afterthought (generate a full plan, then strip it down for display). In the three-stage design, diff is just "show the Resolution," which is more natural and more informative.

**`facade/` separates async and sync** — the async API is the real implementation. The sync facade wraps it with `asyncio.run()` for CLI and scripting convenience. This makes embedding nirip in async applications natural.

**No `observe/` wrapper** — `niri-state`'s API is already clean. Wrapping it adds indirection without value. Import selectors and waiters directly.

**No centralized `model/` package** — each subsystem owns its own models. This keeps imports localized and avoids a grab-bag package.

### 6.3 Dependency flow

```
cli/ ─────────────► facade/
                       │
           ┌───────────┼───────────────┐
           ▼           ▼               ▼
       spec/       planning/       capture/
           │           │               │
           └─────┬─────┘               │
                 ▼                     │
            resolve/ ◄─────────────────┘
                 │
                 ▼
           execution/
                 │
        ┌────────┴─────────┐
        ▼                  ▼
   niri-state          niri-pypc
   (snapshots,         (actions,
    selectors,          requests,
    waiters)            client)
```

---

## 7. Normalization layer

The normalizer transforms a raw `SessionSpec` into a `NormalizedSession` — the spec after defaults, inheritance, and reference resolution. This stage catches structural problems before matching begins.

### 7.1 Normalization models

```python
class NormalizedApp(BaseModel):
    """An app after default merging and reference resolution."""
    name: str
    workspace_name: str               # denormalized from parent workspace
    match: MatchRule
    spawn: SpawnSpec | None
    placement: PlacementSpec
    optional: bool
    startup_timeout_s: float
    depends_on: list[str]


class NormalizedWorkspace(BaseModel):
    """A workspace after default merging."""
    name: str
    output: str | None
    focus: bool
    app_names: list[str]              # ordered list of app names


class NormalizedSession(BaseModel):
    """The session spec after all normalization passes."""
    name: str
    description: str
    options: SessionOptions
    workspaces: list[NormalizedWorkspace]
    apps: list[NormalizedApp]         # flattened from all workspaces
    app_index: dict[str, NormalizedApp]  # workspace_name/app_name -> app
```

### 7.2 Normalization passes

1. **Default merging** — apply `SessionOptions.default_startup_timeout_s` to any app that doesn't override it.
2. **Flattening** — extract apps from nested workspace structure into a flat list with explicit `workspace_name` references.
3. **Reference validation** — verify all `depends_on` targets exist within the same workspace.
4. **Index construction** — build lookup indexes for fast access during matching.

---

## 8. Matching engine

The matching engine determines whether a live window corresponds to a declared app role. This is the most important piece of nirip's logic — correct matching makes reconciliation work; bad matching causes chaos.

### 8.1 Match evaluation

```python
class MatchDecision(BaseModel):
    """Result of matching an app against all live windows."""
    app_name: str
    workspace_name: str
    best: int | None = None            # best-match window ID, if any
    candidates: list[MatchCandidate]   # all evaluated candidates
    confidence: float = 0.0            # confidence of best match
    rationale: list[str]               # human-readable explanation

    @computed_field
    @property
    def is_ambiguous(self) -> bool:
        """True if multiple candidates have similar confidence."""
        high_confidence = [c for c in self.candidates if c.confidence > 0.6]
        return len(high_confidence) > 1

    @computed_field
    @property
    def is_matched(self) -> bool:
        """True if a best match was selected."""
        return self.best is not None


class MatchCandidate(BaseModel):
    """A single window evaluated against a MatchRule."""
    window_id: int
    confidence: float                  # 0.0-1.0
    reasons: list[str]                 # what matched/failed
```

### 8.2 Match evaluation rules

Given a `MatchRule` and a `Window` (from `niri-state` snapshot):

1. `app_id` — exact string match against `window.app_id`
2. `app_id_regex` — regex match against `window.app_id`
3. `title` — exact string match against `window.title`
4. `title_regex` — regex match against `window.title`
5. `pid` — exact match against `window.pid`
6. Multiple flat fields — all must match (implicit AND)
7. `any` — at least one sub-rule must match (OR)
8. `not_rule` — the sub-rule must NOT match (negation)

### 8.3 Confidence scoring

Confidence reflects how specific and reliable a match is:

| Criterion | Confidence |
|---|---|
| `pid` exact match | 1.0 |
| `app_id` exact match | 1.0 |
| `app_id_regex` match | 0.9 |
| `title` exact match | 0.8 |
| `title_regex` match | 0.7 |
| AND composition | minimum of sub-scores |
| OR composition | maximum of sub-scores |
| Multiple criteria satisfied | combined (more specific = more certain) |

### 8.4 Scoring priority order

When the matching engine evaluates candidates, it prefers matches in this order:

1. Previously bound window ID (from prior nirip apply)
2. Verified PID linkage from a spawn launched by nirip
3. Exact `app_id`
4. Exact title
5. Title regex
6. Workspace/output hint agreement
7. Recency relative to spawn timestamp
8. Tie-break by window ID (deterministic)

### 8.5 Match philosophy

The matching engine is **deterministic, explainable, and biases toward false negatives over false positives**. It is better to report "no match found" than to silently pick the wrong window. The output is never just "matched window 42" — it is always a full `MatchDecision` with candidates, confidence, and rationale, so both CLI output and debugging are explainable.

### 8.6 Match context

The matching engine receives a `Snapshot` from `niri-state` and uses its selectors:

```python
from niri_state.api.selectors import windows, workspaces

# Get all windows to evaluate
all_windows = windows.list_windows(snapshot)

# Optionally scope to a workspace
ws = workspaces.get_workspace_by_name(snapshot, "code")
ws_windows = windows.list_windows_on_workspace(snapshot, ws.id)
```

---

## 9. Resolution layer

The resolver takes a `NormalizedSession` and a `Snapshot` and produces a `Resolution` — the complete picture of what matched, what's missing, what drifted, and what's ambiguous. This is the key intermediate representation that powers both `diff` and `plan`.

### 9.1 Resolution models

```python
class AppResolution(BaseModel):
    """Resolution status for a single declared app."""
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    match_decision: MatchDecision
    drift: list[DriftItem]             # what differs from desired state
    action_required: bool

    @computed_field
    @property
    def needs_spawn(self) -> bool:
        return self.status == ResolutionStatus.MISSING and self.action_required

    @computed_field
    @property
    def needs_move(self) -> bool:
        return any(d.kind == DriftKind.WRONG_WORKSPACE for d in self.drift)


class ResolutionStatus(StrEnum):
    MATCHED = "matched"           # window found, in correct state
    DRIFTED = "drifted"           # window found, but placement/workspace wrong
    MISSING = "missing"           # no matching window found
    AMBIGUOUS = "ambiguous"       # multiple high-confidence matches
    OPTIONAL_MISSING = "optional_missing"  # optional app, not found, acceptable


class DriftKind(StrEnum):
    WRONG_WORKSPACE = "wrong_workspace"
    WRONG_FLOATING = "wrong_floating"
    WRONG_FULLSCREEN = "wrong_fullscreen"
    WRONG_MAXIMIZED = "wrong_maximized"
    WRONG_COLUMN_WIDTH = "wrong_column_width"
    WRONG_WINDOW_HEIGHT = "wrong_window_height"


class DriftItem(BaseModel):
    """A single deviation from desired state."""
    kind: DriftKind
    current: str                       # human-readable current value
    desired: str                       # human-readable desired value


class WorkspaceResolution(BaseModel):
    """Resolution status for a single declared workspace."""
    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    app_resolutions: list[AppResolution]


class Resolution(BaseModel):
    """Complete resolution of a session spec against live state."""
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]
    unmatched_apps: list[AppResolution]     # apps with no match
    ambiguous_apps: list[AppResolution]     # apps with ambiguous matches
    warnings: list[str]

    @computed_field
    @property
    def has_drift(self) -> bool:
        """True if any app or workspace needs action."""
        return any(
            ar.action_required
            for wr in self.workspace_resolutions
            for ar in wr.app_resolutions
        ) or any(
            not wr.exists or not wr.output_correct
            for wr in self.workspace_resolutions
        )

    @computed_field
    @property
    def fully_converged(self) -> bool:
        """True if live state matches desired state exactly."""
        return not self.has_drift and not self.unmatched_apps and not self.ambiguous_apps
```

### 9.2 Resolution algorithm

For each workspace in the normalized session:

1. **Check workspace existence** — does a workspace with this name exist in the snapshot?
2. **Check output placement** — if an output is declared, is the workspace on the correct output?
3. **Match apps** — for each declared app, run the matching engine against all live windows. Record the `MatchDecision`.
4. **Detect drift** — for matched windows, compare current placement (workspace, floating, fullscreen, etc.) against desired placement. Record `DriftItem` entries.
5. **Classify status** — assign each app a `ResolutionStatus` based on match results and drift.
6. **Collect ambiguities** — apps with multiple high-confidence matches are flagged.

The Resolution is a pure computation over spec + snapshot. It has no side effects.

---

## 10. Planning layer

The planner compiles a `Resolution` into a `Plan` — an ordered list of steps to converge the desktop toward the desired state.

### 10.1 Plan models

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
    SET_MAXIMIZED = "set_maximized"
    SET_COLUMN_WIDTH = "set_column_width"
    SET_WINDOW_HEIGHT = "set_window_height"
    FOCUS_WINDOW = "focus_window"
    FOCUS_WORKSPACE = "focus_workspace"


class PlanStep(BaseModel):
    """A single imperative step in the execution plan.

    PlanStep is a data class — serializable, displayable, diffable.
    The executor attaches verification predicates at execution time.
    """
    id: str                              # unique step ID
    kind: StepKind
    app_name: str | None = None          # which AppSpec this serves
    workspace_name: str | None = None    # target workspace
    window_id: int | None = None         # known window ID (for move/adjust steps)
    description: str                     # human-readable summary
    depends_on: list[str] = Field(default_factory=list)  # step IDs
    metadata: dict[str, Any] = Field(default_factory=dict)  # step-kind-specific data


class Plan(BaseModel):
    """A compiled execution plan."""
    session_name: str
    steps: list[PlanStep]
    resolution: Resolution               # the resolution this plan was compiled from
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def requires_spawn(self) -> bool:
        """True if any step spawns a new window."""
        return any(s.kind == StepKind.SPAWN_WINDOW for s in self.steps)

    @computed_field
    @property
    def step_count(self) -> int:
        return len(self.steps)

    @computed_field
    @property
    def is_empty(self) -> bool:
        """True if no steps are needed (fully converged)."""
        return len(self.steps) == 0
```

### 10.2 Plan compilation algorithm

The compiler transforms a `Resolution` into a `Plan`:

1. **Workspace steps** — for each workspace that doesn't exist, emit `ENSURE_WORKSPACE`. For each workspace on the wrong output, emit `MOVE_WORKSPACE_TO_OUTPUT`.

2. **App steps** — for each app resolution:
   - **MATCHED, no drift**: skip (no steps needed).
   - **DRIFTED**: emit steps for each drift item (move to workspace, set floating/tiling, set fullscreen, set column width, etc.).
   - **MISSING with spawn**: emit `SPAWN_WINDOW` followed by `WAIT_FOR_WINDOW`, then placement steps.
   - **MISSING without spawn, not optional**: emit a warning.
   - **AMBIGUOUS**: emit a warning (do not guess).
   - **OPTIONAL_MISSING**: skip.

3. **Focus steps** — emit `FOCUS_WINDOW` for the last app with `placement.focus: true`. Emit `FOCUS_WORKSPACE` for workspaces with `focus: true`. Focus steps always come last.

4. **Dependency ordering** — respect `depends_on` within each workspace. Topological sort steps so dependencies execute first. Workspace steps precede app steps within each workspace.

### 10.3 SessionDiff

`SessionDiff` is a human-readable view derived from the `Resolution`. It is what `nirip diff` displays.

```python
class SessionDiff(BaseModel):
    """Human-readable diff between desired and current state."""
    session_name: str
    already_matched: list[str]       # "editor: matched window 42 (app_id=dev-editor)"
    will_spawn: list[str]            # "terminal: will spawn ['kitty', '--class', 'dev-term']"
    will_move: list[str]             # "docs: window 87 -> workspace 'code'"
    will_adjust: list[str]           # "editor: set column width to 0.6"
    workspace_changes: list[str]     # "code: create workspace on DP-1"
    warnings: list[str]              # "discord: no match found, marked optional"
    errors: list[str]                # "slack: no match and no spawn command"

    @computed_field
    @property
    def has_drift(self) -> bool:
        """True if any changes would be made."""
        return bool(
            self.will_spawn or self.will_move or
            self.will_adjust or self.workspace_changes
        )

    @computed_field
    @property
    def has_errors(self) -> bool:
        return bool(self.errors)
```

---

## 11. Execution engine

The executor runs plan steps against live compositor state, using `niri-state` for verification and `niri-pypc` for actions.

### 11.1 Hybrid step model

The plan uses `StepKind` enums for serialization and display. The executor attaches verification predicates at execution time. This gives us the best of both approaches:

- **Plan side**: steps are data (enum + metadata) — serializable, displayable, diffable.
- **Executor side**: each step kind maps to a verification predicate (a typed callable over `Snapshot`) — self-contained, testable, with failure predicates that prevent waiting the full timeout when something goes clearly wrong.

```python
@dataclass
class StepExecution:
    """Runtime binding of a PlanStep to its verification logic."""
    step: PlanStep
    action: ActionRequest | None                # niri-pypc action to send
    verify: Callable[[Snapshot], bool]           # predicate: step is complete
    fail_check: Callable[[Snapshot], bool] | None = None  # predicate: step clearly failed
    timeout_s: float = 20.0
```

### 11.2 Execution flow

```python
class StepOutcome(StrEnum):
    COMPLETED = "completed"    # executed and verified
    SKIPPED = "skipped"        # already satisfied
    FAILED = "failed"          # action failed or verification failed
    TIMED_OUT = "timed_out"    # verification not received in time


class StepResult(BaseModel):
    step: PlanStep
    outcome: StepOutcome
    message: str
    window_id: int | None = None       # resolved window ID, if applicable
    duration_s: float = 0.0


class ApplyResult(BaseModel):
    """Result of applying a session spec."""
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

### 11.3 Step execution pattern

For each step, the executor follows the same pattern:

1. **Check preconditions** — read current `snapshot` from `niri-state`, verify the step's dependencies are satisfied.
2. **Check if already done** — evaluate the verification predicate against current state. If already satisfied, mark `SKIPPED`.
3. **Execute action** — translate the step to a `niri-pypc` action and send it via `NiriClient.request()`.
4. **Wait for verification** — use `niri-state`'s `wait_until` to observe the expected state change. Check the failure predicate on each snapshot to detect early failure. Timeout after `timeout_s`.
5. **Record result** — capture outcome, timing, and any resolved window IDs.

### 11.4 Action translation

Each `StepKind` maps to specific `niri-pypc` actions:

| StepKind | niri-pypc Action |
|---|---|
| `ENSURE_WORKSPACE` | `FocusWorkspaceAction(reference=Name(name))` + verify |
| `MOVE_WORKSPACE_TO_OUTPUT` | `MoveWorkspaceToMonitorAction(...)` |
| `SPAWN_WINDOW` | `SpawnAction(command=...)` |
| `WAIT_FOR_WINDOW` | No action — wait on `niri-state` for matching window |
| `MOVE_WINDOW_TO_WORKSPACE` | `MoveWindowToWorkspaceAction(window_id=..., reference=Name(...))` |
| `SET_FLOATING` | `MoveWindowToFloatingAction(id=...)` |
| `SET_TILING` | `MoveWindowToTilingAction(id=...)` |
| `SET_FULLSCREEN` | `FullscreenWindowAction(id=...)` |
| `SET_MAXIMIZED` | `MaximizeWindowAction(id=...)` |
| `SET_COLUMN_WIDTH` | `SetColumnWidthAction(id=..., change=SetProportion(...))` |
| `SET_WINDOW_HEIGHT` | `SetWindowHeightAction(id=..., change=SetProportion(...))` |
| `FOCUS_WINDOW` | `FocusWindowAction(id=...)` |
| `FOCUS_WORKSPACE` | `FocusWorkspaceAction(reference=Name(...))` |

### 11.5 Action helper layer

The generated action types in `niri-pypc` are verbose to construct (nested `Action(root=SpawnAction(...))` wrapped in `ActionRequest`). The `execution/actions.py` module provides a thin ergonomics layer:

```python
# execution/actions.py — thin helpers over niri-pypc generated types

def spawn_action(command: list[str] | str) -> ActionRequest:
    """Build a spawn action request."""
    ...

def focus_workspace_action(name: str) -> ActionRequest:
    """Build a focus-workspace-by-name action request."""
    ...

def move_window_to_workspace_action(window_id: int, workspace_name: str) -> ActionRequest:
    """Build a move-window-to-workspace action request."""
    ...

def move_workspace_to_output_action(workspace_name: str, output: str) -> ActionRequest:
    """Build a move-workspace-to-output action request."""
    ...
```

These helpers keep the executor readable while preserving the generated protocol boundary underneath. If practical, these should be contributed upstream to `niri-pypc`.

### 11.6 Integration with niri-state

The executor holds a reference to `NiriState` and uses its subscription system:

```python
from niri_state import NiriState
from niri_state.api.waiters import wait_until
from niri_state.api.selectors import windows, workspaces

async def execute_spawn_and_wait(
    state: NiriState,
    client: NiriClient,
    app: NormalizedApp,
    timeout: float,
) -> StepResult:
    # Send spawn action
    await client.request(spawn_action(app.spawn.command))

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

## 12. Managed state

Nirip tracks which windows it has placed during a session apply. This is needed for:
- Knowing what to clean up on re-apply
- Preferring previously-bound windows during matching (scoring priority #1)
- Supporting `move_unmatched` (moving non-session windows out of managed workspaces)

### 12.1 Runtime registry (ephemeral)

```python
class AppRuntimeState(BaseModel):
    """Ephemeral state for one app during a single apply."""
    app_name: str
    workspace_name: str
    matched_window_id: int | None = None
    spawned: bool = False
    spawn_pid: int | None = None
    completed: bool = False
    error: str | None = None


class SessionRuntime(BaseModel):
    """Ephemeral state during a single apply operation."""
    session_name: str
    apps: dict[str, AppRuntimeState] = Field(default_factory=dict)
    started_at: float | None = None
```

### 12.2 Persistent tracking (optional)

For multi-apply workflows, nirip persists a lightweight record of managed windows:

```python
class ManagedSession(BaseModel):
    """Persisted after apply for later re-apply or teardown."""
    session_name: str
    applied_at: str                        # ISO timestamp
    managed_windows: dict[str, int]        # app_name -> window_id
    managed_workspaces: list[str]          # workspace names
```

Stored as JSON in `$XDG_STATE_HOME/nirip/sessions/<name>.json`. This is optional — nirip works fine without it by re-matching from scratch. When present, the matching engine uses it to prefer previously-bound windows.

---

## 13. Capture

Capture reads the current compositor state and generates a starter YAML session spec. It is a **scaffold generator**, not a promise of exact restoration.

### 13.1 Capture logic

```python
async def capture(state: NiriState, name: str | None = None) -> CapturedSession:
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
                # spawn is left empty -- user fills in
            )
            apps.append(app)

        workspaces_spec.append(WorkspaceSpec(
            name=ws.name,
            output=ws.output,
            apps=apps,
        ))

    return CapturedSession(
        spec=SessionSpec(
            name=name or "captured",
            workspaces=workspaces_spec,
        ),
        notes=generate_capture_notes(workspaces_spec),
    )
```

### 13.2 CapturedSession model

```python
class CapturedSession(BaseModel):
    """Result of a capture operation."""
    spec: SessionSpec
    notes: list[str]                   # guidance for the user

    @computed_field
    @property
    def app_count(self) -> int:
        return sum(len(ws.apps) for ws in self.spec.workspaces)

    @computed_field
    @property
    def workspace_count(self) -> int:
        return len(self.spec.workspaces)
```

### 13.3 Match rule inference

For each captured window:
- Always include `app_id` if present (most reliable identifier).
- Include `title_regex` as a YAML comment suggestion if the title contains useful identifiers.
- Note when multiple windows share the same `app_id` (user needs to differentiate with title criteria).

### 13.4 Capture philosophy

Capture stays humble:
- Scaffold with `app_id`-based match rules, no spawn commands.
- Comments guiding manual refinement.
- The captured YAML is a starting template designed for human cleanup, not a replay artifact.

---

## 14. Public API

### 14.1 AsyncNirip (primary)

```python
class AsyncNirip:
    """Primary async API for nirip operations.

    Async-first — this is the real implementation.
    """

    @classmethod
    async def open(cls, config: NiripConfig | None = None) -> "AsyncNirip":
        """Connect to niri and initialize state."""
        ...

    async def inspect(self) -> LiveDesktop:
        """Return a session-aware view of current compositor state.

        LiveDesktop annotates the raw snapshot with information about
        which windows are managed by nirip sessions.
        """
        ...

    async def diff(self, spec: SessionSpec) -> SessionDiff:
        """Compute what would change without applying.

        Runs normalization and resolution, then formats the result
        for human display.
        """
        ...

    async def plan(self, spec: SessionSpec) -> Plan:
        """Compute the full execution plan.

        Runs normalization, resolution, and plan compilation.
        """
        ...

    async def apply(self, spec: SessionSpec) -> ApplyResult:
        """Apply a session spec: plan + execute + verify.

        Returns an ApplyResult with structured step outcomes.
        Does not raise for operational failures (ambiguity, timeout,
        app not appearing). Raises only for programmer misuse or
        dependency failures before apply can be evaluated.
        """
        ...

    async def capture(self, *, name: str | None = None) -> CapturedSession:
        """Generate a session spec scaffold from current state."""
        ...

    async def doctor(self, spec: SessionSpec | None = None) -> DoctorReport:
        """Check connection health, spec validity, match ambiguities.

        If a spec is provided, validates it and checks for match
        conflicts against live state.
        """
        ...

    async def close(self) -> None:
        """Shut down connections."""
        ...

    async def __aenter__(self) -> "AsyncNirip": ...
    async def __aexit__(self, *args: Any) -> None: ...
```

### 14.2 SyncNirip (convenience wrapper)

```python
class SyncNirip:
    """Thin sync wrapper over AsyncNirip for CLI and scripting."""

    def __init__(self, config: NiripConfig | None = None): ...

    def inspect(self) -> LiveDesktop: ...
    def diff(self, spec: SessionSpec) -> SessionDiff: ...
    def plan(self, spec: SessionSpec) -> Plan: ...
    def apply(self, spec: SessionSpec) -> ApplyResult: ...
    def capture(self, *, name: str | None = None) -> CapturedSession: ...
    def doctor(self, spec: SessionSpec | None = None) -> DoctorReport: ...
    def close(self) -> None: ...
```

Each method wraps the corresponding `AsyncNirip` method with `asyncio.run()`.

### 14.3 LiveDesktop

```python
class LiveDesktop(BaseModel):
    """Session-aware view of current compositor state.

    Enriches the raw niri-state Snapshot with nirip-specific
    annotations: which windows are managed, which sessions are active.
    """
    outputs: list[OutputInfo]
    workspaces: list[WorkspaceInfo]
    windows: list[WindowInfo]
    managed_sessions: list[str]        # names of active managed sessions
    focused_window_id: int | None
    focused_workspace_name: str | None
```

### 14.4 Convenience functions

For simple scripting:

```python
from nirip import load_session, apply_session

spec = load_session("dev-day.yaml")
result = apply_session(spec)
```

These are thin wrappers that create a `SyncNirip`, run the operation, and close.

---

## 15. Error hierarchy

```python
class NiripError(Exception):
    """Base for all nirip errors."""

class SpecError(NiripError):
    """Invalid session spec (parse error, validation failure)."""

class SpecValidationError(SpecError):
    """Spec validation failed (empty match rules, conflicts, etc.)."""

class MatchError(NiripError):
    """Window matching failure."""

class AmbiguousMatchError(MatchError):
    """Multiple windows match with similar confidence."""

class PlanningError(NiripError):
    """Plan generation failed (unresolvable conflicts)."""

class ExecutionError(NiripError):
    """Step execution failed."""

class StepTimeoutError(ExecutionError):
    """Window didn't appear within timeout."""

class CaptureError(NiripError):
    """Capture failed."""

class ConnectionError(NiripError):
    """Cannot connect to niri compositor."""
```

Nirip does not wrap `niri-pypc` or `niri-state` errors — those propagate directly. Nirip's errors cover only session-level semantics. Operational failures during apply (ambiguity, timeout, app not appearing) are represented as structured `StepResult` outcomes, not exceptions.

---

## 16. Configuration

```python
class NiripConfig(BaseModel, frozen=True):
    """Nirip-level configuration."""
    state_config: NiriStateConfig | None = None     # pass through to niri-state
    session_dir: Path = Path("~/.config/nirip/sessions")
    state_dir: Path = Path("~/.local/state/nirip")
    default_timeout_s: float = 20.0
    confirm_before_apply: bool = True
```

Nirip inherits all connection/transport config from `niri-state` -> `niri-pypc`. No duplication.

---

## 17. CLI

The CLI is nirip's primary user interface.

### 17.1 Commands

```
nirip apply <session.yaml>     Apply a session spec (reconcile by default)
nirip diff <session.yaml>      Show what would change without applying
nirip capture [-o file.yaml]   Generate a session spec from current state
nirip inspect                  Print current compositor state summary
nirip doctor [session.yaml]    Verify connection, spec validity, match sanity
nirip watch                    Stream state changes for debugging
nirip status                   Show managed sessions and their window states
```

### 17.2 `nirip apply` flow

1. Load and validate the session spec (aggressive validation).
2. Connect to niri via `AsyncNirip.open()`.
3. Wait for initial snapshot (bootstrapping -> live).
4. Normalize the spec.
5. Resolve against live state.
6. Compile plan from resolution.
7. Display plan summary, ask for confirmation (unless `--yes`).
8. Execute steps, streaming progress.
9. Report final result.
10. Optionally persist managed state.

### 17.3 `nirip diff` output

```
Session: dev-day

Workspaces:
  + code          create on DP-1

Already matched:
  = editor        window 42 (app_id=dev-editor) on code

Will spawn:
  + terminal      ['kitty', '--class', 'dev-term'] on code

Will move:
  > docs          window 87 -> workspace code

Will adjust:
  ~ editor        set column width to 0.6

Warnings:
  ? discord       no match found (optional, skipping)

Errors:
  ! slack         no match found and no spawn command
```

### 17.4 `nirip inspect` output

```
Outputs:
  DP-1 (2560x1440 @ 144Hz)  [focused]
  eDP-1 (1920x1080 @ 60Hz)

Workspaces:
  1: code     (DP-1)  [active]
    - kitty (dev-editor)  "~/projects - nvim"  [focused]
    - kitty (dev-term)    "~/projects - zsh"
    - firefox             "docs.rs - MDN Web Docs"
  2: comms    (DP-1)
    - Slack               "Slack | #general"
  3: media    (eDP-1)  [active]
    - spotify             "Spotify"
```

### 17.5 `nirip doctor` output

```
Connection:
  [OK] niri socket connected
  [OK] niri-state live (health: LIVE)
  [OK] niri-pypc protocol: niri-ipc 25.11

Spec validation (dev-day.yaml):
  [OK] 3 workspaces, 6 apps
  [OK] all match rules valid
  [WARN] docs: title_regex-only match, consider adding app_id

Match check:
  [OK] editor: unique match (window 42)
  [OK] terminal: unique match (window 43)
  [WARN] docs: 3 firefox windows, match may be ambiguous
  [OK] slack: unique match (window 78)
  [--] discord: not running (optional)
  [--] spotify: not running (optional)
```

---

## 18. DoctorReport model

```python
class DoctorCheck(BaseModel):
    """A single diagnostic check."""
    name: str
    status: str                    # "ok", "warn", "error", "skip"
    message: str


class DoctorReport(BaseModel):
    """Result of running nirip doctor."""
    connection_checks: list[DoctorCheck]
    spec_checks: list[DoctorCheck]
    match_checks: list[DoctorCheck]

    @computed_field
    @property
    def healthy(self) -> bool:
        all_checks = self.connection_checks + self.spec_checks + self.match_checks
        return not any(c.status == "error" for c in all_checks)
```

---

## 19. Testing strategy

### Unit tests
- **Spec parsing and validation** — valid YAML, invalid YAML, empty match rules, cross-app conflicts, depends_on cycles, all edge cases.
- **Match rule evaluation** — every match criterion against mock `Window` objects, AND/OR/NOT composition, confidence scoring.
- **Normalization** — default merging, flattening, reference resolution.
- **Resolution** — matched/drifted/missing/ambiguous/optional-missing states against mock snapshots.
- **Plan compilation** — resolution to plan step generation, ordering, dependency handling.
- **Diff computation** — resolution to human-readable diff.

### Snapshot replay tests
- Record real `Snapshot` objects from niri sessions.
- Verify matching, resolution, planning, and diff against recorded state.
- Golden-file tests: input YAML + snapshot -> expected plan / diff.

### Integration tests (requires running niri)
- Full apply cycle with real compositor.
- Capture and re-apply roundtrip.
- Reconcile idempotency (apply twice = same result).

### Mock transport tests
- Use `niri-state`'s architecture to inject fake snapshots.
- Test executor logic without a real compositor.

---

## 20. Implementation phases

### Phase 1: Spec + Matching
**Packages:** `spec/`, `resolve/normalizer.py`, `resolve/matcher.py`, `resolve/models.py`

- Session spec models (Pydantic) with aggressive validation.
- YAML loader with validation pipeline.
- Normalization (spec -> NormalizedSession).
- Matching engine (evaluate MatchRule against Window).
- Confidence scoring and explainable match decisions.

**Deliverable:** Parse session YAML, normalize, evaluate matches against mock Windows. Full test suite for spec validation and matching.

### Phase 2: Resolution + Diff
**Packages:** `resolve/resolver.py`, `planning/models.py` (SessionDiff)

- Resolver: NormalizedSession + Snapshot -> Resolution.
- Drift detection (workspace placement, floating state, etc.).
- SessionDiff: Resolution -> human-readable diff.
- `nirip diff` command (basic CLI).

**Deliverable:** `nirip diff session.yaml` shows what would change without touching anything.

### Phase 3: Planning
**Packages:** `planning/compiler.py`, `planning/ordering.py`

- Plan compiler: Resolution -> Plan (ordered steps).
- Topological sort with dependency handling.
- Step ID generation and dependency wiring.
- `nirip plan` command (display compiled plan).

**Deliverable:** Full Plan from Resolution, with correct ordering and dependencies.

### Phase 4: Execution
**Packages:** `execution/`, `facade/`

- Executor: run Plan steps with event-verified confirmation.
- Action translation (PlanStep -> niri-pypc Action) via helper layer.
- Verification predicates for each step kind.
- Failure predicates for early detection.
- SessionRuntime for ephemeral state tracking.
- `AsyncNirip` and `SyncNirip` facade.
- `nirip apply` command.

**Deliverable:** Actually restore sessions end-to-end.

### Phase 5: Capture + Polish
**Packages:** `capture/`, CLI polish

- Snapshot -> SessionSpec scaffold with inferred match rules.
- YAML output with guiding comments.
- `nirip capture` command.
- `nirip doctor` (connection check, spec validation, match ambiguity detection).
- `nirip watch` (stream state changes).
- `nirip inspect` (current state summary).
- `nirip status` (managed sessions).
- Persistent managed state tracking.
- Better error messages and diagnostics.

**Deliverable:** Complete CLI with capture, diagnostics, and polish.

---

## 21. Scope and non-goals

### In scope (v1)
- Workspace-oriented session restore and reconciliation
- Three-stage pipeline: normalize -> resolve -> plan -> execute
- Event-driven spawn -> match -> place -> verify cycle
- Diff / plan / apply / capture workflow
- YAML session specs with aggressive validation
- Python library (AsyncNirip + SyncNirip) and CLI
- Idempotent reconciliation
- Explainable matching with confidence scoring
- `@computed_field` on all result/output models

### Out of scope (v1)
- Exact column/tile geometry replay (niri IPC doesn't fully support this yet)
- App-specific integrations (restoring browser tabs, editor sessions, etc.)
- Multi-version niri compatibility (pinned to niri-ipc 25.11)
- Non-niri compositors
- Daemon mode / auto-apply on events
- tmux-style session switching (nirip is apply-on-demand, not a persistent manager)
- Per-app output affinity (output is workspace-level only)
- `observe/` wrapper around niri-state (unnecessary indirection)

### Future possibilities
- Session groups / profiles (apply multiple session specs)
- Conditional workspace specs (only apply on multi-monitor setups)
- Integration with sidebard for context-aware session switching
- Watch mode: continuously reconcile toward declared state
- TOML spec format support
- Upstream action helpers in niri-pypc

---

## 22. Key integration patterns

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

## 23. Design decision summary

These are the key architectural decisions made by merging the original concept with the deep research analysis:

| # | Decision | Rationale |
|---|---|---|
| 1 | **Three-stage pipeline** (normalize -> resolve -> plan -> execute) | Resolution is a genuinely different concern from Plan compilation. Makes diff first-class, not an afterthought. |
| 2 | **Apps nested under workspaces** in YAML | Users think "workspace X should have apps A, B, C." Normalizer flattens internally. |
| 3 | **`name` not `key`** for app identifier | Natural YAML reading. Add `label` later if needed. |
| 4 | **PlacementSpec** extended with `fullscreen`, `maximized` | Real placement concerns supported by niri actions. |
| 5 | **`resolve/` and `facade/`** adopted, `observe/` and centralized `model/` skipped | resolve/ is independently testable. observe/ is unnecessary indirection. Each subsystem owns its models. |
| 6 | **Hybrid step model** — enum for data, predicates in executor | Plan is serializable/displayable. Executor adds behavior. Best of both. |
| 7 | **Aggressive spec validation** | Catch problems at load time. Empty match rules rejected. Weak matchers warned. Inter-app conflicts detected. |
| 8 | **Action helper layer** in execution/actions.py | Generated types are verbose. Thin helpers keep executor readable. Upstream if practical. |
| 9 | **`AsyncNirip`** as primary API with richer return types | Library name, not "client." LiveDesktop, SessionDiff, ApplyResult are better public API names. |
| 10 | **`@computed_field`** on all result models | Derived values appear in serialization automatically. No manual maintenance. |
| 11 | **Output affinity is workspace-level only** | No per-app output in v1. Simpler execution semantics. |
| 12 | **Capture stays humble** | Scaffold with app_id match rules, no spawn commands, comments guiding refinement. |
| 13 | **Operational failures as structured results, not exceptions** | ApplyResult contains StepResult outcomes. Exceptions reserved for programmer misuse and dependency failures. |
