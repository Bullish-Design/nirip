# NIMRI: Final Architecture & Concept

A layered control plane for the Niri compositor — typed, reactive, declarative.

---

## The one-paragraph version

**Nimri** is three systems. **`nimri-ipc`** is a typed Nim library for the Niri compositor protocol — models, actions, command client, event stream. **`sidebard`** is a reactive daemon that reduces compositor and keyboard events into unified shell state (profiles, keymaps, sidebar ownership) and exposes it over JSON-RPC with push subscriptions. **`nirip`** is an on-demand CLI that loads, freezes, diffs, and reconciles declarative workspace layouts from TOML profiles through pure planning and event-confirmed execution. `nimri-ipc` is the shared substrate. `sidebard` and `nirip` are peers — not parent/child.

---

## 1. System purpose

Nimri makes a Niri desktop:

- **Inspectable** — all live shell state is queryable via RPC
- **Reactive** — focus and context changes immediately drive command/keymap/profile state
- **Reproducible** — workspace layouts can be loaded, diffed, frozen, and restored
- **Typed** — compositor interactions are explicit Nim types, not ad hoc JSON blobs

---

## 2. Architecture

```
                   ┌──────────────────────┐
                   │        Niri          │
                   │  socket + events     │
                   └──────────┬───────────┘
                              │
                        typed protocol
                              │
                   ┌──────────▼───────────┐
                   │      nimri-ipc       │
                   │ models/actions/io    │
                   └───────┬───────┬──────┘
                           │       │
                 snapshots/actions │ events
                           │       │
                  ┌────────▼───┐ ┌─▼──────────┐
                  │   nirip    │ │  sidebard  │
                  │ planner +  │ │ reducer +  │
                  │ executor   │ │ rpc daemon │
                  └──────┬─────┘ └────┬───────┘
                         │            │
                profile TOML/state    │ subscriptions/RPC
                         │            │
                         ▼            ▼
                   user/Nix config   UIs / scripts / Kanata
```

---

## 3. Source-of-truth model

Nimri has three truths. This separation is the key architectural invariant — it prevents the system from mixing "what is," "what it means," and "what should be."

### 3.1 Compositor truth (Niri)

Live ground truth for: existing windows, workspace membership, focus, column layout, output topology.

### 3.2 Shell truth (sidebard)

Semantic truth for: which sidebar owns which window, which profile is active, which commands are available, current keymap state, current Kanata layer intent.

### 3.3 Desired-layout truth (nirip)

Declarative truth for: what workspace arrangement should exist, what windows should be present, what matching rules define those roles, what reconciliation actions are acceptable.

---

## 4. Component responsibilities

### 4.1 `nimri-ipc` — typed Niri protocol library

Owns only Niri protocol concerns. No persistent state.

**Owns:**
- Typed identifiers and domain models
- Typed request/response encoding
- Typed action algebra (100+ action constructors)
- Async command client
- Async event stream client
- Protocol/transport error handling
- Codec helpers (tagged variant parsing, frame buffering)

**Does not own:**
- Sidebar semantics, profile resolution, command/keymap logic
- Workspace profile loading, matching policy, reconciliation strategy

#### Current `nimri-ipc` public API

The library already provides a complete, tested surface:

**Package:** `nimri_ipc` v0.1.0 — MIT — requires Nim >= 2.0.0, results >= 0.4.0

**Typed identifiers:**
- `WindowId` (distinct uint64)
- `WorkspaceId` (distinct uint64)
- `OutputName` (distinct string)
- `WorkspaceIdx` (distinct uint8)

**Domain models:**
- `Window` — id, title, appId, pid, workspaceId, isFocused, isFloating, isUrgent, layout, focusTimestamp
- `WindowLayout` — tileSize, windowSize, posInScrollingLayout, tilePosInWorkspaceView, windowOffsetInTile
- `Workspace` — id, idx, name, output, isActive, isFocused, isUrgent, activeWindowId
- `Output` — name, make, model, serial, physicalSize, modes, currentMode, vrrSupported/Enabled, logical
- `LogicalOutput` — x, y, width, height, scale, transform
- `Mode` — width, height, refreshRate, isPreferred
- `KeyboardLayouts` — names, currentIdx
- `LayerSurface` — namespace, output, layer, keyboardInteractivity
- `Cast` — streamId, sessionId, kind, target, isActive, pid
- `Timestamp` — secs, nanos

**Typed action system:**
- `NiriAction` — variant object with `NiriActionKind` (100+ variants)
- `SizeChange` — SetFixed/SetProportion/AdjustFixed/AdjustProportion
- `PositionChange` — SetFixed/SetProportion/AdjustFixed/AdjustProportion
- `WorkspaceRef` — ById/ByIndex/ByName
- `LayoutSwitchTarget` — Next/Prev/ByIndex
- `ColumnDisplay` — cdNormal/cdTabbed
- Constructor procs for every action: `focusWindow`, `closeWindow`, `spawn`, `spawnSh`, `setColumnWidth`, `moveWindowToWorkspace`, `consumeOrExpelWindowRight`, etc.

**Request/response system:**
- `NiriRequest` — variant with `NiriRequestKind` (Version, Outputs, Workspaces, Windows, Layers, KeyboardLayouts, FocusedOutput, FocusedWindow, OverviewState, Casts, PickWindow, PickColor, Action, EventStream, etc.)
- `NiriResponse` — variant with `NiriResponseKind` matching each request type

**Event system:**
- `NiriEvent` — variant with `NiriEventKind`: WindowOpenedOrChanged, WindowClosed, WindowFocusChanged, WindowFocusTimestampChanged, WindowUrgencyChanged, WindowLayoutsChanged, WorkspacesChanged, WorkspaceActivated, WorkspaceUrgencyChanged, WorkspaceActiveWindowChanged, KeyboardLayoutsChanged, KeyboardLayoutSwitched, OverviewOpenedOrClosed, ConfigLoaded, ScreenshotCaptured, CastsChanged, CastStartedOrChanged, CastStopped, Unknown
- Predicates: `isWindowEvent`, `isWorkspaceEvent`, `isKeyboardEvent`, `isSystemEvent`, `isCastEvent`

**Error system:**
- `NimriIpcError` — kind, message, operation, detail
- `NimriIpcErrorKind` — SocketPathMissing, SocketConnectFailed, SocketReadFailed, SocketWriteFailed, ConnectionClosed, Timeout, JsonEncodeError, JsonDecodeError, ProtocolViolation, NiriError, ResponseMismatch, UnsupportedValue
- Constructor procs for each error kind
- All fallible operations return `Result[T, NimriIpcError]`

**Command client:**
- `NiriClient` — ref object with socket, config, connected state
- `openClient(config): Future[Result[NiriClient, NimriIpcError]]`
- `send(client, request): Future[Result[NiriResponse, NimriIpcError]]`
- `getWindows(client): Future[Result[seq[Window], NimriIpcError]]`
- `getWorkspaces(client): Future[Result[seq[Workspace], NimriIpcError]]`
- `getOutputs(client): Future[Result[Table[string, Output], NimriIpcError]]`
- `getFocusedWindow(client): Future[Result[Option[Window], NimriIpcError]]`
- `getFocusedOutput(client): Future[Result[Option[Output], NimriIpcError]]`
- `getVersion(client): Future[Result[string, NimriIpcError]]`
- `doAction(client, action): Future[Result[void, NimriIpcError]]`
- `close(client)`

**Event stream client:**
- `NiriEventStream` — ref object with socket, config, frameBuffer, connected state
- `openEventStream(config): Future[Result[NiriEventStream, NimriIpcError]]`
- `next(stream, timeout): Future[Result[NiriEvent, NimriIpcError]]`
- `waitFor(stream, predicate, timeout): Future[Result[NiriEvent, NimriIpcError]]`
- `close(stream)`

**Transport/config:**
- `NiriConnectConfig` — socketPath, commandTimeout
- `initNiriConnectConfig(socketPath, commandTimeout)`
- `resolveSocketPath(config): Result[string, NimriIpcError]`
- `NiriSocketEnv = "NIRI_SOCKET"`

**Codec helpers:**
- `TaggedVariant` — tag, payload, isUnit (for Rust-style JSON enum parsing)
- `FrameBuffer` — line-oriented frame accumulation for streaming
- Field accessor helpers: `getField`, `getStr`, `getInt`, `getUint64`, `getFloat`, `getBool`
- Optional variants: `getOptionalField`, `getOptionalStr`, `getOptionalInt`, `getOptionalUint64`

#### What `nimri-ipc` still needs for Nimri

The library is feature-complete for protocol concerns. Two additions are needed:

1. **Snapshot helper** — a convenience proc that fetches windows + workspaces + outputs + focused window in one call sequence:

```nim
type
  NiriSnapshot* = object
    windows*: seq[Window]
    workspaces*: seq[Workspace]
    outputs*: Table[string, Output]
    focusedWindowId*: Option[WindowId]

proc snapshot*(client: NiriClient): Future[Result[NiriSnapshot, NimriIpcError]] {.async.}
```

2. **Event filtering helpers** — convenience for the `waitFor` pattern used by nirip's executor:

```nim
proc isWindowOpenedWithAppId*(appId: string): proc(e: NiriEvent): bool
proc isWindowMovedToWorkspace*(windowId: WindowId, wsId: WorkspaceId): proc(e: NiriEvent): bool
proc isFocusChanged*(windowId: WindowId): proc(e: NiriEvent): bool
```

These are small additions that preserve the library's protocol-only scope.

---

### 4.2 `sidebard` — reactive shell/session daemon

Always-on daemon. Core model: **events in, state out, effects as data.**

**Owns:**
- Live window table and focus state
- Sidebar instances and window-to-sidebar ownership
- Runtime profile resolution (plugin matching from focus context)
- Command registry and keymap trie
- Kanata integration (layer switching, fake keys)
- JSON-RPC query/action interface
- Push subscriptions for consumers

**Philosophy:**

1. **Events in, state out.** The entire system is a deterministic function from events to state. Every input is an event. Every output is derived from state.
2. **The domain is pure.** Core logic (profile resolution, ownership tracking, keymap trie, config merging) has zero I/O. Trivially testable.
3. **I/O lives at the edges.** Protocol adapters translate bytes into domain events and domain effects into bytes. Nothing else.
4. **One binary, two modes.** `sidebard daemon` runs the event loop. `sidebard <subcommand>` sends an RPC request and exits.
5. **Composition over framework.** A plugin is a TOML file. An action is a typed command spec. Extensibility comes from the IPC surface.

#### Internal types (`core/types.nim`)

```nim
import std/[options, sets, tables, times]
import results

# ─── identifiers ─────────────────────────────────
type
  WindowId*    = distinct uint64
  WorkspaceId* = distinct uint64
  OutputId*    = distinct string
  InstanceId*  = distinct string   # "left", "right", "bottom"
  PluginId*    = distinct string   # "chat", "code", "media"
  ProfileId*   = distinct string   # "chat/default", "code/focused"
  CommandId*   = distinct string   # "chat.quick_reply"

# ─── compositor model ────────────────────────────
type
  NiriWindow* = object
    id*: WindowId
    appId*: Option[string]
    title*: Option[string]
    workspaceId*: Option[WorkspaceId]
    outputId*: Option[OutputId]     # reserved for multi-monitor
    isFocused*: bool
    isFloating*: bool

# ─── sidebar model ───────────────────────────────
type
  SidebarState* = enum
    Collapsed    ## edge sliver only
    Inactive     ## visible, not primary
    Active       ## primary, working width
    Focused      ## keyboard focus inside sidebar
    Hidden       ## fully hidden

  SidebarPosition* = enum
    Left, Right, Bottom, Top

  PanelSize* = object
    ratio*:     Option[float]   # 0.0..1.0
    px*:        Option[int]     # absolute pixels
    visiblePx*: Option[int]     # edge sliver when collapsed
    minPx*:     Option[int]
    maxPx*:     Option[int]

  ProfileSizes* = array[SidebarState, Option[PanelSize]]

  SidebarInstance* = object
    id*:         InstanceId
    position*:   SidebarPosition
    state*:      SidebarState
    windowIds*:  seq[WindowId]
    hidden*:     bool

# ─── actions ─────────────────────────────────────
type
  ActionKind* = enum
    akShellCmd, akNiriAction, akKanataFakeKey, akInternalRpc

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
    naFocusWindow, naCloseWindow, naSetColumnWidth,
    naMoveToFloating, naMoveToWorkspace

  NiriActionSpec* = object
    case kind*: NiriActionKind
    of naFocusWindow:   focusWindowId*: WindowId
    of naCloseWindow:   closeWindowId*: WindowId
    of naSetColumnWidth: widthChange*: string
    of naMoveToFloating: floatWindowId*: WindowId
    of naMoveToWorkspace:
      moveWindowId*: WindowId
      moveWorkspaceId*: WorkspaceId

# ─── commands ────────────────────────────────────
type
  KeyToken* = distinct string

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

# ─── profile ─────────────────────────────────────
type
  Profile* = object
    id*:          ProfileId
    pluginId*:    PluginId
    title*:       string
    kanataLayer*: Option[string]
    sizes*:       ProfileSizes
    commands*:    seq[Command]
    workspaceMatch*: Option[string]  # reserved: regex for workspace name

# ─── resolved runtime state ─────────────────────
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
    available*:    seq[Command]
    nextKeys*:     seq[KeyToken]
    exactMatch*:   Option[Command]

  ShellState* = object
    windows*:        Table[WindowId, NiriWindow]
    focusedWindowId*: Option[WindowId]
    instances*:      Table[InstanceId, SidebarInstance]
    activeInstance*:  Option[InstanceId]
    ownership*:      Table[WindowId, InstanceId]
    resolved*:       Option[ResolvedProfile]
    keymap*:         KeymapState
    kanataConnected*: bool
    kanataLayer*:     string
    config*:         SidebardConfig
```

#### Event model

Every input is an `Event`. Events carry what happened, not what to do about it.

```nim
type
  EventKind* = enum
    # niri
    evWindowOpened, evWindowChanged, evWindowClosed
    evWindowFocused, evWorkspaceActivated
    # kanata
    evKanataConnected, evKanataDisconnected
    evKanataLayerChanged, evKanataMessage
    # sidebar (from niri-sidebar state files or future IPC)
    evSidebarStateRead
    # user interaction (via RPC)
    evActivateInstance, evToggleVisibility
    evPrefixAdvance, evPrefixReset
    evFilterSet, evCommandInvoked
    # system
    evConfigReloaded, evTimerFired

  Event* = object
    ts*: MonoTime
    case kind*: EventKind
    of evWindowOpened, evWindowChanged: window*: NiriWindow
    of evWindowClosed:                 closedWindowId*: WindowId
    of evWindowFocused:                focusedId*: Option[WindowId]
    of evWorkspaceActivated:
      workspaceId*: WorkspaceId
      workspaceFocused*: bool
    of evKanataConnected, evKanataDisconnected: discard
    of evKanataLayerChanged:           oldLayer*, newLayer*: string
    of evKanataMessage:                message*: string
    of evSidebarStateRead:
      sidebarInstanceId*: InstanceId
      sidebarWindows*: seq[WindowId]
      sidebarHidden*: bool
    of evActivateInstance:             targetInstance*: InstanceId
    of evToggleVisibility:             toggleInstance*: InstanceId
    of evPrefixAdvance:                key*: KeyToken
    of evPrefixReset:                  discard
    of evFilterSet:                    filterText*: string
    of evCommandInvoked:               commandId*: CommandId
    of evConfigReloaded:               newConfig*: SidebardConfig
    of evTimerFired:                   timerId*: string
```

#### Effect model

The reducer returns effects — descriptions of what should happen. The runtime interprets them.

```nim
type
  EffectKind* = enum
    efChangeKanataLayer, efExecuteAction, efStartTimer
    efCancelTimer, efNotifySubscribers, efNiriAction

  Effect* = object
    case kind*: EffectKind
    of efChangeKanataLayer: layer*: string
    of efExecuteAction:     action*: ActionSpec
    of efStartTimer:        timerId*: string; durationMs*: int
    of efCancelTimer:       cancelTimerId*: string
    of efNotifySubscribers: discard
    of efNiriAction:        niriAction*: NiriActionSpec
```

#### The reducer

Deterministic. I/O-free. Mutates state in place. Returns effects.

```nim
proc reduce*(state: var ShellState, event: Event): seq[Effect] =
  result = @[]
  case event.kind
  of evWindowOpened, evWindowChanged:
    state.windows[event.window.id] = event.window
  of evWindowClosed:
    state.windows.del(event.closedWindowId)
    state.ownership.del(event.closedWindowId)
  of evWindowFocused:
    state.focusedWindowId = event.focusedId
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
  # ... every EventKind handled
```

#### Profile resolution

Simple, flat, deterministic. Two-level merge only (plugin + instance override).

1. If focused window is owned by a sidebar → find matching plugin by `matchAppIds`
2. If no match → use active sidebar's default plugin
3. If no active sidebar → return none

The resolved profile determines: which `PanelSize` applies, which commands are available, which `kanataLayer` is active, what the keymap trie contains.

#### Keymap engine

A trie of key sequences, rebuilt when the active profile changes.

```nim
type
  TrieNode = object
    children: Table[KeyToken, TrieNode]
    commandIds: seq[CommandId]

proc buildTrie*(commands: seq[Command]): TrieNode
proc advance*(state: var KeymapState, key: KeyToken)
proc filter*(state: var KeymapState, text: string)
proc reset*(state: var KeymapState)
```

After any change, the keymap state contains:
- `available` — commands reachable from current prefix + matching filter
- `nextKeys` — valid next keypresses (ordered for stable UI)
- `exactMatch` — if prefix exactly completes one command

#### Public RPC types (`core/api_types.nim`)

Stable contract. Internal types can evolve independently. Conversion procs bridge them.

```nim
type
  ApiWindow* = object
    id*: uint64; appId*, title*: Option[string]
    workspaceId*: Option[uint64]; isFocused*, isFloating*: bool

  ApiSidebarInstance* = object
    id*, position*, state*: string
    windowIds*: seq[uint64]; hidden*: bool

  ApiCommand* = object
    id*, title*, description*, category*: string
    tags*, sequence*: seq[string]; dangerous*: bool

  ApiKeymapState* = object
    profileId*: string; prefix*: seq[string]; filter*: string
    available*: seq[ApiCommand]; nextKeys*: seq[string]
    exactMatch*: Option[ApiCommand]

  ApiResolvedProfile* = object
    profileId*, pluginId*, title*, instanceId*, state*: string
    kanataLayer*: Option[string]

  ApiStateSnapshot* = object
    focusedWindowId*: Option[uint64]; activeInstance*: Option[string]
    resolved*: Option[ApiResolvedProfile]; keymap*: ApiKeymapState
    kanataConnected*: bool; kanataLayer*: string
```

#### JSON-RPC interface

Unix socket, newline-framed JSON-RPC 2.0.

**Queries:** `state`, `profile`, `keymap`, `commands`, `instances`, `windows`

**Actions:** `activate`, `toggle`, `prefix.advance`, `prefix.reset`, `filter`, `run`, `reload`

**Subscriptions:** `subscribe(topics)` → push notifications. Topics: `state`, `keymap`, `profile`, `instances`.

Notifications are topic-filtered — a which-key popup subscribing to `"keymap"` only receives `notify.keymap`.

#### CLI interface

```
sidebard daemon                  # start daemon
sidebard state                   # full state snapshot
sidebard profile                 # resolved profile
sidebard keymap                  # keymap state
sidebard commands                # all commands for active profile
sidebard activate <instance>     # set active sidebar
sidebard toggle <instance>       # toggle visibility
sidebard prefix advance <key>    # push key onto prefix
sidebard prefix reset            # clear prefix
sidebard filter <text>           # set command filter
sidebard run <command-id>        # execute command
sidebard reload                  # reload config
sidebard watch <topic>           # stream notifications
sidebard repair                  # repair ownership state
```

All queries accept `--json` (default) and `--pretty`. `sidebard watch` subscribes and streams to stdout for piping into renderers or debugging.

#### Prefix tracking via Kanata

Kanata config includes `cmd` actions on leader keys:

```kbd
(defalias
  leader (multi
    (layer-while-held leader-layer)
    (cmd sidebard prefix advance Leader)))
```

Kanata runs `sidebard prefix advance Leader` → RPC to daemon → `evPrefixAdvance` → keymap updates → subscribers notified. Sidebard stays out of the keypress path. Kanata is the authority on what physical keys do.

#### Niri adapter interface

```nim
type
  NiriAdapter* = ref object
    conn: AsyncSocket

proc connect*(): Future[Result[NiriAdapter, string]]
proc listWindows*(n: NiriAdapter): Future[Result[seq[NiriWindow], string]]
proc focusedWindow*(n: NiriAdapter): Future[Result[Option[NiriWindow], string]]
proc eventStream*(n: NiriAdapter): Future[Result[void, string]]
proc readEvent*(n: NiriAdapter): Future[Result[Event, string]]
proc executeAction*(n: NiriAdapter, action: NiriActionSpec): Future[Result[void, string]]
```

Internally wraps `nimri-ipc`'s `NiriClient` and `NiriEventStream`, translating their types into sidebard's domain events.

#### Kanata adapter

TCP to `host:port` (default `127.0.0.1:6666`). Sends `ChangeLayer`, `ActOnFakeKey`, `RequestLayerNames`. Receives `LayerChange`, `ConfigFileReload`.

Graceful degradation: if Kanata is unavailable, log warning, retry periodically, skip `efChangeKanataLayer` effects. Everything else works normally.

#### Daemon lifecycle

```
1. Load config from TOML hierarchy
2. Connect to niri socket (via nimri-ipc)
3. Request Windows + FocusedWindow → seed state
4. Read sidebar state.json files → seed ownership (compatibility adapter)
5. Resolve initial profile
6. Start niri event stream
7. Connect to Kanata (non-fatal if unavailable)
8. Start JSON-RPC server on Unix socket
9. Enter event loop:
   forever:
     event = await nextEvent(niriStream, kanataStream, rpcServer, timers)
     effects = reduce(state, event)
     for eff in effects: execute(eff)
```

Single-threaded, single event loop, no locks. Chronos handles async multiplexing. Stateless across restarts — rehydrates from Niri + state files on startup.

---

### 4.3 `nirip` — declarative workspace orchestrator

On-demand CLI. Core model: **snapshot → plan → execute → confirm → replan.**

**Owns:**
- Declarative workspace profile loading and validation
- Compositional window matching
- Pure planning (desired vs actual → operations)
- Freeze/export generation
- Event-confirmed execution against Niri
- Advisory managed-state persistence

**Philosophy:**

1. **Declarative workspace orchestration.** A profile is a complete description of a workspace layout. `nirip load` reconciles reality toward it. The profile is the source of truth.
2. **Pure planning, effectful execution.** The planner is a pure function: `plan(desired, actual) → operations`. No I/O, no async. The executor is the only component that touches Niri IPC.
3. **Compositor-level only.** Nirip restores what Niri controls: workspaces, columns, windows, positions, sizes. Application-internal state is out of scope.
4. **Explicit over automatic.** No background daemon. No implicit restore. The user explicitly loads and freezes. Dangerous operations require opt-in.
5. **Idempotent by design.** Running `nirip load` twice produces the same result. Already-matched windows aren't re-launched. Already-correct columns aren't moved.

#### Domain types (`core/types.nim`)

```nim
import std/[options, tables, times]
import results
import nimri_ipc

type
  ProfileName*   = distinct string
  WorkspaceName* = distinct string
  WindowRole*    = distinct string   # "editor", "terminal", "browser"
  ColumnRole*    = distinct string   # "main", "tools", "reference"
  OutputAlias*   = distinct string   # "primary", "laptop"

# ─── profile model ───────────────────────────────
type
  ProfileOptions* = object
    matchExisting*:    bool          # try to match running windows before launching
    launchMissing*:    bool          # spawn windows that don't match
    moveUnmanaged*:    bool          # move non-profile windows out of the way
    closeExtra*:       bool          # close windows from prior load not in profile
    timeoutMs*:        int           # max wait for window to appear
    focusAfterLoad*:   Option[string] # "workspace:column/window" path

  OutputAliases* = Table[OutputAlias, seq[string]]

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
    cdNormal, cdTabbed

  SizeSpec* = object
    case kind*: SizeKind
    of skProportion: ratio*: float   # 0.0..1.0
    of skPixels:     px*: int

  SizeKind* = enum
    skProportion, skPixels

  WindowSpec* = object
    id*:          WindowRole
    command*:     Option[seq[string]]
    cwd*:         Option[string]
    env*:         Table[string, string]
    match*:       MatchRule
    height*:      Option[SizeSpec]
    floating*:    bool

# ─── match rules (compositional) ─────────────────
type
  MatchRuleKind* = enum
    mrExactAppId, mrRegexAppId, mrExactTitle, mrRegexTitle
    mrWorkspaceName, mrPidFromSpawn, mrOpenedAfter
    mrAll, mrAny, mrNot

  MatchRule* = ref object
    case kind*: MatchRuleKind
    of mrExactAppId:    appId*: string
    of mrRegexAppId:    appIdPattern*: string
    of mrExactTitle:    title*: string
    of mrRegexTitle:    titlePattern*: string
    of mrWorkspaceName: workspace*: string
    of mrPidFromSpawn:  discard
    of mrOpenedAfter:   afterTs*: MonoTime
    of mrAll:           allRules*: seq[MatchRule]
    of mrAny:           anyRules*: seq[MatchRule]
    of mrNot:           negated*: MatchRule

  MatchResult* = object
    matched*: bool
    explanation*: seq[string]

  MatchContext* = object
    spawnTimestamps*: Table[WindowRole, MonoTime]
    launchedPids*: Table[WindowRole, int]
    workspaceNames*: Table[nimri_ipc.WorkspaceId, string]
```

`MatchRule` is `ref object` for recursive composition without value-type issues.

**TOML representation:** Flat fields become implicit `All(...)`. Explicit `any`/`not` keys enable composition when needed. 90% of profiles never need compositional forms.

```toml
# Simple (most common)
[windows.editor.match]
app_id = "code"
title_regex = "backend"
# → All(ExactAppId("code"), RegexTitle("backend"))

# Explicit composition
[windows.browser.match]
any = [
  { app_id_regex = "(?i)chrome|chromium" },
  { app_id_regex = "(?i)firefox" },
]
title_regex = "localhost"
# → All(Any(RegexAppId("chrome|chromium"), RegexAppId("firefox")), RegexTitle("localhost"))
```

#### Operations

```nim
type
  OpKind* = enum
    opEnsureWorkspace, opMoveWorkspaceToOutput, opMoveWorkspaceToIndex
    opSpawnWindow, opWaitForWindow, opMatchExistingWindow
    opMoveWindowToWorkspace, opMoveWindowToTiling, opMoveWindowToFloating
    opConsumeIntoColumn, opMoveColumnToIndex
    opSetColumnWidth, opSetWindowHeight, opSetColumnDisplay
    opFocusWindow, opFocusWorkspace

  FocusReq* = enum
    frNone, frWindow, frColumn

  Operation* = object
    focusReq*: FocusReq
    focusTarget*: Option[nimri_ipc.WindowId]
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
      mtwWindow*: nimri_ipc.WindowId
      mtwWorkspace*: WorkspaceName
    of opMoveWindowToTiling:  mttWindow*: nimri_ipc.WindowId
    of opMoveWindowToFloating: mtfWindow*: nimri_ipc.WindowId
    of opConsumeIntoColumn:
      cicWindow*: nimri_ipc.WindowId
      cicTarget*: nimri_ipc.WindowId
    of opMoveColumnToIndex:
      mciWindow*: nimri_ipc.WindowId
      mciIndex*: int
    of opSetColumnWidth:
      scwWindow*: nimri_ipc.WindowId
      scwSize*: SizeSpec
    of opSetWindowHeight:
      swhWindow*: nimri_ipc.WindowId
      swhSize*: SizeSpec
    of opSetColumnDisplay:
      scdWindow*: nimri_ipc.WindowId
      scdDisplay*: ColumnDisplay
    of opFocusWindow:    fwWindow*: nimri_ipc.WindowId
    of opFocusWorkspace: fwsName*: WorkspaceName

  PlanResult* = object
    operations*: seq[Operation]
    matchedWindows*: Table[WindowRole, nimri_ipc.WindowId]
    unmatchedRoles*: seq[WindowRole]
    warnings*: seq[string]
```

Each operation carries a `FocusReq` so the executor can handle focus-sensitive Niri actions generically (check → focus → verify → execute → verify).

#### The planner (pure)

```nim
proc plan*(profile: Profile, state: NiriSnapshot,
           managed: ManagedState): PlanResult =
  ## Pure function. No I/O.
  ## Strategy:
  ## 1. Ensure all workspaces exist
  ## 2. Match existing windows to profile roles
  ## 3. Plan launches for unmatched roles (if launch_missing)
  ## 4. Plan moves for matched windows not in correct workspace
  ## 5. Plan column formation (consume, ordering)
  ## 6. Plan sizing (column width, window height)
  ## 7. Plan focus
```

Runs multiple times during a load. Each run re-evaluates from current state. Already-satisfied operations are dropped.

#### The executor (async)

```nim
proc execute*(client: NiriClient, plan: PlanResult,
              events: NiriEventStream): Future[ExecuteResult] {.async.} =
  ## Executes operations one at a time.
  ## After each: wait for confirming event or timeout.
  ## If state diverges: re-invoke planner.

proc ensureFocus*(client: NiriClient, events: NiriEventStream,
                  op: Operation): Future[Result[void, string]] {.async.} =
  ## If op.focusReq != frNone:
  ##   Focus target → wait for WindowFocusChanged → verify
```

Event-stream-driven confirmation via `nimri-ipc.waitFor` — faster and more reliable than polling.

#### The matcher (pure)

```nim
proc evaluate*(rule: MatchRule, window: nimri_ipc.Window,
               context: MatchContext): MatchResult =
  ## Recursively evaluate. Returns matched + explanation trace.

proc findMatches*(rule: MatchRule, windows: seq[nimri_ipc.Window],
                  context: MatchContext): seq[RankedMatch] =
  ## Evaluate against all candidates. Sorted by specificity, ties by recency.
```

#### The freezer (pure)

```nim
proc freeze*(state: NiriSnapshot, options: FreezeOptions,
             managed: Option[ManagedState]): Profile =
  ## Niri state → Profile.
  ## 1. Select workspaces (named by default, all if --all)
  ## 2. Group windows by column index (posInScrollingLayout)
  ## 3. Order within columns by tile index
  ## 4. Generate match rules from appId + title
  ## 5. Annotate launch commands from managed state
  ## 6. Generate column widths from layout data
```

#### State file

Lightweight JSON at `$XDG_STATE_HOME/nirip/state.json`. Advisory — never authoritative over Niri.

```nim
type
  ManagedWindow* = object
    role*: WindowRole
    niriId*: Option[nimri_ipc.WindowId]
    pid*: Option[int]
    launchCommand*: Option[seq[string]]
    matchedAt*: string

  LoadedProfile* = object
    name*: ProfileName
    loadedAt*: string
    windows*: Table[WindowRole, ManagedWindow]

  ManagedState* = object
    profiles*: Table[ProfileName, LoadedProfile]
```

Updated after `load` (record), after `close` (remove). Dead windows pruned on read.

#### CLI interface

```
nirip load <profile>             # reconcile toward profile
nirip plan <profile>             # dry-run: show what load would do
nirip freeze [options]           # capture current state as profile
nirip diff <profile>             # compare profile vs current state
nirip doctor <profile>           # validate profile, check environment
nirip list                       # list known profiles
nirip close <profile>            # close managed windows
nirip status                     # show loaded profiles + managed windows
```

Flags: `--json`, `--pretty`, `--workspace <name>`, `--force`, `--verbose`, `--sidebard`

#### Diagnostics output

**`nirip plan`:**
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
  ...
```

**`nirip diff`:**
```
backend:code
  editor       ✓  correct workspace, column 1, width ~0.62
  shell        ~  expected column 2, actual column 3 (drifted)
backend:web
  browser      ✗  missing (not running)

Summary: 1 ok, 1 drifted, 1 missing
```

**`nirip doctor`:**
```
Config:    ✓ profile.toml valid  ✓ code.toml valid
Environment: ✓ $NIRI_SOCKET exists  ✓ Output "DP-1" present
Windows:   ✓ "code" on PATH  ✓ "ghostty" on PATH
Match rules: ✓ All regexes compile
             ⚠ editor.match has no title_regex — may match wrong window
```

---

## 5. Configuration

### 5.1 `sidebard` config

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

Merge: `config.toml` → `plugins/*.toml` → `instances/*.toml`. Scalars: last writer wins. Sequences: replace. Tables: recursive merge.

**`config.toml`:**
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

**`plugins/chat.toml`:**
```toml
id = "chat"
title = "Chat"
priority = 200
match_app_ids = ['^vesktop$', '^org\.telegram\.desktop$']

[profile]
title = "Chat"
kanata_layer = "sidebar-chat"

[profile.sizes.collapsed]
visible_px = 30

[profile.sizes.active]
ratio = 0.34

[[commands]]
id = "chat.quick_reply"
title = "Quick reply"
description = "Reply to the selected conversation"
category = "messaging"
tags = ["reply", "chat"]
sequence = ["Leader", "R"]
when_states = ["active", "focused"]
action = { shell = "sidebard-action chat quick-reply" }
```

**`instances/right.toml`:**
```toml
id = "right"
position = "right"
default_plugin = "chat"

[overrides.chat.sizes.active]
ratio = 0.38
```

**Action format:** Actions are typed inline tables dispatched to `ActionSpec` variants:
```toml
action = { shell = "command --flag" }
action = { niri = "FocusWindow", window_id = 42 }
action = { kanata_key = "vk-reply", key_action = "Tap" }
action = { rpc = "toggle", args = "left" }
```

### 5.2 `nirip` config

```
~/.config/nirip/
├── config.toml                  # global settings + output aliases
└── profiles/
    ├── backend-dev/             # directory-based profile
    │   ├── profile.toml         # metadata + options
    │   ├── code.toml            # workspace spec
    │   └── web.toml             # workspace spec
    └── personal.toml            # single-file profile
```

Both directory and single-file formats supported. Loader detects based on path type.

**`config.toml`:**
```toml
[defaults]
timeout_ms = 20000
match_existing = true
launch_missing = true

[outputs]
primary = ["DP-1", "DP-2", "eDP-1"]
laptop = ["eDP-1"]

[sidebard]
socket = "/run/user/1000/sidebard.sock"
query_ownership = true
```

**Directory profile (`backend-dev/profile.toml`):**
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
```

**Workspace spec (`backend-dev/code.toml`):**
```toml
[workspace]
name = "backend:code"
output = "primary"
index = 1
focus = "editor"

[[columns]]
id = "main"
width = 0.62

[[columns.windows]]
id = "editor"
command = ["code", "~/src/backend"]

[columns.windows.match]
app_id = "code"
title_regex = "backend"

[[columns]]
id = "tools"
width = 0.38

[[columns.windows]]
id = "shell"
command = ["ghostty", "--working-directory", "~/src/backend"]

[columns.windows.match]
app_id = "com.mitchellh.ghostty"
```

**Single-file profile (`personal.toml`):**
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
```

---

## 6. Data ownership and authority

| Domain | Authority | Persistence |
|---|---|---|
| `nimri-ipc` | Protocol types and transport | None |
| `sidebard` | Semantic session interpretation | In-memory (rehydrated on startup) |
| `nirip` | Desired layout profiles | TOML files (config) + JSON file (advisory state) |
| Niri | Compositor ground truth | Always wins over cached state |
| `niri-sidebar` | v1 compatibility backend | `state.json` files (imported by sidebard) |

---

## 7. `niri-sidebar` compatibility strategy

### v1
- `sidebard` hydrates ownership and instance state from `niri-sidebar` `state.json` files
- `niri-sidebar` continues to perform actual sidebar stack geometry (floating, hide/peek, flip, reorder)
- `sidebard` treats it as a compatibility adapter

### v2
- `sidebard` becomes the semantic authority for membership and instance state
- `niri-sidebar` becomes a geometry backend

### v3
- Decide: keep `niri-sidebar` for geometry only, replace with sidebard-native engine, or split into dedicated renderer/backend

---

## 8. Repository and package layout

```
nimri-ipc/      # shared Nim library (nimble package)
sidebard/       # daemon + CLI client
nirip/          # orchestrator CLI
```

### `nimri-ipc`

```
src/nimri_ipc/
  nimri_ipc.nim          # re-exports all modules
  models.nim             # Window, Workspace, Output, WindowLayout, etc.
  actions.nim            # 100+ typed action constructors
  requests.nim           # NiriRequest/NiriResponse variants
  events.nim             # NiriEvent variants + predicates
  client.nim             # NiriClient: async command client
  stream.nim             # NiriEventStream: async event stream
  errors.nim             # NimriIpcError + constructors
  codec.nim              # TaggedVariant, FrameBuffer, field helpers
  internal/
    transport.nim         # NiriConnectConfig, socket connect/read/write
```

### `sidebard`

```
src/
  sidebard.nim           # entry point: daemon or CLI mode
  cli.nim                # CLI subcommands via cligen
  core/                  # pure domain — zero I/O
    types.nim            # all domain types (internal)
    api_types.nim        # public RPC types (stable contract)
    config.nim           # TOML → typed config
    state.nim            # ShellState + reduce() + Effect
    ownership.nim        # window-to-sidebar tracking
    profile.nim          # profile resolution
    keymap.nim           # command trie, prefix, filtering
  adapters/              # I/O boundary — async
    niri.nim             # niri socket (wraps nimri-ipc)
    kanata.nim           # kanata TCP
    rpc.nim              # JSON-RPC server/client
    sidebar_compat.nim   # niri-sidebar state.json reader
```

### `nirip`

```
src/
  nirip.nim              # entry point: CLI dispatch
  cli.nim                # CLI subcommands via cligen
  core/                  # pure domain — zero I/O
    types.nim            # profile, match, operation types
    config.nim           # TOML → typed profile, validation
    matcher.nim          # match rule evaluation
    planner.nim          # plan(desired, actual) → seq[Operation]
    freezer.nim          # niri state → profile
    diagnostics.nim      # explain, format, diff
  executor/              # async I/O
    runner.nim           # operation loop with event confirmation
    launcher.nim         # spawn processes, track PIDs
    focus.nim            # focus management for focus-sensitive ops
  state/
    managed.nim          # active profiles + managed windows (JSON)
  integrations/
    sidebard_rpc.nim     # optional sidebard queries for ownership
```

---

## 9. Dependencies

### `nimri-ipc`

| Package | Purpose |
|---|---|
| nim >= 2.0.0 | Language |
| results | `Result[T, E]` — explicit errors |
| Nim stdlib | options, tables, json, asyncdispatch, asyncnet, os, times |

### `sidebard`

| Package | Purpose |
|---|---|
| nimri-ipc | Niri protocol |
| chronos | Async runtime |
| nim-results | `Result[T, E]` |
| jsony | Fast JSON serialization |
| toml-serialization | TOML config loading |
| nim-json-rpc | JSON-RPC 2.0 server/client |
| cligen | CLI from proc signatures |
| chronicles | Structured logging |

### `nirip`

| Package | Purpose |
|---|---|
| nimri-ipc | Niri protocol |
| chronos | Async runtime (executor) |
| nim-results | `Result[T, E]` |
| jsony | JSON serialization |
| toml-serialization | TOML profile loading |
| cligen | CLI from proc signatures |
| chronicles | Structured logging |

---

## 10. Design invariants

These are enforced in tests and never violated.

1. **`nimri-ipc` has no session semantics.** It owns protocol types and transport only.
2. **`sidebard.reduce()` is deterministic and I/O-free.** It mutates `var ShellState` in place but produces no observable side effects beyond `seq[Effect]`.
3. **`nirip.plan()` is deterministic and I/O-free.** Given the same inputs, it produces the same plan.
4. **`sidebard` never silently mutates workspace layout state.**
5. **`nirip` never silently mutates shell/profile/keymap semantics.**
6. **Niri state always wins over cached state files.**
7. **Ownership is exclusive.** A window belongs to at most one sidebar instance.
8. **`nirip load` is idempotent.** Running it when the desktop matches produces zero operations.
9. **`nirip freeze` is pure with respect to its inputs.**
10. **Matching is deterministic.** Same rule + same window → same result.
11. **Operations are typed and exhaustive.** The executor handles every `OpKind`.
12. **Focus-sensitive operations verify.** The executor never assumes focus landed correctly.
13. **No implicit destructive actions.** Windows never closed unless explicitly opted in.
14. **One active profile at a time** (sidebard). Even if multiple sidebars are visible.
15. **Effects are ordered.** Effects from a single reduce call execute in list order.
16. **Events are total.** The reducer handles every `EventKind`. No silently dropped events.
17. **Public RPC and CLI contracts are versioned and stable within major versions.**

---

## 11. Delivery plan

### Phase 1 — Finish `nimri-ipc`

Complete the stable protocol layer:
- Add snapshot helper
- Add event filtering convenience procs
- Comprehensive tests against captured JSON fixtures
- Publish as nimble package

**Ships:** `nimri-ipc` v0.1.0

### Phase 2 — Build `sidebard` skeleton

- Niri adapter (wrapping nimri-ipc)
- Compatibility adapter for niri-sidebar state.json
- Core types, reducer, state
- Basic event loop: connect → events → reduce → log

**Ships:** `sidebard daemon` that logs niri events and maintains state

### Phase 3 — `sidebard` config + profiles + RPC

- TOML config loading
- Profile resolution from focus context
- JSON-RPC server with queries, actions, subscriptions
- CLI subcommands as RPC clients

**Ships:** Full `sidebard` CLI. External tools can query and control shell state.

### Phase 4 — `sidebard` keymap + Kanata

- Keymap trie, prefix tracking, text filtering
- Kanata adapter with layer switching
- `sidebard watch keymap` for UI consumers

**Ships:** Full keyboard integration. Which-key UIs possible.

### Phase 5 — Build `nirip` core

- Config loader (both single-file and directory profiles)
- Matcher (compositional rule evaluation)
- Freezer (Niri snapshot → profile TOML)
- `nirip freeze`, `nirip doctor`, `nirip list`

**Ships:** Profile creation and validation without reconciliation

### Phase 6 — `nirip` planner + basic executor

- Pure planner
- Sequential executor (workspace creation, window matching, basic moves)
- `nirip plan`, `nirip load` (workspaces + placement, no column formation)

**Ships:** Working `nirip load` for basic layouts

### Phase 7 — `nirip` column formation + sizing

- Consume windows into columns, order columns, set widths/heights
- Focus management for focus-sensitive operations
- `nirip diff`

**Ships:** Full `nirip load` with column arrangement

### Phase 8 — `nirip` event-stream executor + state

- Replace poll-based with event-stream-driven confirmation
- Managed-state file for window tracking
- `nirip close`, `nirip status`

**Ships:** Faster, more reliable reconciliation with lifecycle management

### Phase 9 — Integration

- `nirip` queries `sidebard` for ownership exclusions (`--sidebard` flag)
- `sidebard` can invoke `nirip load/close` as command targets
- Decide on sidebar authority migration timeline

**Ships:** The tools work together without stepping on each other

This order minimizes rework: both upper layers stabilize on one IPC substrate first, then build independently, then integrate.

---

## 12. Nix integration

### `nimri-ipc` package

```nix
nimPackages.buildNimPackage {
  pname = "nimri-ipc";
  version = "0.1.0";
  src = ./.;
}
```

### `sidebard` package + Home Manager module

```nix
# Package
nimPackages.buildNimPackage {
  pname = "sidebard";
  version = "0.1.0";
  src = ./.;
  propagatedNimDeps = [ nimri-ipc ];
}

# Home Manager
systemd.user.services.sidebard = {
  Unit.Description = "sidebard shell daemon";
  Unit.After = [ "graphical-session.target" ];
  Service.ExecStart = "${pkgs.sidebard}/bin/sidebard daemon";
  Service.Restart = "on-failure";
  Install.WantedBy = [ "graphical-session.target" ];
};
```

TOML config files generated from Nix module options at build time.

### `nirip` package + Home Manager module

```nix
# Package
nimPackages.buildNimPackage {
  pname = "nirip";
  version = "0.1.0";
  src = ./.;
  propagatedNimDeps = [ nimri-ipc ];
}
```

Profile TOML files generated from Nix module options. Two profile sources:
1. **Nix-managed** (`~/.config/nirip/profiles/`) — immutable, generated
2. **User profiles** (`~/.local/share/nirip/profiles/`) — editable, from freeze

---

## 13. What this intentionally excludes (v1)

- **Application-internal state.** No browser tabs, editor buffers, terminal sessions.
- **Background daemon for nirip.** No auto-save, no login restore. Explicit commands only.
- **Dynamic plugins.** A plugin is a TOML file. No script runtimes.
- **Renderer/UI surfaces.** Sidebard is the state daemon. UIs consume its RPC.
- **Fuzzy matching.** Match rules are boolean. Write a more specific rule.
- **Floating window geometry.** Niri doesn't expose precise floating coordinates.
- **Profile inheritance/templates.** v1 profiles are self-contained. Templates are v2+.
- **Multi-monitor awareness in sidebard.** `OutputId` reserved in types but not wired in resolution.
- **Workspace-scoped commands.** `workspaceMatch` reserved but not wired in v1.

---

## 14. Final statement

**Nimri is a layered control plane for Niri.** `nimri-ipc` provides a typed transport and model foundation that already exists and is feature-complete for protocol concerns. `sidebard` continuously interprets live compositor context into shell semantics and exposes them over RPC. `nirip` explicitly reconciles the compositor toward declarative workspace profiles through pure planning and event-confirmed execution. `niri-sidebar` is incorporated initially as a compatibility backend while long-term authority migrates into `sidebard`. The result is a system that is reactive at runtime, declarative when desired, and cleanly separated at every boundary.
