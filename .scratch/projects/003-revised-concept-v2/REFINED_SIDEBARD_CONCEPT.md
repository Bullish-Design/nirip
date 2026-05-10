# REFINED SIDEBARD CONCEPT

A ground-up rethink of sidebard as an elegant Nim codebase.

---

## The one-sentence version

Sidebard is a **reactive event-reduced daemon** that turns niri compositor events and Kanata keyboard events into a unified shell state, exposed over JSON-RPC with push subscriptions.

---

## Philosophy

### 1. Events in, state out

The entire system is a deterministic function from events to state. Every input — a window opening, a focus change, a key prefix, a config reload — is an event. Every output — the resolved profile, the keymap snapshot, the Kanata layer — is derived from state. No hidden mutation, no spooky action at a distance.

### 2. The domain is pure

The core logic (profile resolution, ownership tracking, keymap trie, config merging) has zero I/O. No sockets, no files, no async. It takes typed inputs and returns typed outputs. This makes it trivially testable, trivially debuggable, and trivially correct.

The reducer is **deterministic and side-effect-free with respect to I/O** — it mutates state in place for performance, but never reaches outside the process boundary.

### 3. I/O lives at the edges

Protocol adapters (niri socket, Kanata TCP, JSON-RPC server, filesystem config) are thin shells around the pure domain. They translate bytes into domain events and domain effects into bytes. Nothing else.

### 4. One binary, two modes

A single `sidebard` binary runs as either:
- **daemon** — long-running, event loop, IPC server
- **CLI** — sends a single RPC request, prints the result, exits

No separate `sidebarctl` binary. The CLI mode connects to the running daemon. If the daemon isn't running, CLI commands that only need config (like `sidebard commands list`) can work offline by loading TOML directly.

### 5. Composition over framework

No plugin "system." No script "runtime." A plugin is a TOML file. An action is a typed command spec. The daemon's job is to maintain state and route events, not to host application logic. Extensibility comes from the IPC surface — any language can be a client.

### 6. Sidebard is the runtime companion to the Nix workspace layer

The boundary between systems is explicit:
- **Nix** owns workspace taxonomy, static configuration, and workspace-per-file generation
- **Niri** owns workspace runtime semantics (tiling, focus, columns)
- **sidebard** consumes runtime context and overlays command/profile/keymap state on top

Sidebard does not replace or duplicate the workspace loader. It reads the world niri exposes and adds a command layer.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   sidebard                      │
│                                                 │
│  ┌───────────┐  ┌───────────┐  ┌─────────────┐  │
│  │ niri      │  │ kanata    │  │ json-rpc    │  │
│  │ adapter   │  │ adapter   │  │ server      │  │
│  └─────┬─────┘  └─────┬─────┘  └──────┬──────┘  │
│        │              │               │         │
│        ▼              ▼               ▼         │
│  ┌────────────────────────────────────────────┐ │
│  │              event loop                    │ │
│  │                                            │ │
│  │ event ──→ reduce(state, event) ──→ effects │ │
│  │                                            │ │
│  └──────────────────┬─────────────────────────┘ │
│                     │                           │
│        ┌────────────┼────────────┐              │
│        ▼            ▼            ▼              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │ store    │ │ keymap   │ │ profiles │         │
│  │ (state)  │ │ (trie)   │ │ (config) │         │
│  └──────────┘ └──────────┘ └──────────┘         │
│       pure domain — no I/O                      │
└─────────────────────────────────────────────────┘
```

### The core loop

```
1. An adapter produces an Event
2. reduce(state, event) computes new State + seq[Effect]
3. The runtime executes each Effect (send kanata command, start timer, notify subscribers)
4. Goto 1
```

The reducer is deterministic. Effects are data — they describe what should happen, not how. The runtime interprets them. This means you can replay a sequence of events and get the exact same state, which makes debugging trivial.

---

## Module structure

```
src/
├── sidebard.nim                 # entry point: daemon or CLI mode
├── sidebard.nimble              # package manifest
│
├── core/                        # pure domain — zero I/O, zero async
│   ├── types.nim                # all domain types (internal)
│   ├── api_types.nim            # public RPC snapshot types (stable contract)
│   ├── config.nim               # TOML → typed config, hierarchical merge
│   ├── state.nim                # ShellState + reduce() + Effect
│   ├── ownership.nim            # window-to-sidebar ownership tracking
│   ├── profile.nim              # profile resolution from context
│   └── keymap.nim               # command trie, prefix tracking, filtering
│
├── adapters/                    # I/O boundary — async, effectful
│   ├── niri.nim                 # niri Unix socket: requests + event stream
│   ├── kanata.nim               # kanata TCP: layer switch + events
│   └── rpc.nim                  # JSON-RPC server (unix socket) + client
│
└── cli.nim                      # CLI subcommands via cligen
```

### Why this split matters

- `core/` can be compiled and tested without any async runtime.
- `adapters/` can be swapped (mock niri, mock kanata) for integration tests.
- `cli.nim` is a thin translation from command-line arguments to RPC calls.
- The entry point (`sidebard.nim`) just wires adapters to the core loop.
- `api_types.nim` defines the stable public contract; internal types can evolve freely.

---

## Type system

All internal types live in `core/types.nim`. Public RPC types live in `core/api_types.nim`.

### Internal types (`core/types.nim`)

```nim
import std/[options, sets, tables, times]
import results

# ─── identifiers ───────────────────────────────────

type
  WindowId*    = distinct uint64
  WorkspaceId* = distinct uint64
  OutputId*    = distinct string   # monitor/output name
  InstanceId*  = distinct string   # "left", "right", "bottom"
  PluginId*    = distinct string   # "chat", "code", "media"
  ProfileId*   = distinct string   # "chat/default", "code/focused"
  CommandId*   = distinct string   # "chat.quick_reply"

# ─── compositor model ──────────────────────────────

type
  NiriWindow* = object
    id*: WindowId
    appId*: Option[string]
    title*: Option[string]
    workspaceId*: Option[WorkspaceId]
    outputId*: Option[OutputId]     # reserved for multi-monitor
    isFocused*: bool
    isFloating*: bool

# ─── sidebar model ─────────────────────────────────

type
  SidebarState* = enum
    Collapsed    ## edge sliver only
    Inactive     ## visible, not primary
    Active       ## primary, working width
    Focused      ## keyboard focus inside sidebar
    Hidden       ## fully hidden

  SidebarPosition* = enum
    Left
    Right
    Bottom
    Top

  PanelSize* = object
    ratio*:     Option[float]   # 0.0..1.0
    px*:        Option[int]     # absolute pixels
    visiblePx*: Option[int]     # edge sliver when collapsed
    minPx*:     Option[int]
    maxPx*:     Option[int]

  ## Enum-indexed sizes — one slot per state, all compile-time known.
  ProfileSizes* = array[SidebarState, Option[PanelSize]]

  SidebarInstance* = object
    id*:         InstanceId
    position*:   SidebarPosition
    state*:      SidebarState
    windowIds*:  seq[WindowId]
    hidden*:     bool

# ─── actions ──────────────────────────────────────

type
  ActionKind* = enum
    akShellCmd
    akNiriAction
    akKanataFakeKey
    akInternalRpc

  ActionSpec* = object
    case kind*: ActionKind
    of akShellCmd:
      shellCmd*: string
    of akNiriAction:
      niriAction*: NiriActionSpec
    of akKanataFakeKey:
      fakeKeyName*: string
      fakeKeyAction*: string      # "Tap", "Press", "Release"
    of akInternalRpc:
      rpcMethod*: string
      rpcArgs*: string            # JSON-encoded args

  NiriActionKind* = enum
    naFocusWindow
    naCloseWindow
    naSetColumnWidth
    naMoveToFloating
    naMoveToWorkspace

  NiriActionSpec* = object
    case kind*: NiriActionKind
    of naFocusWindow:
      focusWindowId*: WindowId
    of naCloseWindow:
      closeWindowId*: WindowId
    of naSetColumnWidth:
      widthChange*: string        # serialized change spec
    of naMoveToFloating:
      floatWindowId*: WindowId
    of naMoveToWorkspace:
      moveWindowId*: WindowId
      moveWorkspaceId*: WorkspaceId

# ─── key tokens ───────────────────────────────────

type
  KeyToken* = distinct string     # normalized key name: "Leader", "R", "Shift+K"

# ─── commands ──────────────────────────────────────

type
  Command* = object
    id*:          CommandId
    title*:       string
    description*: string
    category*:    string
    tags*:        HashSet[string]
    sequence*:    seq[KeyToken]
    whenStates*:  set[SidebarState]
    action*:      ActionSpec
    dangerous*:   bool

# ─── profile ───────────────────────────────────────

type
  Profile* = object
    id*:          ProfileId
    pluginId*:    PluginId
    title*:       string
    kanataLayer*: Option[string]
    sizes*:       ProfileSizes
    commands*:    seq[Command]
    workspaceMatch*: Option[string]  # reserved: regex for workspace name

# ─── resolved runtime state ───────────────────────

type
  ResolvedProfile* = object
    profile*:   Profile
    instanceId*: InstanceId
    state*:     SidebarState
    size*:      PanelSize

  KeymapState* = object
    profileId*:    ProfileId
    prefix*:       seq[KeyToken]
    filter*:       string
    available*:    seq[Command]    # commands matching prefix + filter + state
    nextKeys*:     seq[KeyToken]   # valid next keypress from current prefix (ordered)
    exactMatch*:   Option[Command] # if prefix completes a command

  ShellState* = object
    # compositor
    windows*:        Table[WindowId, NiriWindow]
    focusedWindowId*: Option[WindowId]

    # sidebars
    instances*:      Table[InstanceId, SidebarInstance]
    activeInstance*:  Option[InstanceId]
    ownership*:      Table[WindowId, InstanceId]

    # profile
    resolved*:       Option[ResolvedProfile]

    # keyboard
    keymap*:         KeymapState

    # kanata
    kanataConnected*: bool
    kanataLayer*:     string

    # config
    config*:         SidebardConfig
```

### Public RPC types (`core/api_types.nim`)

```nim
## Stable types exposed over JSON-RPC. These are the public contract.
## Internal types can evolve independently — conversion procs bridge them.

import std/[options, tables]

type
  ApiWindow* = object
    id*: uint64
    appId*: Option[string]
    title*: Option[string]
    workspaceId*: Option[uint64]
    isFocused*: bool
    isFloating*: bool

  ApiSidebarInstance* = object
    id*: string
    position*: string             # "left", "right", "bottom", "top"
    state*: string                # "collapsed", "inactive", "active", "focused", "hidden"
    windowIds*: seq[uint64]
    hidden*: bool

  ApiCommand* = object
    id*: string
    title*: string
    description*: string
    category*: string
    tags*: seq[string]
    sequence*: seq[string]
    dangerous*: bool

  ApiKeymapState* = object
    profileId*: string
    prefix*: seq[string]
    filter*: string
    available*: seq[ApiCommand]
    nextKeys*: seq[string]
    exactMatch*: Option[ApiCommand]

  ApiResolvedProfile* = object
    profileId*: string
    pluginId*: string
    title*: string
    instanceId*: string
    state*: string
    kanataLayer*: Option[string]

  ApiStateSnapshot* = object
    focusedWindowId*: Option[uint64]
    activeInstance*: Option[string]
    resolved*: Option[ApiResolvedProfile]
    keymap*: ApiKeymapState
    kanataConnected*: bool
    kanataLayer*: string
```

### Design choices

**`distinct` types for IDs.** You cannot accidentally pass a `WindowId` where an `InstanceId` is expected. The compiler catches it. Zero runtime cost.

**`Option` instead of sentinel values.** No `-1` window IDs, no empty strings meaning "none." The type tells you if a value can be absent.

**`Result` for all fallible operations.** Every adapter proc returns `Result[T, string]` or `Result[T, SidebardError]`. No exceptions cross module boundaries.

**`set[SidebarState]` for command availability.** A command's `whenStates` is a compile-time-efficient bitset. Checking `Active in cmd.whenStates` is a single instruction.

**`ProfileSizes` as enum-indexed array.** Since `SidebarState` is a closed enum, an `array[SidebarState, Option[PanelSize]]` gives uniform access without hash table overhead.

**`SidebarPosition` as enum.** No stringly-typed "left"/"right" — the compiler enforces valid positions.

**`ActionSpec` as typed variant.** Commands carry structured action data, not opaque shell strings. The runtime dispatches on kind without parsing.

**`KeyToken` as distinct string.** Key names are normalized and type-safe within the domain. Serialization to/from plain strings happens at the boundary.

**Separate internal vs public types.** `core/types.nim` can evolve freely. `core/api_types.nim` is the stable RPC contract. Conversion procs bridge them, and clients never depend on internal representation.

**`seq` for ordered collections in public types.** `HashSet` and `Table` have non-deterministic iteration order. Public-facing fields use `seq` for stable serialization and predictable UI output.

---

## Event model

Every input to the system is an `Event`. Events are data — they carry what happened, not what to do about it.

```nim
type
  EventKind* = enum
    # niri
    evWindowOpened
    evWindowChanged
    evWindowClosed
    evWindowFocused
    evWorkspaceActivated

    # kanata
    evKanataConnected
    evKanataDisconnected
    evKanataLayerChanged
    evKanataMessage

    # sidebar (from niri-sidebar state files or future IPC)
    evSidebarStateRead

    # user interaction (via RPC)
    evActivateInstance
    evToggleVisibility
    evPrefixAdvance
    evPrefixReset
    evFilterSet
    evCommandInvoked

    # system
    evConfigReloaded
    evTimerFired

  Event* = object
    ts*: MonoTime
    case kind*: EventKind
    of evWindowOpened, evWindowChanged:
      window*: NiriWindow
    of evWindowClosed:
      closedWindowId*: WindowId
    of evWindowFocused:
      focusedId*: Option[WindowId]
    of evWorkspaceActivated:
      workspaceId*: WorkspaceId
      workspaceFocused*: bool
    of evKanataConnected:
      discard
    of evKanataDisconnected:
      discard
    of evKanataLayerChanged:
      oldLayer*, newLayer*: string
    of evKanataMessage:
      message*: string
    of evSidebarStateRead:
      sidebarInstanceId*: InstanceId
      sidebarWindows*: seq[WindowId]
      sidebarHidden*: bool
    of evActivateInstance:
      targetInstance*: InstanceId
    of evToggleVisibility:
      toggleInstance*: InstanceId
    of evPrefixAdvance:
      key*: KeyToken
    of evPrefixReset:
      discard
    of evFilterSet:
      filterText*: string
    of evCommandInvoked:
      commandId*: CommandId
    of evConfigReloaded:
      newConfig*: SidebardConfig
    of evTimerFired:
      timerId*: string
```

---

## Effect model

The reducer does not perform I/O. Instead, it returns a list of effects — descriptions of what should happen. The runtime interprets them.

```nim
type
  EffectKind* = enum
    efChangeKanataLayer
    efExecuteAction
    efStartTimer
    efCancelTimer
    efNotifySubscribers
    efNiriAction

  Effect* = object
    case kind*: EffectKind
    of efChangeKanataLayer:
      layer*: string
    of efExecuteAction:
      action*: ActionSpec
    of efStartTimer:
      timerId*: string
      durationMs*: int
    of efCancelTimer:
      cancelTimerId*: string
    of efNotifySubscribers:
      discard
    of efNiriAction:
      niriAction*: NiriActionSpec
```

### Why effects-as-data

1. **Testable.** Assert that reducing event X produces effect Y. No mocking.
2. **Traceable.** Log every effect. Replay them. Debug them.
3. **Batchable.** Multiple effects from one event are collected and executed together.
4. **Cancelable.** A timer effect can be superseded before the runtime executes it.

---

## The reducer

The heart of the system. A deterministic function — no I/O, no async, but mutates state in place for performance.

```nim
proc reduce*(state: var ShellState, event: Event): seq[Effect] =
  ## Mutates state in place. Returns effects to execute.
  ## This function MUST NOT perform I/O or call async.
  result = @[]

  case event.kind
  of evWindowOpened, evWindowChanged:
    state.windows[event.window.id] = event.window

  of evWindowClosed:
    state.windows.del(event.closedWindowId)
    state.ownership.del(event.closedWindowId)

  of evWindowFocused:
    state.focusedWindowId = event.focusedId
    # re-resolve profile
    let prev = state.resolved
    state.resolved = resolveProfile(state)
    if state.resolved != prev:
      state.keymap = rebuildKeymap(state)
      if state.resolved.isSome:
        let layer = state.resolved.get.profile.kanataLayer
        if layer.isSome and layer.get != state.kanataLayer:
          result.add Effect(kind: efChangeKanataLayer, layer: layer.get)
      result.add Effect(kind: efNotifySubscribers)

  of evActivateInstance:
    state.activeInstance = some(event.targetInstance)
    let prev = state.resolved
    state.resolved = resolveProfile(state)
    if state.resolved != prev:
      state.keymap = rebuildKeymap(state)
      result.add Effect(kind: efNotifySubscribers)

  of evPrefixAdvance:
    advancePrefix(state.keymap, event.key)
    result.add Effect(kind: efNotifySubscribers)

  of evPrefixReset:
    resetPrefix(state.keymap)
    result.add Effect(kind: efNotifySubscribers)

  of evCommandInvoked:
    let cmd = findCommand(state, event.commandId)
    if cmd.isSome:
      result.add Effect(kind: efExecuteAction, action: cmd.get.action)
    resetPrefix(state.keymap)
    result.add Effect(kind: efNotifySubscribers)

  # ... other cases
```

This is pseudocode showing the pattern. The real implementation will handle every event kind.

---

## Profile resolution

Simple, flat, deterministic.

```nim
proc resolveProfile*(state: ShellState): Option[ResolvedProfile] =
  ## 1. If a window is focused and owned by a sidebar,
  ##    find the plugin whose matchAppIds matches the window's appId.
  ## 2. If no match, use the active sidebar's default plugin.
  ## 3. If no active sidebar, return none.
  ##
  ## No 6-level merge cascade. A plugin declares its full profile.
  ## An instance override replaces specific fields. Two levels.
  ##
  ## Future: workspaceMatch in profiles can optionally scope
  ## command availability by workspace name. Not wired in v1.
```

The resolved profile determines everything:
- which `PanelSize` applies (from `profile.sizes[state]`)
- which `commands` are available
- which `kanataLayer` is active
- what the keymap trie contains

One resolution, one source of truth.

---

## Keymap engine

A trie of key sequences, rebuilt when the active profile changes.

```nim
type
  TrieNode = object
    children: Table[KeyToken, TrieNode]
    commandIds: seq[CommandId]

proc buildTrie*(commands: seq[Command]): TrieNode =
  ## Inserts each command's key sequence into the trie.
  ## A command with sequence [Leader, R] creates:
  ##   root -> Leader -> R (terminal, holds command id)

proc advance*(state: var KeymapState, key: KeyToken) =
  ## Push a key onto the prefix.
  ## Recompute: available commands, next valid keys, exact match.

proc filter*(state: var KeymapState, text: string) =
  ## Set text filter. Intersects with prefix-filtered commands.
  ## Matches against title, description, tags.

proc reset*(state: var KeymapState) =
  ## Clear prefix and filter. Restore full command list.
```

### What the keymap exposes

After any change to prefix or filter, the keymap state contains:

- `available`: commands reachable from the current prefix + matching the filter
- `nextKeys`: the set of keys that continue at least one available command (ordered for stable UI)
- `exactMatch`: if the current prefix exactly completes one command

A UI consumer only needs to read these fields to render a which-key popup, a command palette, or an ASCII keyboard with highlighted keys.

---

## Config format

### Hierarchy

```
~/.config/sidebard/
├── config.toml              # daemon settings
├── plugins/                 # one file per app type
│   ├── chat.toml
│   ├── code.toml
│   └── media.toml
└── instances/               # per-sidebar overrides
    ├── left.toml
    ├── right.toml
    └── bottom.toml
```

Merge order: `config.toml` → `plugins/*.toml` → `instances/*.toml`

Scalars: last writer wins. Sequences: replace. Tables: recursive merge.

### `config.toml`

```toml
[daemon]
socket = "/run/user/1000/sidebard.sock"

[kanata]
host = "127.0.0.1"
port = 6666
reconnect_ms = 3000

[defaults]
overlay_timeout_ms = 1200
collapsed_visible_px = 28
```

### `plugins/chat.toml`

```toml
id = "chat"
title = "Chat"
priority = 200

match_app_ids = [
  '^vesktop$',
  '^org\.telegram\.desktop$',
]

[profile]
title = "Chat"
kanata_layer = "sidebar-chat"

[profile.sizes.collapsed]
visible_px = 30

[profile.sizes.inactive]
ratio = 0.20

[profile.sizes.active]
ratio = 0.34

[profile.sizes.focused]
ratio = 0.42

[[commands]]
id = "chat.quick_reply"
title = "Quick reply"
description = "Reply to the selected conversation"
category = "messaging"
tags = ["reply", "chat", "message"]
sequence = ["Leader", "R"]
when_states = ["active", "focused"]
action = { shell = "sidebard-action chat quick-reply" }

[[commands]]
id = "chat.next_unread"
title = "Next unread"
description = "Jump to the next unread conversation"
category = "messaging"
tags = ["nav", "unread", "chat"]
sequence = ["Leader", "J"]
when_states = ["active", "focused"]
action = { shell = "sidebard-action chat next-unread" }

[[commands]]
id = "chat.mark_read"
title = "Mark read"
description = "Mark the selected thread as read"
category = "messaging"
tags = ["read", "inbox"]
sequence = ["Leader", "M"]
when_states = ["active", "focused"]
action = { shell = "sidebard-action chat mark-read" }
```

### Action format in TOML

Actions are typed inline tables. The loader normalizes them into `ActionSpec` variants:

```toml
# shell command
action = { shell = "my-command --flag" }

# niri action
action = { niri = "FocusWindow", window_id = 42 }

# kanata fake key
action = { kanata_key = "vk-reply", key_action = "Tap" }

# internal RPC call
action = { rpc = "toggle", args = "left" }
```

### `instances/right.toml`

```toml
id = "right"
position = "right"
default_plugin = "chat"

# override chat profile sizes for the right sidebar specifically
[overrides.chat.sizes.active]
ratio = 0.38

[overrides.chat.sizes.focused]
ratio = 0.45
```

---

## Niri adapter

### Connection

Connect to `$NIRI_SOCKET`. Send JSON request on one line. Read JSON response on one line.

For the event stream: send `"EventStream"`, read the `Ok` acknowledgment, then continuously read events (one JSON object per line, forever).

### Requests the daemon uses

| What | Request | When |
|---|---|---|
| All windows | `"Windows"` | Startup, to build initial window table |
| Focused window | `"FocusedWindow"` | Startup, to seed focus state |
| Event stream | `"EventStream"` | Startup, kept open for the daemon's lifetime |
| Focus a window | `{"Action":{"FocusWindow":{"id":N}}}` | `focus` command |
| Close a window | `{"Action":{"CloseWindow":{"id":N}}}` | `close` command |
| Resize column | `{"Action":{"SetColumnWidth":{"change":...}}}` | Profile-driven resize |
| Move to floating | `{"Action":{"MoveWindowToFloating":{"id":N}}}` | Sidebar management |

### Events the daemon processes

| Event | Maps to |
|---|---|
| `WindowOpenedOrChanged` | `evWindowOpened` / `evWindowChanged` |
| `WindowClosed` | `evWindowClosed` |
| `WindowFocusChanged` | `evWindowFocused` |
| `WorkspaceActivated` | `evWorkspaceActivated` |

All other niri events are ignored.

### Niri adapter interface

```nim
type
  NiriAdapter* = ref object
    conn: AsyncSocket

proc connect*(): Future[Result[NiriAdapter, string]]
proc listWindows*(n: NiriAdapter): Future[Result[seq[NiriWindow], string]]
proc focusedWindow*(n: NiriAdapter): Future[Result[Option[NiriWindow], string]]
proc eventStream*(n: NiriAdapter): Future[Result[void, string]]
  ## After calling this, read events with readEvent()
proc readEvent*(n: NiriAdapter): Future[Result[Event, string]]
proc executeAction*(n: NiriAdapter, action: NiriActionSpec): Future[Result[void, string]]
```

---

## Kanata adapter

### Connection

TCP to `host:port` (default `127.0.0.1:6666`). Send JSON commands, receive JSON responses/notifications.

### Commands the daemon sends

| What | JSON | When |
|---|---|---|
| Switch layer | `{"ChangeLayer":{"new":"sidebar-chat"}}` | Profile resolved with a kanataLayer |
| Get current layer | `{"RequestLayerNames":{}}` | Startup |
| Fake key tap | `{"ActOnFakeKey":{"name":"vk-reply","action":"Tap"}}` | UI-triggered action |

### Events received

| What | JSON |
|---|---|
| Layer changed | `{"LayerChange":{"old":"base","new":"sidebar-chat"}}` |
| Config reloaded | `{"ConfigFileReload":{"new":"path"}}` |

### Prefix tracking via Kanata

For v1, Kanata config includes `cmd` or `push-msg` actions on leader keys:

```kbd
(defalias
  leader (multi
    (layer-while-held leader-layer)
    (cmd sidebard prefix advance Leader)))
```

When the leader is pressed, Kanata runs `sidebard prefix advance Leader`, which sends an RPC to the daemon, which produces `evPrefixAdvance`. The keymap engine updates. Any subscribed UI sees the new `nextKeys` immediately via push notification.

On timeout or completion, Kanata sends `sidebard prefix reset`.

This keeps sidebard out of the keypress path. Kanata is the authority on what physical keys do. Sidebard only tracks the semantic prefix state.

### Graceful degradation

Kanata is optional. If the connection fails:
- Log a warning via chronicles
- Retry every `reconnect_ms`
- Skip all `efChangeKanataLayer` effects
- Everything else works normally

---

## JSON-RPC interface

Unix socket, newline-framed JSON-RPC 2.0 via `nim-json-rpc`.

### Methods

```nim
# ─── queries ──────────────────────────────────────

rpc("state") do() -> ApiStateSnapshot:
  ## Full shell state snapshot.

rpc("profile") do() -> Option[ApiResolvedProfile]:
  ## Current resolved profile.

rpc("keymap") do() -> ApiKeymapState:
  ## Current keymap: prefix, available commands, next keys.

rpc("commands") do() -> seq[ApiCommand]:
  ## All commands for the active profile.

rpc("instances") do() -> seq[ApiSidebarInstance]:
  ## All sidebar instances with state.

rpc("windows") do() -> seq[ApiWindow]:
  ## All tracked windows.

# ─── actions ──────────────────────────────────────

rpc("activate") do(instance: string):
  ## Set active sidebar instance.

rpc("toggle") do(instance: string):
  ## Toggle sidebar visibility.

rpc("prefix.advance") do(key: string):
  ## Push a key onto the keymap prefix.

rpc("prefix.reset") do():
  ## Clear the keymap prefix.

rpc("filter") do(text: string):
  ## Set the command filter text.

rpc("run") do(command: string):
  ## Execute a command by ID.

rpc("reload") do():
  ## Reload config from disk.

# ─── subscriptions ────────────────────────────────

rpc("subscribe") do(topics: seq[string]) -> string:
  ## Subscribe to push notifications. Returns a subscription ID.
  ## Topics: "state", "keymap", "profile", "instances"
  ## After subscribing, the server sends JSON-RPC notifications
  ## on the same connection whenever the subscribed state changes.

rpc("unsubscribe") do(subscriptionId: string):
  ## Remove a subscription.
```

### Push notifications

When state changes and `efNotifySubscribers` fires, the server sends a JSON-RPC notification to each subscribed connection:

```json
{"jsonrpc": "2.0", "method": "notify.keymap", "params": { ... ApiKeymapState ... }}
{"jsonrpc": "2.0", "method": "notify.profile", "params": { ... ApiResolvedProfile ... }}
{"jsonrpc": "2.0", "method": "notify.state", "params": { ... ApiStateSnapshot ... }}
```

Notifications are topic-filtered: a client that only subscribes to `"keymap"` only receives `notify.keymap`. This keeps bandwidth low for focused consumers like a which-key popup.

### CLI mode

When `sidebard` is invoked with a subcommand, it acts as an RPC client:

```
sidebard daemon                  # start the daemon
sidebard state                   # → rpc("state")
sidebard profile                 # → rpc("profile")
sidebard keymap                  # → rpc("keymap")
sidebard commands                # → rpc("commands")
sidebard activate right          # → rpc("activate", "right")
sidebard toggle left             # → rpc("toggle", "left")
sidebard prefix advance Leader   # → rpc("prefix.advance", "Leader")
sidebard prefix reset            # → rpc("prefix.reset")
sidebard filter "reply"          # → rpc("filter", "reply")
sidebard run chat.quick_reply    # → rpc("run", "chat.quick_reply")
sidebard reload                  # → rpc("reload")
sidebard watch keymap            # → rpc("subscribe", ["keymap"]), then print notifications
```

All query commands accept `--json` (default) and `--pretty` flags.

`sidebard watch` subscribes and streams notifications to stdout — useful for piping into UI renderers or debugging.

Implemented with [cligen](https://github.com/c-blake/cligen) — each subcommand is a proc, `dispatchMulti` generates the CLI.

---

## Ownership tracking

### Compatibility note

v1 hydrates ownership from niri-sidebar's `state.json` files. This is a **compatibility adapter**, not the permanent source of truth. In a future version, sidebard will either become the authoritative owner of sidebar membership state or define a formal adapter contract that decouples it from niri-sidebar's file format.

### The problem it solves

A window can belong to at most one sidebar instance. When a user runs `sidebard toggle right` for the focused window, the system needs to know:
1. Does any sidebar already own this window?
2. If yes, remove it from there first.
3. Then add it to `right`.

### How it works

The ownership table is `Table[WindowId, InstanceId]`.

It's populated at startup by reading each niri-sidebar instance's `state.json` (which lists owned window IDs). It's updated when:
- A window is toggled into/out of a sidebar
- A window is closed
- A repair detects inconsistency

### Repair

`sidebard repair` scans all `state.json` files, detects duplicate ownership (window in multiple sidebars), and resolves by keeping the first claim. This is the same logic as the current `sidebarctl repair`.

---

## Daemon lifecycle

### Startup sequence

```
1. Load config from TOML hierarchy
2. Connect to niri socket
3. Request Windows → seed window table
4. Request FocusedWindow → seed focus
5. Read sidebar state.json files → seed ownership + instances (compatibility adapter)
6. Resolve initial profile
7. Start niri event stream (async reader)
8. Connect to Kanata (non-fatal if unavailable)
9. Start JSON-RPC server on Unix socket
10. Enter event loop
```

### Event loop

```
forever:
  event = await nextEvent(niriStream, kanataStream, rpcServer, timers)
  effects = reduce(state, event)
  for eff in effects:
    execute(eff)
```

Single-threaded, single event loop, no locks. Chronos handles the async multiplexing.

### Shutdown

1. Close RPC server (notify subscribers of disconnect)
2. Close Kanata connection
3. Close niri connection
4. Exit

No state to persist — sidebar instance state lives in niri-sidebar's `state.json` files. The daemon is stateless across restarts (it rehydrates from niri + state files on startup).

### Degraded modes

| Missing | Behavior |
|---|---|
| Niri socket | Fatal — exit with error |
| Kanata | Warning — skip layer switching, retry periodically |
| state.json files | Warning — ownership table starts empty, repairs on first sidebar event |
| Config files | Fatal — cannot determine plugins or instances |

---

## Nix integration

### Package

```nix
{ lib, nimPackages, fetchFromGitHub }:

nimPackages.buildNimPackage {
  pname = "sidebard";
  version = "0.1.0";
  src = fetchFromGitHub { ... };
  # nimble deps resolved by nimPackages
  # IMPORTANT: pin or vendor the Nim dependency graph — do not rely on
  # ad hoc nimble resolution during Nix builds.
}
```

Single package, single binary.

### Home Manager module

```nix
{ config, lib, pkgs, ... }:

let cfg = config.my.desktop.sidebard;
in {
  options.my.desktop.sidebard = {
    enable = lib.mkEnableOption "sidebard shell daemon";
    plugins = lib.mkOption { type = lib.types.attrsOf pluginType; };
    instances = lib.mkOption { type = lib.types.attrsOf instanceType; };
    kanata.port = lib.mkOption { type = lib.types.port; default = 6666; };
  };

  config = lib.mkIf cfg.enable {
    # generate TOML config files
    xdg.configFile = {
      "sidebard/config.toml".text = toTOML { ... };
    } // lib.mapAttrs' (name: plugin:
      lib.nameValuePair "sidebard/plugins/${name}.toml" {
        text = toTOML (pluginToToml plugin);
      }
    ) cfg.plugins
    // lib.mapAttrs' (name: inst:
      lib.nameValuePair "sidebard/instances/${name}.toml" {
        text = toTOML (instanceToToml inst);
      }
    ) cfg.instances;

    # systemd user service
    systemd.user.services.sidebard = {
      Unit.Description = "sidebard shell daemon";
      Unit.After = [ "graphical-session.target" ];
      Service.ExecStart = "${pkgs.sidebard}/bin/sidebard daemon";
      Service.Restart = "on-failure";
      Service.RestartSec = 2;
      Install.WantedBy = [ "graphical-session.target" ];
    };

    # put the binary on PATH for CLI use
    home.packages = [ pkgs.sidebard ];
  };
}
```

---

## Dependencies

| Package | Purpose | Why not stdlib |
|---|---|---|
| [chronos](https://github.com/status-im/nim-chronos) | Async runtime | Correct callback ordering, required by json-rpc |
| [nim-results](https://github.com/arnetheduck/nim-results) | `Result[T, E]` | Explicit errors, no exceptions |
| [jsony](https://github.com/treeform/jsony) | JSON (de)serialization | 10x faster, direct to types |
| [toml-serialization](https://github.com/status-im/nim-toml-serialization) | TOML config loading | TOML 1.0, direct to types |
| [nim-json-rpc](https://github.com/status-im/nim-json-rpc) | JSON-RPC 2.0 server/client | Auto-marshalling, routing, notifications |
| [cligen](https://github.com/c-blake/cligen) | CLI from proc signatures | Zero boilerplate |
| [chronicles](https://github.com/status-im/nim-chronicles) | Structured logging | Scoped, compile-time filtered |

Everything else is Nim stdlib (`options`, `tables`, `sets`, `times`, `os`, `re`).

---

## Implementation phases

### Phase 1 — Skeleton + niri adapter

Build the binary. Connect to niri. Subscribe to events. Print them to stdout.

**Ships:** `sidebard daemon` that logs niri events via chronicles.

**Proves:** The niri socket protocol works, chronos event loop works, the binary compiles with all dependencies.

### Phase 2 — Core domain + state

Implement `types.nim`, `api_types.nim`, `state.nim`, `ownership.nim`. Feed niri events through the reducer. Maintain a `ShellState` in memory.

**Ships:** `sidebard state --json` prints the full state snapshot (via a temporary stdout dump, no RPC yet).

**Proves:** The event → reduce → state pipeline works. Ownership tracking works. Window table stays consistent.

### Phase 3 — Config + profiles

Implement `config.nim`, `profile.nim`. Load TOML plugins. Resolve profiles from focus context.

**Ships:** `sidebard profile --json` shows the resolved profile for the current focus.

**Proves:** TOML loading works. Profile resolution is deterministic. The hierarchy merge works.

### Phase 4 — RPC server + subscriptions + CLI

Implement `rpc.nim`, `cli.nim`. Start the JSON-RPC server with both request/response and push notifications. Wire all query, action, and subscription methods. Implement CLI subcommands as RPC clients.

**Ships:** Full `sidebard` CLI — `sidebard activate right`, `sidebard keymap`, `sidebard watch keymap`, etc.

**Proves:** The IPC contract works. Push subscriptions work. External tools can query, control, and reactively consume sidebard state.

### Phase 5 — Keymap engine

Implement `keymap.nim`. Build the trie from active profile commands. Handle prefix advance/reset, text filtering.

**Ships:** `sidebard keymap` shows available commands, next keys, and exact matches. `sidebard prefix advance Leader` updates the keymap in real time. `sidebard watch keymap` streams changes.

**Proves:** The keyboard engine works. Prefix tracking through RPC works. A which-key UI could be built on top of this.

### Phase 6 — Kanata bridge

Implement `kanata.nim`. Connect to Kanata TCP. Send `ChangeLayer` on profile changes. Subscribe to `LayerChange` events.

**Ships:** Focusing a chat window switches Kanata to the `sidebar-chat` layer automatically.

**Proves:** The full loop works: niri focus → profile resolution → Kanata layer → keymap update.

---

## What this intentionally excludes

These are not in scope. They may become relevant later, but building them now would be premature.

- **Renderer / UI surfaces.** sidebard is the state daemon. A TUI, layer-shell widget, or eww bar can consume its RPC/subscription interface. The daemon doesn't render anything.
- **Plugin scripts.** A plugin is a TOML file. If you need dynamic state (badge counts, build status), write a script that calls `sidebard` RPC methods. The daemon doesn't host script runtimes.
- **Overlay timing.** The concept doc describes transient pop overlays. These are a renderer concern. sidebard can emit "overlay requested" effects, but displaying them is the renderer's job.
- **Terminal panel.** Same — a renderer surface, not a daemon feature.
- **Fuzzy matching / scoring.** The keymap engine does exact prefix matching and substring text filtering. Fuzzy ranking is a UI concern.
- **Multi-monitor awareness.** Profile resolution doesn't consider which output a sidebar is on. The `OutputId` field is reserved in the type model but not wired into resolution logic. Add it when there's a real multi-monitor setup to test against.
- **Workspace-scoped commands.** The `workspaceMatch` field in `Profile` is reserved but not wired in v1. When workspace-specific command sets become needed, the type structure is ready.

---

## Design invariants

These should be enforced by tests and never violated.

1. **`reduce()` is deterministic and I/O-free.** It never performs I/O, never calls async, never accesses global state. It mutates `var ShellState` in place but produces no observable side effects beyond the returned `seq[Effect]`.
2. **One active profile.** At most one profile drives the keymap at any time, even if multiple sidebars are visible.
3. **Ownership is exclusive.** A window belongs to at most one sidebar instance.
4. **Effects are ordered.** Effects from a single reduce call execute in list order.
5. **Events are total.** The reducer handles every `EventKind`. No silently dropped events.
6. **IDs are stable.** `CommandId`, `PluginId`, `ProfileId` do not change between config reloads for the same logical entity.
7. **The daemon is stateless across restarts.** All persistent state lives in niri-sidebar's `state.json` files and the TOML config. (v1 compatibility — see ownership section.)
8. **Public types are stable.** `api_types.nim` is the client contract. Internal type changes must not break RPC consumers.
9. **Subscriptions are push, not poll.** State changes reach subscribers within the same event loop tick that produces `efNotifySubscribers`.
