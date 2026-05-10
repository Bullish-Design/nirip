# CONCEPT: tmuxp-style Session Profiles for Niri

**Name:** `nirip`
**Date:** 2026-04-25 (revised)
**Status:** Revised concept — ready for implementation
**Primary goal:** A declarative, project-oriented session orchestrator for the Niri compositor, inspired by tmuxp.

---

## 1. Executive summary

This project is feasible today.

The best framing is not “desktop session restore” in the traditional X11 sense and not “save every app exactly as it was.” The stronger framing is:

> A tmuxp-style declarative orchestration library for Niri workspaces, columns, windows, launch commands, and optional app-specific state plugins.

That framing fits Niri well because Niri already exposes the important compositor-level primitives through IPC: workspaces, windows, outputs, focused window/output, actions, and an event stream. Niri windows expose useful matching and layout metadata such as `id`, `title`, `app_id`, `pid`, `workspace_id`, floating/focused flags, and layout data. The layout data includes a tiled window’s position in the scrolling layout as `(column index, tile index in column)`, which is the key primitive needed for a “freeze current layout” operation.

The core library should intentionally **not** own application-internal state. It should treat application-internal state as an optional plugin concern. That means the core can reliably restore things like:

- Which commands/apps should be started.
- Which named workspaces should exist.
- Which output each workspace should live on.
- Which windows belong to which workspace.
- Which windows belong to which column.
- Column order.
- Window order inside a column.
- Column width or approximate width.
- Window height or approximate height.
- Floating vs tiled state where supported.
- Focus targets.
- Optional metadata for plugins to restore deeper app state.

It should not promise to restore:

- Unsaved editor buffers.
- Browser tab state unless a browser plugin handles it.
- Shell history or foreground processes in terminals.
- Arbitrary runtime memory state.
- Pixel-perfect layout across monitor scale/output changes.
- Perfect ordering when applications open slowly, open extra helper windows, or mutate their own titles late.

The product opportunity is real because existing tools already prove demand, but there is still room for a more tmuxp-like, declarative, library-first design. Existing Niri session tools include `nirinit`, which auto-saves and restores window layout, workspace names, indices, outputs, and window sizes, and supports `app_id` to launch-command mappings and skip lists. The `awesome-niri` index also lists `niri-session-manager` and `nirinit` under session management. This concept should differentiate by focusing on **project profiles**, **explicit load/freeze workflows**, **typed config**, **dry-run/diff**, and **plugins** rather than only automatic login restore.

---

## 2. Background and analogy to tmuxp

`tmuxp` is a tmux session manager that can load, freeze, and convert tmux sessions using YAML/JSON configuration files. Its mental model is simple: users define repeatable terminal workspaces as files, then load them on demand.

A Niri equivalent cannot map 1:1 because the underlying substrate is different:

| tmuxp concept | Niri equivalent |
|---|---|
| tmux server | running Niri compositor |
| tmux session | named Niri project/profile |
| tmux window | Niri workspace, or possibly workspace group |
| tmux pane | Niri window/tile |
| pane layout | Niri columns and tile positions |
| shell command | app launch command |
| freeze | snapshot Niri IPC state into profile config |
| load | reconcile current Niri state against profile config |

The right design is not “tmux inside Niri.” It is “tmuxp’s workflow, applied to Niri’s model.”

A minimal example might look like this:

```yaml
version: 1
name: backend-dev

workspaces:
  - name: backend:code
    output: DP-1
    columns:
      - width: 0.62
        windows:
          - id: editor
            command: code ~/src/backend
            match:
              app_id: code
              title_regex: "backend"
      - width: 0.38
        windows:
          - id: shell
            command: ghostty --working-directory ~/src/backend
            match:
              app_id: com.mitchellh.ghostty

  - name: backend:web
    output: DP-1
    columns:
      - windows:
          - id: browser
            command: google-chrome-stable --new-window http://localhost:3000
            match:
              app_id_regex: "(?i)chrome|chromium"
            plugins:
              chrome:
                profile: Default
                urls:
                  - http://localhost:3000
                  - http://localhost:8000/docs
```

The user-facing promise is:

```text
nirip load backend-dev.yaml
nirip freeze backend-dev > backend-dev.yaml
nirip diff backend-dev.yaml
nirip doctor backend-dev.yaml
```

---

## 3. Current Niri capability surface

### 3.1 IPC access

Niri exposes an IPC socket through `$NIRI_SOCKET`. A client can connect to that UNIX socket, write one JSON request per line, and read one JSON reply per line. `niri msg --json` is a thin wrapper around that socket interface.

This matters because a library does not need to shell out to `niri msg` for every operation. It can implement a proper IPC client, keep sockets open, and separate command/control traffic from event streaming.

Niri’s JSON output is the appropriate target for scripts and tooling. The project documents that JSON output should remain stable in the sense that existing fields and enum variants should not be renamed and non-optional existing fields should not be removed, while new fields and variants may be added. The Rust `niri-ipc` crate itself follows the Niri version and is not semver-stable, so non-Rust clients should deserialize defensively and tolerate unknown fields.

### 3.2 Requests and actions

The `niri-ipc` crate documents request variants including:

- `Version`
- `Outputs`
- `Workspaces`
- `Windows`
- `FocusedOutput`
- `FocusedWindow`
- `Action`
- `EventStream`
- `OverviewState`
- `Casts`

The action surface is broad and includes the primitives needed for this project:

- `Spawn` and `SpawnSh`
- `FocusWindow`
- `FocusColumn`
- `FocusWorkspace`
- `FocusMonitor`
- `MoveWindowToWorkspace`
- `MoveColumnToWorkspace`
- `MoveWorkspaceToIndex`
- `MoveWorkspaceToMonitor`
- `SetWorkspaceName`
- `SetColumnWidth`
- `SetWindowHeight`
- `MoveColumnToIndex`
- `ConsumeWindowIntoColumn`
- `ExpelWindowFromColumn`
- `SetColumnDisplay`
- `ToggleColumnTabbedDisplay`
- `MoveWindowToFloating`
- `MoveWindowToTiling`

This is enough to build a reconciler that can launch windows, wait for them, move them to workspaces, group them into columns, move columns, resize columns/windows, and set focus.

### 3.3 Window metadata

Niri windows expose:

- `id`
- `title`
- `app_id`
- `pid`
- `workspace_id`
- `is_focused`
- `is_floating`
- `is_urgent`
- `layout`
- `focus_timestamp`

The `id` is stable only while the window is open and should not be treated as a durable cross-session identity. For durable matching, the profile should use app IDs, title patterns, launch command identity, process lineage where available, and optional plugin-provided fingerprints.

The most valuable layout field is `layout.pos_in_scrolling_layout`, which gives `(column index, tile index in column)` for tiled windows. The indices are 1-based. That makes freeze/load practical because the library can infer columns and window order from live Niri state.

### 3.4 Workspace metadata

Niri workspaces expose:

- `id`
- `idx`
- `name`
- `output`
- `is_urgent`
- `is_active`
- `is_focused`
- `active_window_id`

The important detail is that `id` is the stable identifier while a workspace exists, whereas `idx` is the current position of the workspace on its monitor. `idx` can change when workspaces are reordered, and workspaces on different monitors can share the same index. Therefore, project profiles should prefer **workspace names** over indices as durable references.

### 3.5 Dynamic workspace model

Niri has dynamic workspaces per monitor. Empty middle workspaces disappear when switched away, and each monitor has an empty workspace at the end. Named workspaces are the practical way to create durable project anchors.

For this library, that means:

- **Every managed workspace must have a name.** This is enforced by the profile schema (workspace `name` is required).
- Freeze emits only named workspaces by default. Anonymous workspaces are skipped unless `--include-anonymous` is passed, in which case stable names are generated (e.g., `unnamed-1`, `unnamed-2`).
- Workspace indices are treated as ordering hints, not identity.

### 3.6 Event stream

Niri’s event stream gives the complete current state up front and then streams updates. This is a better foundation for a long-running daemon or reliable loader than repeated polling.

One important implementation detail: once a connection requests `EventStream`, Niri stops reading further requests on that connection and continuously writes events. Therefore, a robust implementation should use **two sockets**:

1. A read-only event stream socket.
2. A command socket for actions and one-shot requests.

Niri also documents that separate requests are processed one by one and time passes between requests. For example, `Workspaces` and `Windows` requests sent together may not describe a perfectly consistent moment if a window opens between them. The event stream mitigates this by giving a stateful feed, but even event updates are not guaranteed to be atomic in every case. The library should model Niri state as eventually consistent and reconcile with retries.

---

## 4. Product definition

### 4.1 One-sentence product

A typed Python library and CLI for loading, freezing, diffing, and reconciling declarative Niri project profiles.

### 4.2 Target users

- Niri users who frequently start the same project layouts.
- Developers who want one command to open editor, terminals, browser, docs, logs, dashboards, and chat windows in predictable workspaces.
- Users migrating from i3/Sway/tmux workflows who want declarative desktop setup without fighting Niri’s dynamic workspace model.
- Power users who want to version-control graphical workspace layouts.
- Tool authors who want a library layer over Niri IPC.

### 4.3 Core promises

The core should promise:

1. **Repeatable project launch.** Given a config file, create/focus workspaces, spawn apps, and arrange windows.
2. **Best-effort layout restore.** Restore workspace, output, column, tile order, and approximate sizes.
3. **Explicit freeze.** Convert current Niri layout into a portable profile file.
4. **Safe reconciliation.** Avoid closing or moving unrelated windows unless explicitly requested.
5. **Transparent failures.** Explain which windows failed to match, which apps failed to launch, and which layout operations could not be applied.
6. **Extensibility.** Let plugins add app-specific state capture/restore without polluting the core.

### 4.4 Non-goals

The core should not promise:

- Application-internal state restore.
- Arbitrary browser tab recovery.
- Terminal process/session recovery.
- Bit-for-bit desktop restore.
- Compositor-independent behavior.
- Replacement for Niri config.
- Background daemon as the only workflow.

A daemon can exist, but the main UX should be deterministic, explicit, and file-based.

---

## 5. Recommended project shape

### 5.1 Package layout

```text
src/nirip/
  __init__.py
  cli.py
  errors.py
  ipc/
    client.py
    models.py
    requests.py
    events.py
  config/
    models.py
    loader.py
    freezer.py
    validator.py
  engine/
    snapshot.py
    planner.py
    reconciler.py
    matcher.py
    layout.py
    launcher.py
    diagnostics.py
    operations.py
tests/
  unit/
  integration/
  fixtures/
  conftest.py
  fake_niri.py
```

Notes on layout:
- Test infrastructure (`fake_niri.py`, fixtures) lives in `tests/`, not inside the package.
- `plugins/` and `state/` modules are deferred to Phase 2.
- `errors.py` defines the error taxonomy used across all modules.

### 5.2 CLI shape

MVP commands:

```text
nirip load <profile.yaml>
nirip load --dry-run <profile.yaml>    # alias for plan
nirip freeze [--workspace NAME ...] [--all] [--format yaml]
nirip plan <profile.yaml>
nirip doctor <profile.yaml>
```

Deferred to Phase 2+:

```text
nirip diff <profile.yaml>
nirip list
nirip close <profile-name>
nirip watch <profile.yaml>
nirip plugin list
nirip plugin doctor chrome
```

The most important distinction:

- `plan` (and `load --dry-run`) prints intended operations without applying them.
- `load` applies the plan.
- `freeze` serializes current state.

**CLI framework: `click`.** Chosen for maturity, composable command groups, and broad ecosystem support. The CLI layer is synchronous and calls `asyncio.run()` to enter the async runtime for IPC operations.

### 5.3 Library API

```python
import asyncio
from nirip import NiriClient, Profile, Reconciler

async def main():
    client = NiriClient.from_env()
    profile = Profile.from_file("backend-dev.yaml")

    plan = await Reconciler(client).plan(profile)
    print(plan.summary())

    result = await Reconciler(client).apply(profile)
    print(result.summary())

asyncio.run(main())
```

The library should be first-class, not just a CLI wrapper. This will make it useful for launchers, bars, Niri helper scripts, and user-specific automation.

**Async runtime: `asyncio`.** The IPC client, event stream reader, and reconciler are async. The CLI uses `asyncio.run()` as its entry point. Pydantic models remain synchronous data structures.

---

## 6. Configuration model

### 6.1 Principles

The config should be:

- Declarative.
- Human-readable.
- Diff-friendly.
- Stable across Niri versions.
- Explicit about best-effort behavior.
- Able to represent both hand-written profiles and frozen snapshots.

YAML should be the primary human format. JSON should be supported for tooling.

### 6.2 Top-level schema

```yaml
version: 1
name: backend-dev

metadata:
  description: Backend development layout
  tags: [dev, backend]

options:
  match_existing: true
  launch_missing: true
  move_unmanaged_windows: false
  close_extra_managed_windows: false
  focus_after_load: backend:code/editor
  timeout_seconds: 20

workspaces:
  - name: backend:code
    output: DP-1
    index: 1
    columns: []
```

**Decisions applied:**

- **Workspace names are required.** Anonymous workspaces add complexity without clear MVP value. Named workspaces are Niri's durable anchoring primitive.
- **Output aliases are deferred to Phase 2.** For MVP, use raw output names (e.g., `DP-1`, `eDP-1`). Alias resolution and multi-monitor fallback policies will be designed in Phase 2 with real multi-monitor testing.
- **`focus_after_load` path syntax:** `workspace_name/window_id`. To focus a workspace without a specific window, use `workspace_name` alone. Column-level focus paths are not supported in MVP.

### 6.3 Workspace schema

```yaml
workspaces:
  - name: backend:code
    output: primary
    index: 1
    focus: editor
    columns:
      - id: main
        width: 0.62
        display: normal
        windows: []
      - id: tools
        width: 0.38
        display: tabbed
        windows: []
```

Fields:

| Field | Meaning |
|---|---|
| `name` | Durable Niri workspace name. **Required.** |
| `output` | Output name or output alias. |
| `index` | Desired position on the output. Ordering hint, not identity. |
| `focus` | Window ID, column ID, or path to focus after load. |
| `columns` | Ordered list of column specs. |
| `rules` | Workspace-level matching/launch defaults. |

### 6.4 Column schema

```yaml
columns:
  - id: editor-stack
    width: 0.65
    display: normal
    windows:
      - id: editor
        command: code ~/src/backend
        match:
          app_id: code
          title_regex: "backend"
      - id: tests
        command: ghostty --working-directory ~/src/backend -e pytest -f
        match:
          app_id: com.mitchellh.ghostty
          title_regex: "pytest|backend"
```

Fields:

| Field | Meaning |
|---|---|
| `id` | Profile-local column identity. |
| `width` | Proportion or logical pixels. |
| `display` | `normal` or `tabbed`, mapped to Niri column display actions where possible. |
| `windows` | Ordered list of windows in the column. |

### 6.5 Window schema

```yaml
windows:
  - id: browser
    command:
      - google-chrome-stable
      - --new-window
      - http://localhost:3000
    cwd: ~/src/backend
    env:
      ENVIRONMENT: dev
    match:
      app_id_regex: "(?i)chrome|chromium"
      title_regex: "localhost:3000|Backend"
      pid_from_spawn: true
    layout:
      height: 1.0
      floating: false
    plugins:
      chrome:
        profile: Default
        urls:
          - http://localhost:3000
          - http://localhost:8000/docs
```

Fields:

| Field | Meaning |
|---|---|
| `id` | Stable identity inside the profile. |
| `command` | String or argv list to launch if missing. |
| `cwd` | Working directory for command execution. |
| `env` | Extra environment variables. |
| `match` | Rules for identifying the window after launch or in current state. |
| `layout` | Height, floating/tiled, focus hints. |
| `plugins` | Optional app-specific state. |

### 6.6 Matching schema

```yaml
match:
  app_id: com.mitchellh.ghostty
  app_id_regex: "(?i)ghostty|alacritty"
  title: "backend"
  title_regex: "backend|pytest"
  pid_from_spawn: true
  workspace: backend:code
  score_threshold: 0.75
```

Matching should be score-based, not purely boolean. A robust matcher can combine:

- App ID exact match.
- App ID regex match.
- Title exact/regex match.
- Workspace membership.
- PID from launch.
- Child/descendant process relationship where possible.
- Plugin-provided fingerprint.
- Recency: newly opened windows after launch are more likely candidates.
- Negative rules: `not_title_regex`, `not_app_id_regex`, etc.

### 6.7 Pydantic model sketch

```python
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ColumnDisplay(str, Enum):
    normal = "normal"
    tabbed = "tabbed"


class MatchSpec(BaseModel):
    app_id: str | None = None
    app_id_regex: str | None = None
    title: str | None = None
    title_regex: str | None = None
    pid_from_spawn: bool = True
    workspace: str | None = None
    count: int = 1
    score_threshold: float = 0.75


class LayoutSpec(BaseModel):
    height: float | int | None = None
    floating: bool | None = None
    focus: bool = False


class WindowSpec(BaseModel):
    id: str
    command: str | list[str] | None = None
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)
    match: MatchSpec = Field(default_factory=MatchSpec)
    layout: LayoutSpec = Field(default_factory=LayoutSpec)


class ColumnSpec(BaseModel):
    id: str | None = None
    width: float | int | None = None
    display: ColumnDisplay = ColumnDisplay.normal
    windows: list[WindowSpec] = Field(default_factory=list)


class WorkspaceSpec(BaseModel):
    name: str  # Required. Named workspaces are Niri's durable anchor.
    output: str | None = None  # Raw output name (e.g., "DP-1"). Aliases deferred to Phase 2.
    index: int | None = None
    focus: str | None = None
    columns: list[ColumnSpec] = Field(default_factory=list)


class ProfileOptions(BaseModel):
    match_existing: bool = True
    launch_missing: bool = True
    move_unmanaged_windows: bool = False
    close_extra_managed_windows: bool = False
    focus_after_load: str | None = None  # Path syntax: "workspace_name/window_id" or "workspace_name"
    timeout_seconds: float = 20.0


class Profile(BaseModel):
    version: Literal[1] = 1
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    options: ProfileOptions = Field(default_factory=ProfileOptions)
    workspaces: list[WorkspaceSpec]
```

**Changes from initial concept:**

- `plugins` field removed from `WindowSpec` — plugin schema deferred to Phase 2.
- `match.count` field added — declares how many windows are expected for this match rule (e.g., two Ghostty terminals). Default: 1.
- `WorkspaceSpec.name` is required (not optional).
- `WorkspaceSpec.output` uses raw output names, not aliases.
- `ProfileOptions.focus_after_load` is typed and documented.

---

## 7. Runtime state model

The library can operate statelessly, but a small state database improves matching and freeze/load quality.

Recommended storage:

```text
$XDG_STATE_HOME/niri-profiles/state.db
$XDG_STATE_HOME/niri-profiles/logs/
$XDG_CONFIG_HOME/niri-profiles/profiles/
```

Because this is a Python-oriented concept, a SQLite database using SQLModel would fit well.

### 7.1 Stored entities

```python
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ManagedWindow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_name: str = Field(index=True)
    profile_window_id: str = Field(index=True)
    last_niri_window_id: int | None = Field(default=None, index=True)
    last_app_id: str | None = None
    last_title: str | None = None
    last_pid: int | None = None
    last_workspace_name: str | None = None
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)


class ProfileRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_name: str = Field(index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    status: str
    summary_json: str
```

This database should be an optimization, not a source of truth. The source of truth is always the profile plus current Niri IPC state.

---

## 8. Core architecture

### 8.1 Component overview

```text
Profile YAML/JSON
      │
      ▼
Config loader ──► Validator ──► Planner ──► Reconciler ──► Niri IPC client
                      ▲              │             │
                      │              │             ▼
                 Plugin registry     │        Event stream state
                                      ▼
                              Operation plan
```

### 8.2 IPC client

Responsibilities:

- Read `$NIRI_SOCKET`.
- Connect to the UNIX socket.
- Send JSON requests.
- Parse `Ok`/`Err` replies.
- Provide typed helpers for common actions.
- Run a separate event stream connection.
- Tolerate unknown fields.
- Surface Niri errors with actionable context.

High-level interface (asyncio-based):

```python
from collections.abc import AsyncIterator

class NiriClient:
    async def version(self) -> str: ...
    async def outputs(self) -> list[NiriOutput]: ...
    async def workspaces(self) -> list[NiriWorkspace]: ...
    async def windows(self) -> list[NiriWindow]: ...
    async def focused_window(self) -> NiriWindow | None: ...
    async def action(self, action: dict) -> None: ...
    async def events(self) -> AsyncIterator[NiriEvent]: ...
```

All IPC models should include a `raw: dict[str, Any]` field to preserve unknown fields from Niri's JSON responses. This supports forward compatibility and debugging without requiring model updates for every Niri release.

### 8.3 Snapshot/state store

Responsibilities:

- Maintain current windows by Niri ID.
- Maintain current workspaces by Niri ID and by name.
- Maintain output state.
- Join windows to workspaces.
- Derive columns from `layout.pos_in_scrolling_layout`.
- Expose stable query helpers.

Derived layout example:

```python
class DerivedWorkspaceLayout(BaseModel):
    workspace: NiriWorkspace
    columns: list[DerivedColumn]


class DerivedColumn(BaseModel):
    index: int
    windows: list[NiriWindow]
    width: float | None
```

### 8.4 Planner

The planner computes the gap between the desired profile and current state. It produces an ordered operation list, not side effects.

Example operation types:

```python
class EnsureWorkspace(Operation): ...
class MoveWorkspaceToOutput(Operation): ...
class MoveWorkspaceToIndex(Operation): ...
class LaunchWindow(Operation): ...
class WaitForWindow(Operation): ...
class MoveWindowToWorkspace(Operation): ...
class MoveWindowToTiling(Operation): ...
class MoveWindowToFloating(Operation): ...
class FocusWindow(Operation): ...
class ConsumeWindowIntoColumn(Operation): ...
class MoveColumnToIndex(Operation): ...
class SetColumnWidth(Operation): ...
class SetWindowHeight(Operation): ...
class SetColumnDisplay(Operation): ...
class PluginPrepare(Operation): ...
class PluginCapture(Operation): ...
class PluginPostRestore(Operation): ...
```

### 8.5 Reconciler

The reconciler applies the plan. It must be careful because Niri state can change between actions.

Recommended behavior:

1. Apply one action.
2. Wait for an event-stream update or perform a bounded refresh.
3. Re-evaluate the local target state.
4. Continue or replan if state diverged.

Avoid long blind sequences like:

```text
focus window A
move window down
move window down
consume into column
```

State may change between actions. Prefer operations that address windows by ID when available, and re-check focus before focus-sensitive operations.

### 8.6 Launcher

The launcher should support both Niri `Spawn`/`SpawnSh` and direct subprocess launch.

Tradeoff:

| Launch mode | Pros | Cons |
|---|---|---|
| Niri `Spawn` | Compositor-native, matches Niri config expectations | PID tracking may be weaker from the library side |
| Direct subprocess | Better PID/process tracking, custom cwd/env is straightforward | Need to ensure environment is right for Wayland/Niri session |

**Decision: Default to Niri `Spawn` for MVP.**

Niri `Spawn` is the correct default because it ensures the launched process inherits the correct Wayland/Niri session environment without the library needing to replicate that setup. Direct subprocess launch will be added as an opt-in `launch_mode: subprocess` option in Phase 2 for cases where `cwd` or `env` control is essential.

For MVP, `cwd` and `env` fields in the window spec are passed through Niri's `SpawnSh` where possible (wrapping the command in a shell with `cd` and `export` prefixes). Record launch timestamp for match-scoring; PID tracking from Niri `Spawn` is best-effort.

Example:

```yaml
windows:
  - id: logs
    command: ghostty --working-directory ~/src/backend -e journalctl -f
    # launch_mode defaults to "spawn" (Niri Spawn/SpawnSh)
```

### 8.7 Matcher

The matcher should be one of the most carefully designed components.

Suggested scoring:

| Signal | Example score |
|---|---:|
| PID exactly matches launched process | +0.40 |
| PID is descendant of launched process (best-effort) | +0.30 |
| `app_id` exact match | +0.30 |
| `app_id_regex` match | +0.20 |
| `title` exact match | +0.20 |
| `title_regex` match | +0.15 |
| expected workspace match | +0.10 |
| opened after launch timestamp | +0.10 |
| plugin fingerprint match | +0.40 |
| negative regex match | reject |

The matcher should return explanations:

```text
browser matched window 47 with score 0.83:
  + app_id_regex matched "Google-chrome"
  + title_regex matched "localhost:3000"
  + opened after launch
  - pid unavailable
```

This makes debugging tolerable.

**Note on PID/process lineage matching:** Process tree inspection requires reading `/proc` and may not work reliably for Flatpak apps, sandboxed processes, or applications that fork and exec. PID-based scoring signals are always best-effort with a graceful fallback (the signal is simply not contributed if PID data is unavailable).

---

## 9. Layout restoration strategy

### 9.1 Desired layout abstraction

Niri’s core layout abstraction is not a fixed grid. It is a horizontally scrolling set of columns, each of which may contain one or more tiled windows.

The profile should model that directly:

```text
workspace
  column 1
    tile 1
    tile 2
  column 2
    tile 1
  column 3
    tile 1
    tile 2
    tile 3
```

Do not force an i3/Sway tree model onto Niri.

### 9.2 Freeze algorithm

A reasonable `freeze` algorithm:

1. Build a current-state snapshot from the event stream or `Workspaces` + `Windows` fallback.
2. Select workspaces:
   - named workspaces by default;
   - optionally all non-empty workspaces with generated names.
3. For each workspace:
   - group tiled windows by `layout.pos_in_scrolling_layout[0]`;
   - sort windows inside each column by `layout.pos_in_scrolling_layout[1]`;
   - capture tile/window sizes;
   - capture floating windows separately.
4. Generate `match` sections from `app_id` and current `title`.
5. Generate `command` only if known from user mappings, plugins, process inspection, or prior state DB.
6. Include comments or diagnostics for unknown launch commands.

Frozen profile example:

```yaml
version: 1
name: frozen-2026-04-25

workspaces:
  - name: backend:code
    output: DP-1
    index: 1
    columns:
      - id: col-1
        width: 1182
        windows:
          - id: win-1
            command: null
            match:
              app_id: code
              title_regex: "backend"
            freeze:
              niri_window_id: 18
              captured_title: "backend - Visual Studio Code"
      - id: col-2
        width: 720
        windows:
          - id: win-2
            command: ghostty
            match:
              app_id: com.mitchellh.ghostty
```

### 9.3 Load algorithm

A reasonable `load` algorithm:

1. Parse and validate the profile.
2. Start event stream state.
3. Ensure target outputs exist or resolve aliases/fallbacks.
4. Ensure named workspaces exist.
5. Move workspaces to requested outputs and approximate indices.
6. Match existing windows if `match_existing` is true.
7. Launch missing windows if `launch_missing` is true.
8. Wait for windows with bounded timeout.
9. Move matched windows to target workspaces.
10. Convert floating/tiled states as requested.
11. Arrange windows into target columns.
12. Move columns to target indices.
13. Apply column display mode and sizes.
14. Apply window heights where possible.
15. Focus requested workspace/window.
16. Run plugin post-restore hooks.
17. Print a structured summary.

### 9.4 Column construction

Column construction is the hardest part because many Niri actions are focus-sensitive. This section describes the algorithm, failure modes, and fallback strategy.

**Algorithm:**

1. **Phase 1: Placement.** Put every target window on the correct workspace as separate columns (one window per column). Verify each window's `workspace_id` after the move.

2. **Phase 2: Column formation.** For each target column with more than one window:
   a. Focus the first (anchor) window in the column. Verify focus via `FocusedWindow`.
   b. For each subsequent window in the column:
      - Focus the window to be consumed. Verify focus.
      - Use `ConsumeWindowIntoColumn` to merge it into the anchor's column.
      - Re-query the window's `pos_in_scrolling_layout` to verify it now shares the anchor's column index.
      - If verification fails, log the failure and continue with remaining windows (partial column is acceptable).
   c. After all windows are consumed, verify the column's tile count matches expectations.

3. **Phase 3: Column ordering.** Move each formed column to its target index with `MoveColumnToIndex`. Process columns right-to-left (highest target index first) to avoid index shifting during reordering.

4. **Phase 4: Sizing.** Apply `SetColumnWidth` and `SetWindowHeight` after all columns are formed and positioned.

**Failure modes and fallbacks:**

| Failure | Behavior |
|---|---|
| Window refuses to be consumed (dialog, popup) | Log warning, leave window as separate column, continue |
| Focus shifts unexpectedly during consume | Re-focus and retry once; if retry fails, log and skip |
| Target column index shifted due to prior operations | Re-query layout positions and recalculate target indices |
| Two profile columns claim the same ambiguously-matched window | First column wins; second column reports the window as unresolved |
| `pos_in_scrolling_layout` not available (floating window) | Skip column formation for floating windows; they are positioned independently |

**MVP limitation:** Column construction is best-effort. The reconciler will report partial success if some windows could not be grouped into their target columns. This is documented as an explicit limitation, not a silent failure.

**Potential upstream improvement:** An ID-addressed `ConsumeWindowIntoColumn { window_id, target_column_window_id }` action in Niri would eliminate the focus-sensitivity problem entirely. This is tracked as a stretch-goal upstream request, not a blocker.

### 9.5 Size restoration

Niri supports changing focused column width and window height. A profile should allow both proportional and fixed sizes, but the reconciler should treat them as best-effort.

**Size value semantics (canonical rule):**

- Values in the range `(0.0, 1.0]` are **proportions** of the available space.
- Values `> 1.0` are **logical pixels**.
- `null` or omitted means "use Niri default / no preference."
- `1.0` means **proportion 1.0** (full width/height), not 1 pixel.

Shorthand examples:

```yaml
width: 0.62     # proportion: 62% of available width
width: 1180     # logical pixels: 1180px
height: 0.50    # proportion: 50% of available height
height: 400     # logical pixels: 400px
```

The loader normalizes these to the nearest supported Niri `SetColumnWidth` / `SetWindowHeight` action. Size restoration is always best-effort.

---

## 10. Plugin surface (Phase 2)

> **Status: Deferred to Phase 2.** The plugin system is not part of MVP. The `plugins` key is not included in the MVP profile schema. This section documents the conceptual design for future implementation. The plugin API will be designed after the core reconciler is proven, so that hook points reflect actual reconciler behavior rather than assumptions.

### 10.1 Philosophy

Plugins should be optional, explicit, and sandbox-conscious.

Core contract:

> The core restores compositor-level placement. Plugins may enrich launch, match, capture, and post-restore behavior for specific applications.

Do not make the core depend on Chrome, Firefox, qutebrowser, VS Code, terminals, or editor-specific APIs.

### 10.2 Plugin capabilities

A plugin may implement any subset of these hooks:

```python
from typing import Any, Protocol

from pydantic import BaseModel


class CaptureContext(BaseModel): ...
class LaunchContext(BaseModel): ...
class MatchContext(BaseModel): ...
class RestoreContext(BaseModel): ...


class LaunchPlan(BaseModel):
    command: list[str] | None = None
    env: dict[str, str] = {}
    cwd: str | None = None


class MatchContribution(BaseModel):
    score: float
    reason: str


class AppStatePlugin(Protocol):
    name: str

    def validate_config(self, config: dict[str, Any]) -> None: ...

    async def capture(
        self,
        window: dict[str, Any],
        context: CaptureContext,
    ) -> dict[str, Any]: ...

    async def prepare_launch(
        self,
        config: dict[str, Any],
        context: LaunchContext,
    ) -> LaunchPlan | None: ...

    async def match_window(
        self,
        window: dict[str, Any],
        saved_state: dict[str, Any],
        context: MatchContext,
    ) -> MatchContribution | None: ...

    async def post_restore(
        self,
        window_id: int,
        saved_state: dict[str, Any],
        context: RestoreContext,
    ) -> None: ...
```

### 10.3 Plugin lifecycle during load

```text
validate profile
  │
  ├─ plugin.validate_config
  │
build launch plan
  │
  ├─ plugin.prepare_launch
  │
launch/match windows
  │
  ├─ plugin.match_window contributes score
  │
arrange compositor layout
  │
  └─ plugin.post_restore
```

### 10.4 Plugin lifecycle during freeze

```text
snapshot windows
  │
  ├─ core captures app_id/title/pid/layout
  │
  ├─ plugin.capture captures optional internal state
  │
  └─ freezer writes plugin state under window.plugins.<plugin-name>
```

### 10.5 Chrome/Chromium plugin concept

Possible capabilities:

- Launch Chrome with a specific profile directory.
- Open a specific URL set.
- Use Chrome’s native session restore flags where acceptable.
- Optionally use the DevTools Protocol when Chrome is launched with a remote debugging port.
- Capture visible tab URLs and titles if debugging is enabled.
- Match windows based on title/URL fingerprints.

Recommended explicit config:

```yaml
plugins:
  chrome:
    profile: Default
    mode: urls
    urls:
      - http://localhost:3000
      - http://localhost:8000/docs
    remote_debugging:
      enabled: false
      port: 9222
```

Security note: remote debugging is powerful. The plugin should never enable it implicitly. It should require explicit config and document the local security implications.

### 10.6 Firefox plugin concept

Possible capabilities:

- Launch a specific profile.
- Open URLs.
- Capture a coarse URL/title set if an integration is available.
- Use browser-native restore behavior when desired.

Recommended explicit config:

```yaml
plugins:
  firefox:
    profile: dev
    urls:
      - http://localhost:3000
      - http://localhost:8000/docs
```

### 10.7 qutebrowser plugin concept

qutebrowser is likely a strong plugin candidate because it already has session concepts and is scriptable. A plugin could:

- Save a qutebrowser session.
- Load a named qutebrowser session.
- Match windows via temporary title markers or session metadata.
- Coordinate session load with Niri layout restore.

This plugin could become the cleanest proof-of-concept for “app-internal state as optional plugin.”

### 10.8 Terminal plugin concept

Terminals are tricky because shell/process state is not generally recoverable. Keep the terminal plugin modest:

- Launch terminal in a cwd.
- Launch terminal with a command.
- Optionally set title for matching.
- Do not claim to restore running TUI programs.

Example:

```yaml
windows:
  - id: api-shell
    command:
      - ghostty
      - --working-directory
      - ~/src/backend
      - --title
      - api-shell
    match:
      title: api-shell
```

### 10.9 Editor plugin concept

Editors can usually restore project-level state themselves. The core only needs to open the right project/folder.

Possible plugin behavior:

- VS Code: open workspace file or folder.
- Neovide/Neovim GUI: open cwd/session file.
- JetBrains: open project path.

Keep this as launch enrichment and matching, not deep editor state management.

---

## 11. Safety model

A layout orchestrator can be annoying or destructive if it moves/closes the wrong windows. The default behavior should be conservative.

### 11.1 Safe defaults

```yaml
options:
  match_existing: true
  launch_missing: true
  move_unmanaged_windows: false
  close_extra_managed_windows: false
  require_confirmation_for_close: true
  dry_run: false
```

Default load should:

- Move only windows it matched confidently.
- Launch only missing windows with explicit commands.
- Never close windows unless the user passes a flag or config explicitly allows it.
- Never move windows with low match confidence.
- Print unresolved matches.

### 11.2 Dangerous operations

These should require explicit opt-in:

- Closing extra windows.
- Moving unmatched windows out of the way.
- Renaming existing workspaces that do not look managed.
- Enabling browser remote debugging.
- Running plugin commands from untrusted profile files.

### 11.3 Trust boundary

A profile file can run arbitrary commands. Treat profiles like shell scripts.

Suggested CLI warning:

```text
This profile contains launch commands and plugin hooks. Review it before loading if it came from someone else.
```

### 11.4 Error taxonomy

All errors across the library use a structured hierarchy defined in `errors.py`. Each error category maps to distinct user-facing messaging:

| Category | Examples | User message style |
|---|---|---|
| `IpcError` | Connection refused, timeout, malformed response, socket not found | "Cannot connect to Niri: ..." with remediation |
| `ConfigError` | Schema validation, semantic validation (duplicate IDs, invalid regex) | "Profile validation failed: ..." with line/field reference |
| `MatchError` | No candidates found, ambiguous candidates, all below threshold | "Window 'X' not matched: ..." with candidate scores |
| `ReconcileError` | Action failed, state drift, window disappeared during operation | "Failed to apply operation: ..." with context and retry status |
| `LaunchError` | Command not found, process exited immediately, timeout waiting for window | "Failed to launch 'X': ..." with command and exit info |
| `FreezeError` | Cannot snapshot (no Niri connection, empty workspace set) | "Cannot freeze: ..." with environment check hints |

Each error carries:
- A human-readable message with actionable next steps.
- A machine-readable error code for programmatic handling.
- Optional context (window ID, workspace name, candidate list, etc.).

---

### 11.5 Dependencies

MVP runtime dependencies:

| Package | Purpose |
|---|---|
| `pydantic >= 2.12` | Profile schema models, IPC response parsing, validation |
| `click >= 8.0` | CLI framework |
| `pyyaml >= 6.0` | YAML profile loading |

Dev dependencies (already in `pyproject.toml`):

| Package | Purpose |
|---|---|
| `pytest >= 7.0` | Test framework |
| `pytest-cov >= 4.1` | Coverage reporting |
| `pytest-asyncio >= 0.23` | Async test support |
| `mypy >= 1.10` | Static type checking |
| `ruff >= 0.5.0` | Linting and formatting |

Deferred dependencies (Phase 2+):

| Package | Purpose |
|---|---|
| `ruamel.yaml` | Roundtrip YAML preservation for freeze (replace PyYAML if needed) |
| `sqlmodel` / `sqlalchemy` | State database |
| `rich` | Enhanced CLI output formatting |

**Note:** `asyncio` is stdlib and requires no additional dependency. No third-party async framework is needed for MVP.

---

## 12. Diagnostics and UX

Diagnostics will make or break this project.

### 12.1 `plan`

Example output:

```text
Profile: backend-dev

Will create/focus workspaces:
  ✓ backend:code on DP-1
  ✓ backend:web on DP-1

Will launch missing windows:
  + editor: code ~/src/backend
  + browser: google-chrome-stable --new-window http://localhost:3000

Will move existing windows:
  ~ api-shell: window 42 -> backend:code column tools

Will not touch:
  - Slack window 17, not managed by this profile
```

### 12.2 `diff`

Example output:

```text
backend:code
  editor       OK       workspace, column, size match
  api-shell    DRIFT    expected column 2, actual column 3
  tests        MISSING  no matching window found

backend:web
  browser      OK       matched by app_id_regex + title_regex
```

### 12.3 `doctor`

Checks:

- `$NIRI_SOCKET` exists.
- Niri version can be read.
- Required outputs are present or aliases resolve.
- Workspace names are unique.
- Window IDs are unique inside profile.
- Every window has either `command`, `match`, or plugin launch data.
- Regexes compile.
- Plugin configs validate.
- Risky options are flagged.

### 12.4 Failure explanations

Bad:

```text
failed to restore browser
```

Good:

```text
browser: no matching window reached score >= 0.75 within 20s
  candidate window 51 score 0.50: app_id matched, title did not match
  candidate window 52 score 0.35: title matched, app_id did not match
  next steps: loosen match.title_regex or set command to launch a fresh window
```

---

## 13. MVP proposal

### 13.1 MVP scope

The MVP should avoid daemon complexity and plugins at first.

MVP commands:

```text
nirip load <profile.yaml>
nirip freeze --all > profile.yaml
nirip plan <profile.yaml>
nirip doctor <profile.yaml>
```

MVP features:

- YAML config.
- Pydantic validation.
- Niri socket client.
- Windows/workspaces snapshots.
- Named workspace targeting.
- App launch.
- Existing window matching by `app_id` and title regex.
- Move windows to workspaces.
- Basic column grouping.
- Basic column ordering.
- Best-effort column width.
- Freeze named workspaces.
- Human-readable diagnostics.

Out of MVP:

- Browser plugins.
- Daemon/autosave.
- Close/kill profile.
- Complex monitor fallback logic.
- Floating geometry precision.
- Import/export from other tools.

### 13.2 MVP success criteria

The MVP succeeds if it can reliably handle:

```yaml
version: 1
name: simple-dev
workspaces:
  - name: simple:code
    columns:
      - windows:
          - id: editor
            command: code ~/src/project
            match:
              app_id: code
              title_regex: project
      - windows:
          - id: terminal
            command: ghostty --working-directory ~/src/project
            match:
              app_id_regex: ghostty
  - name: simple:web
    columns:
      - windows:
          - id: browser
            command: firefox http://localhost:3000
            match:
              app_id_regex: firefox
              title_regex: localhost
```

And can:

1. Load it from a clean Niri session.
2. Load it again without duplicating windows unnecessarily.
3. Freeze it back into a similar config.
4. Explain unresolved windows.

### 13.3 Phase 2

- Event-stream-backed state store.
- Better replanning after each action.
- Output aliases and fallback policies.
- Local state DB.
- Plugin API skeleton.
- Chrome/qutebrowser proof-of-concept plugin.
- `diff` command.

### 13.4 Phase 3

- Daemon/watch mode.
- Autosave profiles.
- Profile close/unload semantics.
- TUI picker.
- Fuzzy profile launcher integration.
- Declarative keybindings snippets for Niri config.
- Import from `nirinit` session JSON if feasible.
- Export to user-friendly docs/examples.

---

## 14. Key risks and mitigations

### 14.1 Window matching ambiguity

Risk: multiple windows share the same app ID/title.

Mitigations:

- Score-based matching.
- User-provided title markers.
- PID tracking for launched commands.
- Plugin fingerprints.
- Interactive `doctor` suggestions.
- Require explicit IDs and stronger match rules in profiles.

### 14.2 Focus-sensitive actions

Risk: actions like consuming windows into columns may apply to the wrong focused window if state changes.

Mitigations:

- Prefer ID-addressed actions where available.
- Verify focus before focus-sensitive operations.
- Apply one action at a time.
- Wait for event confirmation.
- Replan after drift.

### 14.3 Dynamic workspace behavior

Risk: unnamed empty workspaces disappear or indices shift.

Mitigations:

- Use named workspaces as anchors.
- Treat indices as ordering hints only.
- Generate names when freezing anonymous workspaces.
- Move workspaces by name when possible.

### 14.4 Application launch nondeterminism

Risk: apps open helper windows, delay main windows, or reuse existing windows.

Mitigations:

- Bounded wait loops.
- Match existing windows before launching.
- Detect newly opened windows after launch timestamp.
- Allow `wait_for` rules.
- Per-app plugins for known odd behavior.

### 14.5 Niri IPC evolution

Risk: new fields or variants appear; Rust crate version changes.

Mitigations:

- Tolerate unknown fields.
- Keep a small compatibility layer.
- Add `nirip doctor` version reporting.
- Test against multiple Niri versions.
- Prefer JSON IPC stability guarantees over tight Rust crate bindings unless writing in Rust.

### 14.6 User trust and destructive actions

Risk: the tool moves/closes important windows.

Mitigations:

- Conservative defaults.
- Dry-run planning.
- No close by default.
- Confidence thresholds.
- Clear summaries before and after apply.

---

## 15. Relationship to emerging Wayland session management

Wayland Protocols 1.48 added XDG Session Management in April 2026, according to contemporary reporting. That is relevant long-term, but it does not make this concept obsolete.

Reasons:

1. This project is Niri-specific and can provide immediate workflow automation using existing Niri IPC.
2. This project is project/profile-oriented, not only logout/login restoration.
3. This project can orchestrate commands and workspaces even for apps that do not implement new session protocols.
4. If Niri later exposes protocol-backed restore data, this library can integrate it as another backend/plugin signal.

Treat future protocol support as an enhancement path, not a dependency.

---

## 16. Existing ecosystem and differentiation

### 16.1 `nirinit`

`nirinit` already targets Niri session management. Its README describes it as a session manager that automatically saves and restores Niri window layout. It includes auto-save, startup restore, preservation of workspace names/indices/outputs/window sizes, `app_id` to launch-command mapping, and skip lists.

Differentiation opportunity:

| Area | `nirinit` style | Proposed library |
|---|---|---|
| Primary UX | automatic session restore | explicit project profiles plus optional daemon |
| Config | app launch mapping / skip config | declarative tmuxp-like workspace files |
| Workflow | restore previous state | load/freeze/diff named project layouts |
| Plugin surface | not primary focus | first-class optional extension point |
| Library API | not the main product | first-class API for other tools |
| Safety | auto-restore oriented | dry-run, diff, diagnostics, conservative reconciliation |

### 16.2 `niri-session-manager`

The `awesome-niri` index lists `niri-session-manager` as a tool that automatically saves and restores windows. That validates the problem space, but a tmuxp-like project can still own the declarative profile niche.

### 16.3 Why not just Niri config?

Niri config is the right place for global rules, keybindings, default column widths, spawn-at-startup commands, and static preferences. This project should not replace it.

This project is better for:

- Per-project layouts.
- Ad hoc session files.
- Freezing current state.
- Loading different workspaces on demand.
- Team-shared development layout templates.
- Plugin-driven app/session integration.

---

## 17. Name

**`nirip`** — short, tmuxp-adjacent, used for both the package and the CLI command.

The Python package is `nirip` (importable as `import nirip`). The CLI binary is `nirip`.

---

## 18. Suggested README positioning

```markdown
# niri-profile

tmuxp-style project profiles for the Niri compositor.

`niri-profile` loads and freezes declarative workspace layouts for Niri:

- named workspaces
- outputs
- columns
- windows
- launch commands
- layout matching
- optional app-state plugins

It restores compositor-level layout. Browser tabs, editor state, and terminal process state are plugin-level concerns, not part of the core guarantee.
```

---

## 19. Implementation notes

### 19.1 JSON request examples

Focus a workspace by name:

```json
{"Action":{"FocusWorkspace":{"reference":{"Name":"backend:code"}}}}
```

Spawn a command:

```json
{"Action":{"Spawn":{"command":["ghostty","--working-directory","/home/me/src/backend"]}}}
```

Move a window to a workspace by name:

```json
{"Action":{"MoveWindowToWorkspace":{"window_id":42,"reference":{"Name":"backend:code"},"focus":false}}}
```

Set workspace name:

```json
{"Action":{"SetWorkspaceName":{"name":"backend:code","workspace":null}}}
```

Actual serialized shapes should be verified against the running Niri version with `niri msg`/`socat` or generated from `niri-ipc` docs/tests.

### 19.2 Testing strategy

Testing should not require a live Niri session for most logic.

Recommended layers:

1. Pure unit tests for config validation.
2. Pure unit tests for matching scores.
3. Pure unit tests for freeze serialization from fixture snapshots.
4. Fake Niri IPC server for request/reply behavior.
5. Fake event stream fixtures.
6. Optional integration tests against nested/windowed Niri.

### 19.3 Fixture snapshot

Use stored Niri JSON snapshots:

```text
tests/fixtures/simple/windows.json
tests/fixtures/simple/workspaces.json
tests/fixtures/simple/events.ndjson
```

### 19.4 Compatibility strategy

- Parse Niri JSON with permissive Pydantic models: ignore unknown fields.
- Keep raw payloads available for debugging.
- Do not assume IDs increment.
- Do not assume optional layout fields are always present.
- Do not assume PID is always available.
- Do not assume workspace index is stable.

---

## 20. Open questions

**Resolved:**

1. ~~Should load prefer Niri `Spawn` or direct subprocess by default?~~ **Resolved: Niri `Spawn` is the default.** See Section 8.6.
2. ~~Can column construction be made robust enough with current focus-sensitive actions?~~ **Resolved: Yes, with best-effort semantics and partial-success reporting.** See Section 9.4. Upstream ID-addressed consume is a stretch-goal, not a blocker.
3. ~~Should profiles require all managed workspaces to be named?~~ **Resolved: Yes.** Workspace `name` is required in the schema.
4. ~~Should freeze include unmanaged windows by default?~~ **Resolved: No.** Freeze emits only named workspaces by default.
5. ~~How should output aliases be resolved when a monitor is disconnected?~~ **Resolved: Deferred to Phase 2.** MVP uses raw output names only.
6. ~~Should plugin hooks run in-process or as subprocesses?~~ **Resolved: Deferred.** Plugin system is Phase 2.

**Still open (Phase 2+):**

7. Should the core support a lockfile to prevent concurrent profile loads?
8. Should app launch commands be inferred from `.desktop` files during freeze?
9. Should the profile support variables/templates?
10. Should there be an interactive resolver for ambiguous matches?

---

## 21. Possible upstream asks for Niri

The project is viable without upstream changes, but a few Niri enhancements could make it better:

1. ID-addressed “consume window into column with target window/column” action.
2. ID-addressed “set column width for column containing window ID” action.
3. A batch/transaction IPC request for actions that should apply against one coherent state.
4. Explicit workspace creation by name/output.
5. A stable “managed by external tool” annotation or tag for windows/workspaces.
6. More structured layout export for full columns, not just per-window positions.

These should be considered stretch goals, not blockers.

---

## 22. Verdict

Build it.

The concept is technically plausible, useful, and well-aligned with Niri’s model if the scope is kept honest. The winning design is a declarative compositor-layout orchestrator with app-internal state delegated to optional plugins.

The key product choices are:

- Prefer named workspaces.
- Treat workspace indices as ordering hints.
- Make matching explainable and score-based.
- Keep load/freeze/diff explicit and deterministic.
- Avoid destructive actions by default.
- Use the event stream for robust state tracking.
- Make plugins optional and explicit.

The first milestone should be a small but reliable MVP that loads and freezes named workspaces with columns and launch commands. Browser/tab support can wait until the core proves reliable.

---

## References

1. tmuxp documentation: “Session manager for tmux. Load, freeze, and convert tmux sessions through YAML/JSON configuration files.”  
   https://tmuxp.git-pull.com/

2. Niri IPC wiki: IPC socket, `niri msg --json`, event stream behavior, programmatic access, and JSON stability notes.  
   https://github.com/niri-wm/niri/wiki/IPC

3. `niri-ipc` crate documentation, version 26.4.0: request processing, event stream socket behavior, and compatibility caveats.  
   https://docs.rs/niri-ipc/latest/niri_ipc/

4. `Request` enum documentation: `Version`, `Outputs`, `Workspaces`, `Windows`, `Action`, `EventStream`, etc.  
   https://docs.rs/niri-ipc/latest/niri_ipc/enum.Request.html

5. `Window` struct documentation: window fields including `id`, `title`, `app_id`, `pid`, `workspace_id`, focus/floating flags, layout, and focus timestamp.  
   https://docs.rs/niri-ipc/latest/niri_ipc/struct.Window.html

6. `WindowLayout` struct documentation: `pos_in_scrolling_layout`, tile/window size, tile position, and 1-based column/tile indices.  
   https://docs.rs/niri-ipc/latest/niri_ipc/struct.WindowLayout.html

7. `Workspace` struct documentation: workspace fields including `id`, `idx`, `name`, `output`, active/focused flags, and active window ID.  
   https://docs.rs/niri-ipc/latest/niri_ipc/struct.Workspace.html

8. `Action` enum documentation: Niri action surface including spawn, focus, move, workspace naming, column/window sizing, and column display actions.  
   https://docs.rs/niri-ipc/latest/niri_ipc/enum.Action.html

9. Niri Workspaces wiki: dynamic workspaces, per-monitor workspace sets, disappearing empty middle workspaces, and named workspaces as permanent references.  
   https://github.com/niri-wm/niri/wiki/Workspaces

10. Niri Design Principles wiki: window opening should not affect existing sizes, focused window should not move unexpectedly, and actions should apply immediately.  
    https://github.com/niri-wm/niri/wiki/Design-Principles

11. `nirinit` README: auto-save/restore features, workspace names/indices/outputs/window sizes, app ID launch mapping, skip lists.  
    https://github.com/amaanq/nirinit

12. `awesome-niri` Session Management section: lists `niri-session-manager`, `nirinit`, and related session tools.  
    https://github.com/niri-wm/awesome-niri/blob/main/README.md

13. Phoronix report on Wayland Protocols 1.48 and XDG Session Management, April 2026.  
    https://www.phoronix.com/news/Wayland-Protocols-1.48
