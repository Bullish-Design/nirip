# REVISED NIRIP CONCEPT

A ground-up rethink of nirip as a Nim workspace orchestrator, designed alongside sidebard.

---

## Brainstorming

### 1. Nim instead of Python

**Idea:** Rewrite the entire concept in Nim. Single static binary. No Python runtime, no pip, no virtualenv.

**Pros:**
- Single binary deployment via Nix — same packaging story as sidebard
- Shared Niri IPC library with sidebard (same language, same types)
- Algebraic data types for operations, plans, and results — compiler-enforced exhaustiveness
- No runtime dependency hell — the binary just works on any Linux
- Performance: the reconciler loop (action → wait → replan) benefits from low-latency IPC parsing
- `Result[T, E]` for every fallible operation — no exceptions, no "oops forgot to catch"
- Compile-time config validation via typed TOML deserialization
- Can share chronos async runtime with sidebard if they ever co-locate

**Cons:**
- Nim's ecosystem for YAML parsing is weaker than Python's (but we can use TOML instead)
- No Pydantic — config validation is manual (but Nim's type system + toml-serialization handles most of it)
- Plugin model is harder without dynamic loading (but we don't need dynamic plugins — see brainstorm #8)
- Smaller contributor pool (but this is a personal dotfiles project, not a community tool)

**Implications:**
- Config format should probably be TOML, not YAML (better Nim library support, consistent with sidebard)
- Plugin system needs rethinking — can't just `import plugin_module` at runtime
- Testing becomes compile-time type-checked fixtures rather than Pydantic model validation
- The IPC client can be a shared Nim package used by both sidebard and nirip

**Opportunity:** A `niri-ipc-nim` library package that both projects import. Typed request/response models, async socket client, event stream parser. Write once, use everywhere.

---

### 2. Shared niri-ipc library with sidebard

**Idea:** Extract the Niri IPC client into a standalone Nim package that both sidebard and nirip depend on.

**Pros:**
- DRY — one implementation of the Niri socket protocol
- Shared typed models for windows, workspaces, outputs, actions
- Bug fixes propagate to both projects
- Can be tested independently against Niri
- Natural place for the event stream state machine

**Cons:**
- Adds a dependency coordination concern (version both projects against the library)
- If Niri IPC changes, one update fixes both — but also one bug breaks both
- Slight over-engineering if the IPC surface is small enough to duplicate

**Implications:**
- Package structure: `niri-ipc-nim/` as a nimble package, imported by both `sidebard` and `nirip`
- The library owns: socket connection, JSON serialization, typed request/response, event stream parsing
- It does NOT own: state reduction, profile resolution, reconciliation logic

**Opportunity:** This library could become a community contribution — a proper typed Nim client for Niri that anyone can use. Even if we never publish it, having it separate keeps both projects cleaner.

---

### 3. TOML instead of YAML for profile config

**Idea:** Use TOML for workspace profiles instead of YAML.

**Pros:**
- Consistent with sidebard config format — one config language for the whole stack
- Better Nim library support (toml-serialization is mature, YAML in Nim is patchy)
- TOML is unambiguous (no "Norway problem," no implicit type coercion)
- Diff-friendly (no indentation sensitivity)
- Nix-adjacent community already uses TOML widely

**Cons:**
- TOML is worse at deeply nested structures — workspace → column → window → match → regex is 4 levels deep
- TOML arrays of tables (`[[workspace.columns]]`) are verbose compared to YAML lists
- Frozen profile snapshots may be large and TOML doesn't compress as elegantly as YAML for data-heavy files

**Implications:**
- Need to design the config schema to avoid excessive nesting
- May want a flat-file-per-workspace approach (like sidebard's plugins/) to keep individual files shallow
- Frozen snapshots could use a more compact format (JSON, or a TOML variant with less nesting)

**Opportunity:** A **directory-based profile format** instead of a single monolithic file:

```
~/.config/nirip/profiles/backend-dev/
├── profile.toml          # metadata, options
├── workspaces/
│   ├── code.toml         # one workspace per file
│   └── web.toml
└── frozen/               # snapshot data (optional, machine-generated)
    └── 2026-05-10.toml
```

This keeps TOML files shallow and human-editable while supporting complex multi-workspace profiles. Each workspace file is self-contained and easy to diff/review.

---

### 4. The reconciler as a pure planner (sidebard-style)

**Idea:** Apply sidebard's "reducer produces effects" pattern to nirip's reconciler. The planner is a pure function that takes (desired profile, current state) and returns a sequence of typed operations. The runtime executes them.

**Pros:**
- Testable without Niri — feed in fixture state, assert on operation sequence
- Replayable — log the plan, replay it, debug it
- Dry-run is free — just don't execute the effects
- Consistent architecture with sidebard — same mental model
- The "diff" command is literally just running the planner and formatting the output

**Cons:**
- The real reconciler needs to re-plan after each step (state changes between actions)
- Pure planning assumes you know the full state upfront — but window matching is probabilistic
- Over-purity could make the "wait for window to appear" logic awkward

**Implications:**
- The planner should be designed for iterative re-planning: `plan(profile, state) → ops`, execute first op, update state, re-plan
- This is not a single `reduce()` call — it's a loop of `plan → execute one → observe → plan again`
- The plan itself is still pure and deterministic given the same inputs

**Opportunity:** A `plan` command that shows exactly what nirip *would* do, step by step, with confidence scores for each match. This makes the tool trustworthy — users can review before applying.

---

### 5. Standalone binary vs sidebard integration

**Idea:** Should nirip be a separate binary, a sidebard subcommand, or a shared-library module inside sidebard?

**Option A: Separate binary, separate project**
- Pros: Clean separation of concerns. Each project is focused. Can be used independently.
- Cons: Two binaries to install. Two Niri connections. Slight coordination overhead.

**Option B: nirip as a sidebard subcommand (`sidebard project load`)**
- Pros: Single binary. Shared Niri connection. Shared state. No IPC between them.
- Cons: Massively expands sidebard's scope. Violates "sidebard is a state daemon, not an orchestrator." Harder to test in isolation.

**Option C: Separate binary, shared library package**
- Pros: Clean binary boundary. Shared types and Niri client via nimble package. Can communicate via sidebard RPC when needed.
- Cons: Need to manage the shared package dependency.

**Recommendation:** Option C. Separate `nirip` binary. Shared `niri-ipc-nim` library. Communication via sidebard's JSON-RPC when enriched context is needed. This preserves the "nirip is the sculptor, sidebard is the brain" separation while eliminating duplicated Niri protocol code.

---

### 6. Type-safe operation model

**Idea:** Instead of Python's class hierarchy of operations, use Nim's variant objects for a closed, exhaustive operation algebra.

**Pros:**
- Compiler enforces you handle every operation type
- Pattern matching with `case op.kind` — no forgotten cases
- Zero-cost abstraction — variant objects are just tagged unions
- Serializable for logging/debugging

**Cons:**
- Adding a new operation kind requires recompiling (but that's fine — it's not a plugin system)
- Variant objects can get verbose with many fields

**Implications:**
- The operation model becomes the core "language" of nirip — every compositor action the tool can take is a variant
- The planner produces `seq[Operation]`, the executor consumes them one at a time
- Logging an operation sequence is trivially serializable to JSON for debugging

**Opportunity:** Type the *expected outcome* alongside each operation:

```nim
type
  Operation* = object
    case kind*: OpKind
    of opSpawnWindow:
      spawnCmd*: seq[string]
      expectMatch*: MatchSpec    # what we expect to appear
      timeoutMs*: int
    of opMoveToWorkspace:
      windowId*: WindowId
      workspaceName*: string
      expectWorkspaceId*: WorkspaceId  # verify after
    ...
```

Each operation carries its success criterion. The executor can verify outcomes and flag drift without the planner needing to re-query.

---

### 7. Matching redesigned with algebraic types

**Idea:** Replace the Python score-based matcher with a typed, compositional matching DSL.

**Current Python approach:** A flat `MatchSpec` with optional fields, score-accumulation logic, and a threshold float.

**Nim approach:** A recursive `MatchRule` variant that composes:

```nim
type
  MatchRuleKind* = enum
    mrExactAppId
    mrRegexAppId
    mrExactTitle
    mrRegexTitle
    mrWorkspace
    mrPidFromSpawn
    mrPidDescendant
    mrOpenedAfter
    mrAnd
    mrOr
    mrNot

  MatchRule* = object
    case kind*: MatchRuleKind
    of mrExactAppId: appId*: string
    of mrRegexAppId: appIdPattern*: string
    of mrExactTitle: title*: string
    of mrRegexTitle: titlePattern*: string
    of mrWorkspace: workspace*: string
    of mrPidFromSpawn: discard
    of mrPidDescendant: ancestorPid*: int
    of mrOpenedAfter: afterTs*: MonoTime
    of mrAnd: andRules*: seq[MatchRule]
    of mrOr: orRules*: seq[MatchRule]
    of mrNot: negated*: MatchRule
```

**Pros:**
- Composable — `And(ExactAppId("code"), RegexTitle("backend"))` is a single typed value
- Evaluable as a pure function: `proc matches(rule: MatchRule, window: NiriWindow): MatchResult`
- Explainable — walk the rule tree and report which sub-rules matched/failed
- No magic float thresholds — matching is boolean with structured explanations
- TOML-representable as nested tables

**Cons:**
- More complex type than a flat struct with optional fields
- TOML representation needs careful design to stay human-friendly
- Loses the "fuzzy score" aspect — but do we actually need fuzzy matching?

**Implication:** Rethink whether score-based matching is actually needed. For a *declarative* profile tool, the user explicitly declares what a window looks like. If the declaration matches, it matches. If it doesn't, it doesn't. Fuzzy scoring is for *discovery* (freeze), not for *load* (where the user already told you what to expect).

**Opportunity:** Split matching into two modes:
1. **Load matching (deterministic):** Boolean rule evaluation. Either the window matches or it doesn't. User writes explicit rules.
2. **Freeze matching (heuristic):** Score-based fuzzy matching for correlating frozen state with live windows. Used only during `freeze` to generate match rules for the user.

---

### 8. Plugin model in Nim

**Idea:** Rethink plugins without Python's dynamic import. In Nim, "plugins" are either:
- Compile-time registered modules (static dispatch)
- External processes invoked via subprocess/IPC (dynamic dispatch)

**Option A: Compiled-in app modules**

```nim
# plugins/chrome.nim
proc captureState*(window: NiriWindow): Option[JsonNode] = ...
proc prepareLaunch*(config: JsonNode): LaunchPlan = ...
proc matchContribution*(window: NiriWindow, saved: JsonNode): Option[MatchRule] = ...
```

All plugins compiled into the binary. Registered at compile time. No dynamic loading.

- Pros: Type-safe. Fast. No subprocess overhead. Easy to test.
- Cons: Adding a plugin requires recompiling. Can't add user plugins without forking.
- Verdict: Fine for a personal dotfiles project. Wrong for a community tool.

**Option B: External process plugins**

```toml
[plugins.chrome]
command = "nirip-plugin-chrome"
capabilities = ["capture", "launch", "match"]
```

Plugins are separate executables that nirip invokes with JSON on stdin/stdout.

- Pros: Language-agnostic. User-extensible. Sandboxable.
- Cons: Subprocess overhead per invocation. Schema coordination.
- Verdict: Right for extensibility, but over-engineered for v1.

**Option C: No plugins in v1; app-specific logic as config**

Most "plugin" behavior from the original concept is actually just:
- Chrome: launch with specific profile + URLs → that's just a `command` with args
- Firefox: launch with profile → just a command
- Terminals: launch in cwd with title → just a command
- Editors: open workspace → just a command

The *capture* side (freezing browser tabs, editor state) is the only part that truly needs plugin logic. And that's a Phase 3 concern.

- Pros: Dramatically simpler. Ship faster. Add plugins only when the need is proven.
- Cons: Can't capture app-internal state in freeze mode. Freeze output is purely compositor-level.
- Verdict: Start here. The original concept acknowledged this is the right MVP scope.

**Recommendation:** Option C for v1. Option A for v2 (compiled-in modules for common apps). Option B only if the tool becomes a community project.

---

### 9. State persistence redesign

**Original concept:** SQLite + SQLModel for window tracking history and profile run logs.

**Rethink for Nim:**

**Option A: No persistent state**

The tool is stateless. Every invocation reads Niri + config, computes a plan, executes. No database.

- Pros: Simplest possible model. No state corruption. No cleanup needed. Matches sidebard's "stateless across restarts" philosophy.
- Cons: Can't correlate "I launched this window" with "this window appeared" across invocations. Freeze can't remember which profile originally managed a window.

**Option B: Flat JSON state file**

```
~/.local/state/nirip/
├── active.json           # currently loaded profiles + managed window IDs
└── history/              # optional run logs
    └── 2026-05-10T14:30:00.json
```

- Pros: Simple. Human-readable. Easy to debug. Easy to blow away.
- Cons: No efficient queries. Grows linearly.

**Option C: Single-file state with managed window associations**

```json
{
  "loaded_profiles": {
    "backend-dev": {
      "loaded_at": "2026-05-10T14:30:00Z",
      "managed_windows": {
        "editor": { "niri_id": 42, "pid": 1234 },
        "terminal": { "niri_id": 43, "pid": 1235 }
      }
    }
  }
}
```

- Pros: Enough state to know "window 42 was launched by profile backend-dev as role editor." Enables idempotent reload (don't re-launch what's already there). Enables `nirip close backend-dev` (knows which windows to close).
- Cons: State can drift from reality (window closed but state file not updated). Requires a "repair" concept.

**Recommendation:** Option C. A simple JSON state file tracking which profiles are loaded and which Niri window IDs they manage. Updated on load/close. Treated as advisory (always verify against live Niri state). No SQLite.

---

### 10. Freeze as a first-class pure function

**Idea:** Freeze should be a pure function from Niri state snapshot → profile TOML. No side effects, no state file updates, no network calls beyond the initial snapshot.

**Pros:**
- Testable with fixture snapshots
- Deterministic — same Niri state always produces same profile
- Can be piped, diffed, version-controlled
- No "freeze accidentally mutated something" risk

**Cons:**
- Without plugin capture hooks, freeze is limited to compositor-level data
- Without state file context, freeze can't annotate "this window was launched by command X"

**Implication:** Freeze output is a *starting point* that the user edits. It captures structure (workspaces, columns, positions, app_ids, titles) but not launch commands. The user fills in commands, tightens match rules, and names their windows.

**Opportunity:** A `nirip freeze --annotate` mode that reads the state file and annotates frozen windows with their known launch commands (from prior loads). This bridges the gap without making freeze impure — it reads state file as an input, same as it reads Niri state.

---

### 11. Directory-per-profile vs monolithic file

**Idea:** Profiles as directories with one file per workspace, instead of one giant TOML/YAML file.

**Proposed structure:**
```
~/.config/nirip/profiles/
├── backend-dev/
│   ├── profile.toml          # name, options, output aliases
│   ├── code.toml             # workspace "backend:code"
│   └── web.toml              # workspace "backend:web"
├── personal/
│   ├── profile.toml
│   ├── chat.toml
│   └── media.toml
└── _templates/               # reusable workspace fragments
    └── terminal-stack.toml
```

**Pros:**
- Each file stays shallow (TOML works well at 2-3 levels of nesting)
- Easy to add/remove workspaces without editing a monolith
- Git-friendly (changes to one workspace don't pollute diffs for others)
- Supports large profiles (10+ workspaces) without unwieldy files
- Natural composition — copy a workspace file between profiles

**Cons:**
- More filesystem overhead for simple 1-workspace profiles
- Need a discovery/loading convention
- Can't just `cat profile.toml` to see everything

**Opportunity:** Support both modes:
- Single `profile.toml` with inline workspaces for simple profiles
- Directory with split files for complex profiles
- Loader detects which mode based on whether the path is a file or directory

---

### 12. Niri action addressing improvements

**Idea:** The original concept notes that many Niri actions are focus-sensitive (consume into column, set width, etc.). The reconciler must "focus window A, then do action." This is fragile.

**Nim opportunity:** Model focus-sensitivity explicitly in the operation type:

```nim
type
  FocusRequirement* = enum
    frNone            # action addresses by ID, no focus needed
    frWindowFocused   # requires specific window to be focused
    frColumnFocused   # requires window in target column to be focused

  Operation* = object
    focusReq*: FocusRequirement
    case kind*: OpKind
    ...
```

The executor handles focus requirements generically:
1. Check if focus requirement is met
2. If not, focus the required target first
3. Verify focus landed correctly
4. Execute the action
5. Verify the outcome

This separates "what action to take" from "what focus setup is needed" and makes the executor's retry/verify logic uniform.

**Opportunity:** Track which Niri actions are ID-addressed vs focus-sensitive in a single place. As Niri adds more ID-addressed actions upstream, the executor can drop focus requirements without changing the planner.

---

### 13. Event-stream-driven executor

**Idea:** Instead of polling Niri state between actions, use the event stream to confirm each operation's outcome.

**Flow:**
```
1. Execute operation (e.g., MoveWindowToWorkspace)
2. Wait for confirming event (WindowChanged with new workspace_id)
3. Timeout if no confirmation within N ms
4. Proceed or replan based on observed event
```

**Pros:**
- Faster than poll-based confirmation (events arrive immediately)
- More reliable (event stream is the canonical state source)
- Natural integration with chronos async (already used by sidebard's Niri adapter)
- Detects external interference (user or another tool moves something during reconciliation)

**Cons:**
- Some Niri actions may not produce clean confirmation events
- Need to handle "expected event never arrives" gracefully
- Slightly more complex than "sleep 100ms, re-query Windows"

**Opportunity:** If nirip and sidebard share a `niri-ipc-nim` library, the event stream parser is already written and tested. Nirip can use the same typed event model.

---

### 14. Workspace templates and composition

**Idea:** Instead of every profile being fully self-contained, support reusable workspace fragments.

```toml
# _templates/dev-terminal-pair.toml
[template]
id = "dev-terminal-pair"
params = ["project_path", "workspace_prefix"]

[[columns]]
id = "editor"
width = 0.62
[[columns.windows]]
id = "editor"
command = ["code", "${project_path}"]
match.app_id = "code"
match.title_regex = "${project_path | basename}"

[[columns]]
id = "terminal"
width = 0.38
[[columns.windows]]
id = "shell"
command = ["ghostty", "--working-directory", "${project_path}"]
match.app_id = "com.mitchellh.ghostty"
```

Then in a profile:
```toml
# backend-dev/code.toml
[workspace]
name = "backend:code"
output = "primary"
template = "dev-terminal-pair"
template_params = { project_path = "~/src/backend", workspace_prefix = "backend" }
```

**Pros:**
- DRY — common patterns (editor+terminal, browser+devtools) defined once
- Parameterized — different projects use the same layout skeleton
- Encourages consistency across profiles

**Cons:**
- Template resolution adds complexity to the config loader
- String interpolation in TOML is non-standard (need a custom resolver)
- Over-engineering risk for a personal tool

**Implication:** This is a Phase 2+ feature. v1 should work with fully-expanded profiles. But the directory structure should *accommodate* templates without needing a redesign.

---

### 15. Integration with Nix workspace generation

**Idea:** The dotfiles project already generates Niri workspace config from Nix (workspace-per-file loader). Nirip profiles could be *generated from Nix* too, alongside the Niri config.

```nix
my.desktop.nirip.profiles.backend-dev = {
  workspaces = {
    code = {
      output = "primary";
      columns = [
        { width = 0.62; windows = [{ id = "editor"; command = "code ~/src/backend"; match.app_id = "code"; }]; }
        { width = 0.38; windows = [{ id = "shell"; command = "ghostty"; match.app_id = "com.mitchellh.ghostty"; }]; }
      ];
    };
  };
};
```

Nix generates TOML profiles at build time. Nirip reads them at runtime.

**Pros:**
- Single source of truth for workspace structure (Nix)
- Profile files are reproducible and version-controlled
- Can cross-reference Niri workspace config with nirip profiles (same Nix module defines both)
- Consistent with the broader project's "Nix owns static config" philosophy

**Cons:**
- Profiles become immutable (Nix-managed) — can't edit at runtime
- Frozen profiles (from `nirip freeze`) live outside Nix — need a workflow for incorporating them
- Adds a Nix module to maintain

**Opportunity:** Two profile sources:
1. **Nix-managed profiles** (in `~/.config/nirip/profiles/`, Nix-generated, immutable)
2. **User profiles** (in `~/.local/share/nirip/profiles/`, user-created, editable, from freeze)

Nirip reads both. Nix profiles are the "declared desired state." User profiles are ad-hoc captures.

---

## The one-sentence version

Nirip is a **typed Nim CLI** that loads, freezes, diffs, and reconciles declarative Niri workspace layouts from TOML profile files, sharing a Niri IPC library with sidebard.

---

## Philosophy

### 1. Declarative workspace orchestration

A profile is a complete description of a workspace layout. `nirip load` reconciles reality toward that description. `nirip freeze` captures reality into that description. The profile is the source of truth — not the running desktop state.

### 2. Pure planning, effectful execution

The planner is a pure function: `plan(desired, actual) → operations`. It has no I/O, no async, no side effects. The executor is the only component that touches Niri IPC. This makes planning testable, diffable, and explainable without a running compositor.

### 3. Compositor-level only

Nirip restores what Niri controls: workspaces, columns, windows, positions, sizes. Application-internal state (editor buffers, browser tabs, terminal sessions) is out of scope for v1. App-specific modules may add capture/restore in later phases.

### 4. Explicit over automatic

No background daemon saving state. No implicit restore on login. The user explicitly loads and freezes. The tool explains what it will do before doing it. Dangerous operations (close, move unmanaged) require explicit opt-in.

### 5. Idempotent by design

Running `nirip load` twice produces the same result. If windows already match, they aren't re-launched. If columns are already in position, they aren't moved. The reconciler converges, it doesn't blindly replay.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                          nirip                              │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ config       │  │ planner      │  │ executor         │   │
│  │ loader       │  │ (pure)       │  │ (async, I/O)     │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                 │                   │             │
│         ▼                 ▼                   ▼             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              niri-ipc-nim (shared library)           │   │
│  │                                                      │   │
│  │  NiriClient  │  typed models  │  event stream        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ matcher      │  │ freezer      │  │ diagnostics      │   │
│  │ (pure)       │  │ (pure)       │  │ (pure)           │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Core loop (load)

```
1. Load profile from TOML
2. Snapshot current Niri state (windows, workspaces, outputs)
3. Plan: plan(profile, snapshot) → seq[Operation]
4. For each operation:
   a. Verify precondition (focus, window exists, etc.)
   b. Execute via Niri IPC
   c. Wait for confirming event or timeout
   d. Update local state from event
   e. Re-plan from current position if state diverged
5. Report results
```

### Core loop (freeze)

```
1. Snapshot current Niri state
2. Optionally read state file for launch command annotations
3. Transform: freeze(snapshot, options) → Profile
4. Serialize Profile to TOML
5. Write to stdout or file
```

Both loops are simple because the complexity lives in the pure functions (`plan`, `freeze`, `match`), not in the I/O.

---

## Module structure

```
src/
├── nirip.nim                    # entry point: CLI dispatch
├── nirip.nimble                 # package manifest
│
├── core/                        # pure domain — zero I/O, zero async
│   ├── types.nim                # all domain types
│   ├── config.nim               # TOML → typed profile, validation
│   ├── planner.nim              # plan(desired, actual) → seq[Operation]
│   ├── matcher.nim              # window matching rules, evaluation
│   ├── freezer.nim              # niri state → profile structure
│   └── diagnostics.nim          # explain matches, format plans, diff
│
├── executor/                    # async I/O — executes plans against Niri
│   ├── runner.nim               # operation loop with event confirmation
│   ├── launcher.nim             # spawn processes, track PIDs
│   └── focus.nim                # focus management for focus-sensitive ops
│
├── state/                       # lightweight persistence
│   └── managed.nim              # active profiles + managed window IDs (JSON)
│
└── cli.nim                      # CLI subcommands via cligen
```

### Shared dependency

```
niri-ipc-nim/                    # separate nimble package
├── src/
│   ├── niri_ipc.nim             # public API
│   ├── client.nim               # async socket client
│   ├── models.nim               # NiriWindow, NiriWorkspace, NiriOutput, etc.
│   ├── requests.nim             # typed request builders
│   ├── events.nim               # event stream parser + types
│   └── actions.nim              # typed action constructors
└── tests/
    ├── fixtures/                # recorded Niri JSON responses
    └── test_client.nim
```

---

## Type system

### Identifiers

```nim
import std/[options, tables, times]
import results
import niri_ipc

type
  ProfileName*   = distinct string
  WorkspaceName* = distinct string
  WindowRole*    = distinct string   # "editor", "terminal", "browser"
  ColumnRole*    = distinct string   # "main", "tools", "reference"
  OutputAlias*   = distinct string   # "primary", "laptop"
```

### Profile model

```nim
type
  ProfileOptions* = object
    matchExisting*:    bool          # try to match running windows before launching
    launchMissing*:    bool          # spawn windows that don't match
    moveUnmanaged*:    bool          # move non-profile windows out of the way
    closeExtra*:       bool          # close windows from prior load that aren't in profile
    timeoutMs*:        int           # max wait for window to appear after launch
    focusAfterLoad*:   Option[string] # "workspace:code/editor" path to focus

  OutputAliases* = Table[OutputAlias, seq[string]]  # alias → real output names

  Profile* = object
    name*:        ProfileName
    description*: string
    options*:     ProfileOptions
    outputs*:     OutputAliases
    workspaces*:  seq[WorkspaceSpec]

  WorkspaceSpec* = object
    name*:        WorkspaceName
    output*:      Option[string]     # output name or alias
    index*:       Option[int]        # ordering hint
    focus*:       Option[WindowRole] # focus target after load
    columns*:     seq[ColumnSpec]

  ColumnSpec* = object
    id*:          Option[ColumnRole]
    width*:       Option[SizeSpec]
    display*:     ColumnDisplay
    windows*:     seq[WindowSpec]

  ColumnDisplay* = enum
    cdNormal
    cdTabbed

  SizeSpec* = object
    case kind*: SizeKind
    of skProportion:
      ratio*: float                  # 0.0..1.0
    of skPixels:
      px*: int

  SizeKind* = enum
    skProportion
    skPixels

  WindowSpec* = object
    id*:          WindowRole
    command*:     Option[seq[string]] # argv to launch
    cwd*:         Option[string]
    env*:         Table[string, string]
    match*:       MatchRule
    height*:      Option[SizeSpec]
    floating*:    bool
```

### Match rules (compositional)

```nim
type
  MatchRuleKind* = enum
    mrExactAppId
    mrRegexAppId
    mrExactTitle
    mrRegexTitle
    mrWorkspaceName
    mrPidFromSpawn
    mrOpenedAfter
    mrAll             # AND: all sub-rules must match
    mrAny             # OR: at least one sub-rule must match
    mrNot             # negation

  MatchRule* = ref object
    case kind*: MatchRuleKind
    of mrExactAppId:
      appId*: string
    of mrRegexAppId:
      appIdPattern*: string
    of mrExactTitle:
      title*: string
    of mrRegexTitle:
      titlePattern*: string
    of mrWorkspaceName:
      workspace*: string
    of mrPidFromSpawn:
      discard
    of mrOpenedAfter:
      afterTs*: MonoTime
    of mrAll:
      allRules*: seq[MatchRule]
    of mrAny:
      anyRules*: seq[MatchRule]
    of mrNot:
      negated*: MatchRule

  MatchResult* = object
    matched*: bool
    explanation*: seq[string]       # human-readable trace
```

Match rules are `ref object` to allow recursive composition without value-type recursion issues.

### TOML representation of match rules

```toml
# Simple (most common): flat fields become implicit All(...)
[windows.editor.match]
app_id = "code"
title_regex = "backend"
# Deserialized as: All(ExactAppId("code"), RegexTitle("backend"))

# Explicit composition when needed
[windows.browser.match]
any = [
  { app_id_regex = "(?i)chrome|chromium" },
  { app_id_regex = "(?i)firefox" },
]
title_regex = "localhost"
# Deserialized as: All(Any(RegexAppId("chrome|chromium"), RegexAppId("firefox")), RegexTitle("localhost"))

# Negation
[windows.editor.match]
app_id = "code"
not = { title_regex = "Settings" }
# Deserialized as: All(ExactAppId("code"), Not(RegexTitle("Settings")))
```

The flat form (most common) deserializes into `All(...)`. Explicit `any`/`not` keys enable composition when needed. 90% of profiles never need the compositional forms.

### Operations

```nim
type
  OpKind* = enum
    opEnsureWorkspace
    opMoveWorkspaceToOutput
    opMoveWorkspaceToIndex
    opSpawnWindow
    opWaitForWindow
    opMatchExistingWindow
    opMoveWindowToWorkspace
    opMoveWindowToTiling
    opMoveWindowToFloating
    opConsumeIntoColumn
    opMoveColumnToIndex
    opSetColumnWidth
    opSetWindowHeight
    opSetColumnDisplay
    opFocusWindow
    opFocusWorkspace

  FocusReq* = enum
    frNone
    frWindow
    frColumn

  Operation* = object
    focusReq*: FocusReq
    focusTarget*: Option[niri_ipc.WindowId]
    case kind*: OpKind
    of opEnsureWorkspace:
      wsName*: WorkspaceName
      wsOutput*: Option[string]
    of opMoveWorkspaceToOutput:
      mwsName*: WorkspaceName
      mwsOutput*: string
    of opMoveWorkspaceToIndex:
      mwiName*: WorkspaceName
      mwiIndex*: int
    of opSpawnWindow:
      spawnRole*: WindowRole
      spawnCmd*: seq[string]
      spawnCwd*: Option[string]
      spawnEnv*: Table[string, string]
      spawnMatch*: MatchRule
      spawnTimeout*: int
    of opWaitForWindow:
      waitRole*: WindowRole
      waitMatch*: MatchRule
      waitTimeout*: int
    of opMatchExistingWindow:
      matchRole*: WindowRole
      matchRule*: MatchRule
    of opMoveWindowToWorkspace:
      mtwWindow*: niri_ipc.WindowId
      mtwWorkspace*: WorkspaceName
    of opMoveWindowToTiling:
      mttWindow*: niri_ipc.WindowId
    of opMoveWindowToFloating:
      mtfWindow*: niri_ipc.WindowId
    of opConsumeIntoColumn:
      cicWindow*: niri_ipc.WindowId
      cicTarget*: niri_ipc.WindowId  # window already in target column
    of opMoveColumnToIndex:
      mciWindow*: niri_ipc.WindowId  # any window in the column
      mciIndex*: int
    of opSetColumnWidth:
      scwWindow*: niri_ipc.WindowId
      scwSize*: SizeSpec
    of opSetWindowHeight:
      swhWindow*: niri_ipc.WindowId
      swhSize*: SizeSpec
    of opSetColumnDisplay:
      scdWindow*: niri_ipc.WindowId
      scdDisplay*: ColumnDisplay
    of opFocusWindow:
      fwWindow*: niri_ipc.WindowId
    of opFocusWorkspace:
      fwsName*: WorkspaceName

  PlanResult* = object
    operations*: seq[Operation]
    matchedWindows*: Table[WindowRole, niri_ipc.WindowId]
    unmatchedRoles*: seq[WindowRole]
    warnings*: seq[string]
```

---

## Config format

### Profile directory structure

```
~/.config/nirip/
├── config.toml                  # global settings
└── profiles/
    ├── backend-dev/
    │   ├── profile.toml         # metadata + options
    │   ├── code.toml            # workspace spec
    │   └── web.toml             # workspace spec
    └── personal.toml            # single-file profile (simple case)
```

### Global config (`config.toml`)

```toml
[defaults]
timeout_ms = 20000
match_existing = true
launch_missing = true

[outputs]
# global output aliases
primary = ["DP-1", "DP-2", "eDP-1"]
laptop = ["eDP-1"]

[sidebard]
# optional sidebard integration
socket = "/run/user/1000/sidebard.sock"
query_ownership = true            # skip sidebar-owned windows during match
```

### Profile metadata (`backend-dev/profile.toml`)

```toml
name = "backend-dev"
description = "Backend development layout"

[options]
match_existing = true
launch_missing = true
move_unmanaged = false
close_extra = false
timeout_ms = 15000
focus_after_load = "code/editor"

[outputs]
primary = ["DP-1", "eDP-1"]
```

### Workspace spec (`backend-dev/code.toml`)

```toml
[workspace]
name = "backend:code"
output = "primary"
index = 1
focus = "editor"

[[columns]]
id = "main"
width = 0.62
display = "normal"

[[columns.windows]]
id = "editor"
command = ["code", "~/src/backend"]

[columns.windows.match]
app_id = "code"
title_regex = "backend"

[[columns]]
id = "tools"
width = 0.38
display = "normal"

[[columns.windows]]
id = "shell"
command = ["ghostty", "--working-directory", "~/src/backend"]

[columns.windows.match]
app_id = "com.mitchellh.ghostty"
```

### Single-file profile (`personal.toml`)

```toml
name = "personal"
description = "Chat and media layout"

[[workspaces]]
name = "personal:chat"
output = "primary"

[[workspaces.columns]]
width = 1.0

[[workspaces.columns.windows]]
id = "discord"
command = ["vesktop"]

[workspaces.columns.windows.match]
app_id = "vesktop"

[[workspaces]]
name = "personal:media"

[[workspaces.columns]]
width = 1.0

[[workspaces.columns.windows]]
id = "spotify"
command = ["spotify"]

[workspaces.columns.windows.match]
app_id_regex = "spotify"
```

Both formats (directory and single-file) are supported. The loader detects based on whether the path is a directory or a `.toml` file.

---

## CLI interface

```
nirip load <profile>             # reconcile desktop toward profile
nirip plan <profile>             # show what load would do (dry-run)
nirip freeze [options]           # capture current state as a profile
nirip diff <profile>             # compare profile against current state
nirip doctor <profile>           # validate profile, check Niri, report issues
nirip list                       # list known profiles
nirip close <profile>            # close windows managed by profile
nirip status                     # show loaded profiles + managed windows
```

### Flags

```
--json                           # JSON output (default for scripting)
--pretty                         # human-readable output (default for TTY)
--workspace <name>               # limit to specific workspace(s)
--force                          # skip confirmation for dangerous ops
--verbose                        # detailed operation logging
--sidebard                       # query sidebard for enriched context
```

### Examples

```bash
# Load a project layout
nirip load backend-dev

# See what would happen without doing it
nirip plan backend-dev

# Freeze current named workspaces
nirip freeze > ~/frozen.toml

# Freeze specific workspaces into a profile directory
nirip freeze --workspace "backend:*" --dir ~/.config/nirip/profiles/backend-dev/

# Compare reality vs profile
nirip diff backend-dev

# Validate a profile
nirip doctor backend-dev

# Close all windows from a loaded profile
nirip close backend-dev
```

---

## The planner (pure)

```nim
proc plan*(profile: Profile, state: NiriSnapshot, managed: ManagedState): PlanResult =
  ## Pure function. No I/O.
  ## Computes the minimum set of operations to reconcile state toward profile.
  ##
  ## Strategy:
  ## 1. Ensure all workspaces exist
  ## 2. Match existing windows to profile roles
  ## 3. Plan launches for unmatched roles (if launch_missing)
  ## 4. Plan moves for matched windows not in correct workspace
  ## 5. Plan column formation (consume, ordering)
  ## 6. Plan sizing (column width, window height)
  ## 7. Plan focus
  ##
  ## The planner is conservative: it does the minimum work.
  ## It does not move windows that are already correctly placed.
  ## It does not resize columns that are already approximately correct.
```

The planner runs multiple times during a load (after each operation or batch). Each run re-evaluates from current state. Operations that are already satisfied are dropped.

---

## The executor (async)

```nim
proc execute*(client: NiriClient, plan: PlanResult,
              events: NiriEventStream): Future[ExecuteResult] {.async.} =
  ## Executes operations one at a time.
  ## After each operation, waits for a confirming event or timeout.
  ## If state diverges from expectations, re-invokes the planner.
  ##
  ## Returns a structured result with:
  ## - completed operations
  ## - failed operations with reasons
  ## - skipped operations (already satisfied)
  ## - final state summary
```

### Focus management

```nim
proc ensureFocus*(client: NiriClient, events: NiriEventStream,
                  op: Operation): Future[Result[void, string]] {.async.} =
  ## If op.focusReq != frNone:
  ##   1. Check current focus
  ##   2. If wrong, issue FocusWindow action
  ##   3. Wait for WindowFocusChanged event confirming correct focus
  ##   4. Return Ok or Err("focus did not land on expected window")
```

---

## The matcher (pure)

```nim
proc evaluate*(rule: MatchRule, window: niri_ipc.NiriWindow,
               context: MatchContext): MatchResult =
  ## Recursively evaluate a match rule against a window.
  ## Returns matched=true/false with full explanation trace.
  ##
  ## MatchContext carries:
  ## - spawn timestamps (for mrOpenedAfter)
  ## - launched PIDs (for mrPidFromSpawn)
  ## - workspace name cache

proc findMatches*(rule: MatchRule, windows: seq[niri_ipc.NiriWindow],
                  context: MatchContext): seq[RankedMatch] =
  ## Evaluate rule against all candidate windows.
  ## Return matched windows sorted by specificity (more rule hits = better).
  ## Ties broken by recency (newest window wins).
```

### Match explanation output

```
editor: matched window 42 (code - backend - Visual Studio Code)
  ✓ app_id = "code" (exact match)
  ✓ title_regex "backend" matched "code - backend - Visual Studio Code"

browser: no match found
  candidate window 51 (Google Chrome): FAILED
    ✓ app_id_regex "(?i)chrome" matched "Google-chrome"
    ✗ title_regex "localhost:3000" did not match "New Tab"
  candidate window 52 (Firefox): FAILED
    ✗ app_id_regex "(?i)chrome" did not match "firefox"
```

---

## The freezer (pure)

```nim
proc freeze*(state: NiriSnapshot, options: FreezeOptions,
             managed: Option[ManagedState]): Profile =
  ## Pure function: Niri state → Profile.
  ##
  ## Strategy:
  ## 1. Select workspaces (named by default, all if --all)
  ## 2. Group windows by column index (from layout.pos_in_scrolling_layout)
  ## 3. Order windows within columns by tile index
  ## 4. Generate match rules from app_id + title
  ## 5. Annotate with launch commands from managed state (if available)
  ## 6. Generate column widths from layout data
  ## 7. Return typed Profile
```

### Freeze options

```nim
type
  FreezeOptions* = object
    includeAll*: bool              # include unnamed workspaces
    workspaceFilter*: Option[string]  # glob pattern for workspace names
    annotateCommands*: bool        # look up launch commands from state file
    outputFormat*: FreezeFormat

  FreezeFormat* = enum
    ffDirectory    # split into workspace files
    ffSingleFile   # one TOML file
```

---

## State file

Lightweight JSON tracking loaded profiles and managed window associations.

```nim
type
  ManagedWindow* = object
    role*: WindowRole
    niriId*: Option[niri_ipc.WindowId]
    pid*: Option[int]
    launchCommand*: Option[seq[string]]
    matchedAt*: string              # ISO timestamp

  LoadedProfile* = object
    name*: ProfileName
    loadedAt*: string               # ISO timestamp
    windows*: Table[WindowRole, ManagedWindow]

  ManagedState* = object
    profiles*: Table[ProfileName, LoadedProfile]
```

Location: `$XDG_STATE_HOME/nirip/state.json`

Updated:
- After successful `load` (record managed windows)
- After `close` (remove profile entry)
- Verified against live Niri state on read (dead windows pruned)

---

## Diagnostics

### `nirip plan` output

```
Profile: backend-dev

Workspaces:
  ✓ backend:code exists on DP-1
  + backend:web will be created on DP-1

Windows:
  ✓ editor: matched window 42 (already in backend:code, column 1)
  ~ shell: matched window 43 (needs move to backend:code, column 2)
  + browser: will launch "google-chrome-stable --new-window http://localhost:3000"

Operations (7):
  1. EnsureWorkspace "backend:web" on DP-1
  2. MoveWindow 43 → workspace "backend:code"
  3. ConsumeIntoColumn 43 → column containing 42
  4. MoveColumn [43] → index 2
  5. SetColumnWidth [42] → 0.62
  6. SetColumnWidth [43] → 0.38
  7. SpawnWindow "browser" → ["google-chrome-stable", "--new-window", "http://localhost:3000"]
```

### `nirip diff` output

```
Profile: backend-dev vs current state

backend:code
  editor       ✓  correct workspace, column 1, width ~0.62
  shell        ~  expected column 2, actual column 3 (drifted)

backend:web
  browser      ✗  missing (not running)

Summary: 1 ok, 1 drifted, 1 missing
```

### `nirip doctor` output

```
Profile: backend-dev

Config:
  ✓ profile.toml valid
  ✓ code.toml valid
  ✓ web.toml valid

Environment:
  ✓ $NIRI_SOCKET exists
  ✓ Niri version 26.4.0
  ✓ Output "DP-1" present (alias "primary" resolves)
  ⚠ Output "eDP-1" not connected (alias "laptop" unresolvable)

Windows:
  ✓ editor: "code" is on PATH
  ✓ shell: "ghostty" is on PATH
  ✓ browser: "google-chrome-stable" is on PATH

Match rules:
  ✓ All regexes compile
  ⚠ editor.match has no title_regex — may match wrong VS Code window
```

---

## Niri IPC shared library (`niri-ipc-nim`)

### Public API

```nim
## niri_ipc.nim — typed Niri IPC client for Nim

import std/[options, tables, asyncdispatch]
import chronos
import results

type
  NiriClient* = ref object
    ## Async client for Niri compositor IPC.
    ## Maintains a command socket and optionally an event stream socket.

  NiriWindow* = object
    id*: WindowId
    title*: Option[string]
    appId*: Option[string]
    pid*: Option[int]
    workspaceId*: Option[WorkspaceId]
    isFocused*: bool
    isFloating*: bool
    layout*: Option[WindowLayout]

  WindowLayout* = object
    posInScrollingLayout*: Option[tuple[column: int, tile: int]]
    size*: Option[tuple[width: int, height: int]]

  NiriWorkspace* = object
    id*: WorkspaceId
    idx*: int
    name*: Option[string]
    output*: Option[string]
    isActive*: bool
    isFocused*: bool
    activeWindowId*: Option[WindowId]

  NiriOutput* = object
    name*: string
    make*: Option[string]
    model*: Option[string]
    currentMode*: Option[OutputMode]

  NiriEvent* = object
    case kind*: NiriEventKind
    of nekWindowOpened, nekWindowChanged:
      window*: NiriWindow
    of nekWindowClosed:
      windowId*: WindowId
    of nekWindowFocusChanged:
      focusedId*: Option[WindowId]
    of nekWorkspaceActivated:
      workspaceId*: WorkspaceId
    # ... other events

# ─── client interface ─────────────────────────────

proc connect*(socketPath: string = ""): Future[Result[NiriClient, string]]
proc windows*(c: NiriClient): Future[Result[seq[NiriWindow], string]]
proc workspaces*(c: NiriClient): Future[Result[seq[NiriWorkspace], string]]
proc outputs*(c: NiriClient): Future[Result[seq[NiriOutput], string]]
proc focusedWindow*(c: NiriClient): Future[Result[Option[NiriWindow], string]]
proc action*(c: NiriClient, action: NiriAction): Future[Result[void, string]]

# ─── event stream ─────────────────────────────────

proc startEventStream*(c: NiriClient): Future[Result[void, string]]
proc nextEvent*(c: NiriClient): Future[Result[NiriEvent, string]]

# ─── typed actions ────────────────────────────────

proc spawn*(cmd: seq[string]): NiriAction
proc focusWindow*(id: WindowId): NiriAction
proc closeWindow*(id: WindowId): NiriAction
proc moveWindowToWorkspace*(id: WindowId, workspace: WorkspaceRef): NiriAction
proc setColumnWidth*(change: SizeChange): NiriAction
proc setWindowHeight*(change: SizeChange): NiriAction
proc consumeWindowIntoColumn*(): NiriAction
proc moveColumnToIndex*(idx: int): NiriAction
proc setWorkspaceName*(name: string): NiriAction
proc focusWorkspace*(workspace: WorkspaceRef): NiriAction
proc moveWorkspaceToOutput*(output: string): NiriAction

# ─── snapshot helper ──────────────────────────────

type
  NiriSnapshot* = object
    windows*: seq[NiriWindow]
    workspaces*: seq[NiriWorkspace]
    outputs*: seq[NiriOutput]
    focusedWindowId*: Option[WindowId]

proc snapshot*(c: NiriClient): Future[Result[NiriSnapshot, string]]
  ## Fetches windows + workspaces + outputs + focused in one call sequence.
```

This library is used by both sidebard (for its niri adapter) and nirip (for orchestration). Sidebard uses the event stream primarily; nirip uses snapshots and actions primarily.

---

## Implementation phases

### Phase 1 — niri-ipc-nim library + snapshot

Build the shared library. Connect to Niri. Fetch windows/workspaces/outputs. Parse typed responses.

**Ships:** `niri-ipc-nim` nimble package. A trivial `nirip snapshot --json` that dumps current state.

**Proves:** The Niri socket protocol works in Nim. Typed models parse correctly. The library is usable.

### Phase 2 — Config loader + matcher + freeze

Implement profile TOML loading, match rule evaluation, and the freezer.

**Ships:** `nirip freeze --all`, `nirip doctor <profile>`.

**Proves:** Config schema works. Match rules evaluate correctly. Freeze produces valid round-trippable profiles.

### Phase 3 — Planner + basic executor

Implement the pure planner and a basic sequential executor. Handle workspace creation, window matching, basic moves.

**Ships:** `nirip plan <profile>`, `nirip load <profile>` (workspaces + window placement, no column formation yet).

**Proves:** The plan → execute loop works. Windows end up in the right workspaces. Idempotent reload works.

### Phase 4 — Column formation + sizing

Implement the hard part: consuming windows into columns, ordering columns, setting widths/heights. Focus management for focus-sensitive operations.

**Ships:** Full `nirip load` with column arrangement. `nirip diff`.

**Proves:** Column construction is reliable enough for daily use. Focus-sensitive operations verify correctly.

### Phase 5 — Event-stream executor + state file

Replace poll-based confirmation with event-stream-driven execution. Add state file for managed window tracking. Implement `nirip close` and `nirip status`.

**Ships:** Faster, more reliable reconciliation. Profile lifecycle (load/close/status).

**Proves:** Event-driven execution is more robust. State tracking enables idempotent operations.

### Phase 6 — Sidebard integration

Query sidebard for sidebar ownership (skip sidebar windows during matching). Expose nirip operations as sidebard command targets. Optional sidebard push subscription for reactive re-reconciliation.

**Ships:** `--sidebard` flag. Sidebard commands can invoke `nirip load/close`.

**Proves:** The tools work together without stepping on each other.

---

## What this intentionally excludes

- **Application-internal state.** No browser tabs, no editor buffers, no terminal sessions. Compositor-level only.
- **Background daemon.** No auto-save. No login restore. Explicit commands only.
- **Dynamic plugins.** No runtime-loaded modules. App-specific logic is compiled in (Phase 7+) or handled by external scripts.
- **Fuzzy matching.** Match rules are boolean. If you want "find the best match," write a more specific rule.
- **Floating window geometry.** Niri doesn't expose precise floating coordinates via IPC. We track floating state but not position.
- **Cross-monitor workspace migration.** Moving workspaces between monitors during load is supported, but not automatic "my monitor config changed, redistribute everything."
- **Profile inheritance/templates.** v1 profiles are fully self-contained. Templates are a v2+ concern.

---

## Design invariants

1. **The planner is pure.** No I/O, no async, no global state. Given the same inputs, it produces the same plan.
2. **Operations are typed and exhaustive.** Every action nirip can take is an `OpKind` variant. The executor handles all of them.
3. **Matching is deterministic.** Same rule + same window → same result. No randomness, no ambient state.
4. **Load is idempotent.** Running `nirip load` when the desktop already matches the profile produces zero operations.
5. **Freeze is pure.** Same Niri state → same profile output.
6. **State file is advisory.** The source of truth is always Niri IPC + profile config. State file is an optimization hint.
7. **Focus-sensitive operations verify.** The executor never assumes focus landed correctly — it checks.
8. **No implicit destructive actions.** Windows are never closed unless `close_extra = true` or `nirip close` is explicitly invoked.

---

## Key differences from the Python concept

| Aspect | Python concept | Nim concept |
|---|---|---|
| Language | Python + Pydantic + SQLModel | Nim + toml-serialization + results |
| Config format | YAML | TOML (or directory of TOMLs) |
| Binary | Script + venv | Single static binary |
| Matching | Score-based float accumulation | Boolean rule composition |
| State persistence | SQLite database | Simple JSON file |
| Plugin model | Protocol class + dynamic import | Compiled-in modules (later phases) |
| Niri client | Custom async Python | Shared `niri-ipc-nim` library with sidebard |
| Planner | Class with methods | Pure function |
| Executor | Async reconciler class | Async loop with event confirmation |
| Testing | Pytest + Pydantic fixtures | Nim unittest + typed fixtures |
| Packaging | pip/pipx | Nix + nimble |

---

## Nix integration

### Package

```nix
{ lib, nimPackages, niri-ipc-nim }:

nimPackages.buildNimPackage {
  pname = "nirip";
  version = "0.1.0";
  src = ./.;
  propagatedNimDeps = [ niri-ipc-nim ];
}
```

### Home Manager module

```nix
{ config, lib, pkgs, ... }:

let cfg = config.my.desktop.nirip;
in {
  options.my.desktop.nirip = {
    enable = lib.mkEnableOption "nirip workspace profiles";
    profiles = lib.mkOption {
      type = lib.types.attrsOf profileType;
      default = {};
      description = "Declarative workspace profiles";
    };
  };

  config = lib.mkIf cfg.enable {
    # Generate TOML profile files
    xdg.configFile = lib.concatMapAttrs (name: profile:
      let dir = "nirip/profiles/${name}";
      in {
        "${dir}/profile.toml".text = toTOML (profileMeta profile);
      } // lib.mapAttrs' (wsName: ws:
        lib.nameValuePair "${dir}/${wsName}.toml" {
          text = toTOML (workspaceToToml ws);
        }
      ) profile.workspaces
    ) cfg.profiles;

    home.packages = [ pkgs.nirip ];
  };
}
```

This means profiles declared in Nix are generated as TOML files at build time. Nirip reads them at runtime, same as hand-written profiles.

---

## Relationship to sidebard

Summarized from the integration analysis:

- **Shared:** `niri-ipc-nim` library (types, client, event stream)
- **sidebard → nirip:** Commands invoke `nirip load/close` via shell or typed action
- **nirip → sidebard:** Optional RPC query for sidebar ownership (skip those windows)
- **Independent:** Each has its own event loop, state, and lifecycle
- **Philosophy:** sidebard is always-on reactive brain; nirip is on-demand workspace sculptor
