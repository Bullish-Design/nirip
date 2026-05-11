# Sidebard Implementation Guide

A step-by-step guide for implementing the sidebard reactive shell daemon from scratch.

---

## Prerequisites

Before starting, ensure you have:

- **Nim >= 2.0.0** installed and on PATH
- **nimble** package manager (ships with Nim)
- **A running Niri compositor** with `$NIRI_SOCKET` set
- **The `nimri-ipc` library** cloned locally at `../nimri-ipc` (or installed via nimble)
- Familiarity with Nim's variant objects, `Option`, `Result`, and async/await
- Read the `FINAL_CONCEPT.md` in this directory — it is the architectural source of truth

### Key dependencies to install

| Package | Purpose | Install |
|---|---|---|
| chronos | Async runtime | `nimble install chronos` |
| nim-results | `Result[T, E]` | `nimble install results` |
| jsony | JSON serialization | `nimble install jsony` |
| toml-serialization | TOML config loading | `nimble install toml_serialization` |
| nim-json-rpc | JSON-RPC 2.0 | `nimble install json_rpc` |
| cligen | CLI generation | `nimble install cligen` |
| chronicles | Structured logging | `nimble install chronicles` |

---

## Repository setup

### Step 1: Create the project

```bash
mkdir sidebard && cd sidebard
nimble init
```

Edit `sidebard.nimble`:

```nim
# Package
version       = "0.1.0"
author        = "andrew"
description   = "Reactive shell daemon for Niri compositor"
license       = "MIT"
srcDir        = "src"
bin           = @["sidebard"]

# Dependencies
requires "nim >= 2.0.0"
requires "results >= 0.4.0"
requires "chronos >= 4.0.0"
requires "jsony >= 1.1.0"
requires "toml_serialization >= 0.2.0"
requires "json_rpc >= 0.4.0"
requires "cligen >= 1.7.0"
requires "chronicles >= 0.10.0"
requires "nimri_ipc >= 0.1.0"
```

### Step 2: Create the directory structure

```bash
mkdir -p src/core
mkdir -p src/adapters
mkdir -p tests
mkdir -p tests/fixtures
```

Target layout:

```
src/
├── sidebard.nim             # entry point
├── cli.nim                  # CLI subcommands
├── core/
│   ├── types.nim            # internal domain types
│   ├── api_types.nim        # public RPC types (stable contract)
│   ├── config.nim           # TOML config loading
│   ├── state.nim            # ShellState + reduce() + Effect
│   ├── ownership.nim        # window-to-sidebar tracking
│   ├── profile.nim          # profile resolution
│   └── keymap.nim           # command trie, prefix, filtering
├── adapters/
│   ├── niri.nim             # niri socket (wraps nimri-ipc)
│   ├── kanata.nim           # kanata TCP
│   ├── rpc.nim              # JSON-RPC server + client mode
│   └── sidebar_compat.nim   # niri-sidebar state.json reader
tests/
├── test_types.nim
├── test_state.nim
├── test_ownership.nim
├── test_profile.nim
├── test_keymap.nim
├── test_config.nim
└── fixtures/
    ├── niri_windows.json
    ├── niri_events.json
    ├── config.toml
    ├── plugins/
    │   └── chat.toml
    └── instances/
        └── right.toml
```

---

## Implementation phases

The phases below are ordered so that each builds on the previous. Do not skip ahead — each phase has a "prove it works" checkpoint.

---

## Phase 1: Core types (`core/types.nim`)

This is the foundation. Every other module imports from here. Get the types right and the rest follows.

### Step 1.1: Identifiers

Create `src/core/types.nim`. Start with distinct ID types:

```nim
import std/[options, sets, tables, times, hashes]
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
```

You **must** define `==`, `hash`, and `$` for each distinct type so they work in `Table`, `HashSet`, and logging:

```nim
proc `==`*(a, b: WindowId): bool {.borrow.}
proc hash*(a: WindowId): Hash {.borrow.}
proc `$`*(a: WindowId): string {.borrow.}

proc `==`*(a, b: WorkspaceId): bool {.borrow.}
proc hash*(a: WorkspaceId): Hash {.borrow.}
proc `$`*(a: WorkspaceId): string {.borrow.}

# For string-based distinct types:
proc `==`*(a, b: OutputId): bool {.borrow.}
proc hash*(a: OutputId): Hash {.borrow.}
proc `$`*(a: OutputId): string {.borrow.}

proc `==`*(a, b: InstanceId): bool {.borrow.}
proc hash*(a: InstanceId): Hash {.borrow.}
proc `$`*(a: InstanceId): string {.borrow.}

proc `==`*(a, b: PluginId): bool {.borrow.}
proc hash*(a: PluginId): Hash {.borrow.}
proc `$`*(a: PluginId): string {.borrow.}

proc `==`*(a, b: ProfileId): bool {.borrow.}
proc hash*(a: ProfileId): Hash {.borrow.}
proc `$`*(a: ProfileId): string {.borrow.}

proc `==`*(a, b: CommandId): bool {.borrow.}
proc hash*(a: CommandId): Hash {.borrow.}
proc `$`*(a: CommandId): string {.borrow.}
```

### Step 1.2: Compositor model

These types represent what sidebard knows about Niri's window state. Note: these are **sidebard's internal model**, not `nimri-ipc`'s types directly. The adapter converts between them.

```nim
type
  NiriWindow* = object
    id*: WindowId
    appId*: Option[string]
    title*: Option[string]
    workspaceId*: Option[WorkspaceId]
    outputId*: Option[OutputId]     # reserved for multi-monitor
    isFocused*: bool
    isFloating*: bool
```

### Step 1.3: Sidebar model

```nim
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
```

### Step 1.4: Action types

```nim
type
  ActionKind* = enum
    akShellCmd
    akNiriAction
    akKanataFakeKey
    akInternalRpc

  NiriActionKind* = enum
    naFocusWindow
    naCloseWindow
    naSetColumnWidth
    naMoveToFloating
    naMoveToWorkspace

  NiriActionSpec* = object
    case kind*: NiriActionKind
    of naFocusWindow:      focusWindowId*: WindowId
    of naCloseWindow:      closeWindowId*: WindowId
    of naSetColumnWidth:   widthChange*: string
    of naMoveToFloating:   floatWindowId*: WindowId
    of naMoveToWorkspace:
      moveWindowId*: WindowId
      moveWorkspaceId*: WorkspaceId

  ActionSpec* = object
    case kind*: ActionKind
    of akShellCmd:
      shellCmd*: string
    of akNiriAction:
      niriAction*: NiriActionSpec
    of akKanataFakeKey:
      fakeKeyName*: string
      fakeKeyAction*: string
    of akInternalRpc:
      rpcMethod*: string
      rpcArgs*: string
```

### Step 1.5: Key tokens, commands, profiles

```nim
type
  KeyToken* = distinct string

proc `==`*(a, b: KeyToken): bool {.borrow.}
proc hash*(a: KeyToken): Hash {.borrow.}
proc `$`*(a: KeyToken): string {.borrow.}

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

  Profile* = object
    id*:             ProfileId
    pluginId*:       PluginId
    title*:          string
    kanataLayer*:    Option[string]
    sizes*:          ProfileSizes
    commands*:       seq[Command]
    workspaceMatch*: Option[string]
```

### Step 1.6: Resolved runtime state

```nim
type
  ResolvedProfile* = object
    profile*:    Profile
    instanceId*: InstanceId
    state*:      SidebarState
    size*:       PanelSize

  KeymapState* = object
    profileId*:  ProfileId
    prefix*:     seq[KeyToken]
    filter*:     string
    available*:  seq[Command]
    nextKeys*:   seq[KeyToken]
    exactMatch*: Option[Command]
```

### Step 1.7: Forward-declare config and shell state

You'll flesh out `SidebardConfig` in Phase 3 (config). For now, define a stub so `ShellState` compiles:

```nim
type
  SidebardConfig* = object
    daemonSocket*: string
    kanataHost*: string
    kanataPort*: int
    kanataReconnectMs*: int
    overlayTimeoutMs*: int
    collapsedVisiblePx*: int

  ShellState* = object
    # compositor
    windows*:         Table[WindowId, NiriWindow]
    focusedWindowId*: Option[WindowId]
    # sidebars
    instances*:       Table[InstanceId, SidebarInstance]
    activeInstance*:   Option[InstanceId]
    ownership*:       Table[WindowId, InstanceId]
    # profile
    resolved*:        Option[ResolvedProfile]
    # keyboard
    keymap*:          KeymapState
    # kanata
    kanataConnected*: bool
    kanataLayer*:     string
    # config
    config*:          SidebardConfig
```

### Step 1.8: Event model

```nim
type
  EventKind* = enum
    evWindowOpened
    evWindowChanged
    evWindowClosed
    evWindowFocused
    evWorkspaceActivated
    evKanataConnected
    evKanataDisconnected
    evKanataLayerChanged
    evKanataMessage
    evSidebarStateRead
    evActivateInstance
    evToggleVisibility
    evPrefixAdvance
    evPrefixReset
    evFilterSet
    evCommandInvoked
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
      oldLayer*: string
      newLayer*: string
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

### Step 1.9: Effect model

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

### Checkpoint

Write `tests/test_types.nim`:

```nim
import unittest
import core/types

suite "types":
  test "distinct IDs are type-safe":
    let w = WindowId(42)
    let i = InstanceId("left")
    check $w == "42"
    check $i == "left"
    # This should NOT compile:
    # let bad: WindowId = WorkspaceId(42)

  test "SidebarState is a closed enum":
    check SidebarState.low == Collapsed
    check SidebarState.high == Hidden

  test "ProfileSizes is enum-indexed":
    var sizes: ProfileSizes
    sizes[Active] = some(PanelSize(ratio: some(0.34)))
    check sizes[Active].isSome
    check sizes[Collapsed].isNone

  test "Event variant construction":
    let ev = Event(
      ts: getMonoTime(),
      kind: evWindowOpened,
      window: NiriWindow(id: WindowId(1), isFocused: false, isFloating: false)
    )
    check ev.kind == evWindowOpened
    check ev.window.id == WindowId(1)
```

Run: `nim c -r tests/test_types.nim`

Everything must compile and pass before proceeding.

---

## Phase 2: Ownership tracking (`core/ownership.nim`)

Ownership answers: "which sidebar instance owns this window?" It's a thin module but correctness is critical — the invariant is **exclusive ownership** (a window belongs to at most one instance).

### Step 2.1: Create `src/core/ownership.nim`

```nim
import std/[tables, options, sets]
import types

proc assignWindow*(state: var ShellState, windowId: WindowId, instanceId: InstanceId) =
  ## Assign a window to a sidebar instance.
  ## If already owned by another instance, remove from the old one first.
  let existing = state.ownership.getOrDefault(windowId)
  if existing != InstanceId("") and existing != instanceId:
    # Remove from old instance's window list
    if existing in state.instances:
      state.instances[existing].windowIds.keepItIf(it != windowId)

  state.ownership[windowId] = instanceId

  # Add to new instance's window list if not already there
  if instanceId in state.instances:
    if windowId notin state.instances[instanceId].windowIds:
      state.instances[instanceId].windowIds.add(windowId)

proc removeWindow*(state: var ShellState, windowId: WindowId) =
  ## Remove a window from ownership tracking entirely.
  let instanceId = state.ownership.getOrDefault(windowId)
  if instanceId != InstanceId(""):
    if instanceId in state.instances:
      state.instances[instanceId].windowIds.keepItIf(it != windowId)
  state.ownership.del(windowId)

proc ownerOf*(state: ShellState, windowId: WindowId): Option[InstanceId] =
  ## Return the instance that owns this window, if any.
  if windowId in state.ownership:
    some(state.ownership[windowId])
  else:
    none(InstanceId)

proc windowsOf*(state: ShellState, instanceId: InstanceId): seq[WindowId] =
  ## Return all windows owned by an instance.
  if instanceId in state.instances:
    state.instances[instanceId].windowIds
  else:
    @[]

proc repair*(state: var ShellState): seq[string] =
  ## Detect and fix ownership inconsistencies.
  ## Returns a list of repair actions taken.
  var repairs: seq[string] = @[]

  # 1. Check for windows in ownership table but not in any instance's windowIds
  for windowId, instanceId in state.ownership:
    if instanceId notin state.instances:
      repairs.add("Removed orphan ownership: window " & $windowId & " → missing instance " & $instanceId)
      state.ownership.del(windowId)
    elif windowId notin state.instances[instanceId].windowIds:
      state.instances[instanceId].windowIds.add(windowId)
      repairs.add("Added missing window " & $windowId & " to instance " & $instanceId & " windowIds")

  # 2. Check for windows in instance windowIds but not in ownership table
  for instanceId, instance in state.instances:
    for windowId in instance.windowIds:
      if windowId notin state.ownership:
        state.ownership[windowId] = instanceId
        repairs.add("Added missing ownership: window " & $windowId & " → instance " & $instanceId)

  # 3. Check for windows owned by non-existent windows
  var deadWindows: seq[WindowId] = @[]
  for windowId in state.ownership.keys:
    if windowId notin state.windows:
      deadWindows.add(windowId)
  for windowId in deadWindows:
    removeWindow(state, windowId)
    repairs.add("Removed dead window " & $windowId & " from ownership")

  repairs
```

**Important:** The `keepItIf` template may need to be written manually as a simple filter-in-place loop if your Nim version doesn't have it in `sequtils`. Alternatively, use `sugar` or write the loop explicitly:

```nim
proc removeFromSeq(s: var seq[WindowId], val: WindowId) =
  var i = 0
  while i < s.len:
    if s[i] == val:
      s.del(i)
    else:
      inc i
```

### Checkpoint

Write `tests/test_ownership.nim` covering:

- Assigning a window to an instance adds it to both `ownership` table and `windowIds`
- Re-assigning a window removes it from the old instance
- Removing a window cleans up both tables
- `repair` detects and fixes orphans, missing entries, and dead windows
- Exclusive ownership: assign window to A, then to B, verify it's only in B

---

## Phase 3: Config loading (`core/config.nim`)

This module loads the TOML config hierarchy into typed config structures.

### Step 3.1: Define config types

If you haven't already fleshed out `SidebardConfig` beyond the stub, now is the time. Create `src/core/config.nim`:

```nim
import std/[os, options, tables, strutils, sets]
import results
import toml_serialization
import types

type
  DaemonConfig* = object
    socket*: string

  KanataConfig* = object
    host*: string
    port*: int
    reconnectMs*: int

  DefaultsConfig* = object
    overlayTimeoutMs*: int
    collapsedVisiblePx*: int

  PluginSizeConfig* = object
    ratio*: Option[float]
    px*: Option[int]
    visiblePx*: Option[int]
    minPx*: Option[int]
    maxPx*: Option[int]

  PluginSizesConfig* = object
    collapsed*: Option[PluginSizeConfig]
    inactive*:  Option[PluginSizeConfig]
    active*:    Option[PluginSizeConfig]
    focused*:   Option[PluginSizeConfig]
    hidden*:    Option[PluginSizeConfig]

  CommandActionConfig* = object
    shell*:      Option[string]
    niri*:       Option[string]
    windowId*:   Option[uint64]
    kanataKey*:  Option[string]
    keyAction*:  Option[string]
    rpc*:        Option[string]
    args*:       Option[string]

  CommandConfig* = object
    id*: string
    title*: string
    description*: string
    category*: string
    tags*: seq[string]
    sequence*: seq[string]
    whenStates*: seq[string]
    action*: CommandActionConfig
    dangerous*: bool

  PluginProfileConfig* = object
    title*: string
    kanataLayer*: Option[string]
    sizes*: Option[PluginSizesConfig]

  PluginConfig* = object
    id*: string
    title*: string
    priority*: int
    matchAppIds*: seq[string]
    profile*: PluginProfileConfig
    commands*: seq[CommandConfig]

  InstanceOverrideConfig* = object
    sizes*: Option[PluginSizesConfig]

  InstanceConfig* = object
    id*: string
    position*: string
    defaultPlugin*: string
    overrides*: Table[string, InstanceOverrideConfig]

  RawConfig* = object
    daemon*: DaemonConfig
    kanata*: KanataConfig
    defaults*: DefaultsConfig
```

### Step 3.2: Implement the loader

```nim
proc loadMainConfig*(path: string): Result[RawConfig, string] =
  ## Load the main config.toml file.
  if not fileExists(path):
    return err("config file not found: " & path)
  try:
    let config = Toml.loadFile(path, RawConfig)
    ok(config)
  except CatchableError as e:
    err("failed to parse " & path & ": " & e.msg)

proc loadPlugins*(dir: string): Result[seq[PluginConfig], string] =
  ## Load all plugin TOML files from the plugins/ directory.
  var plugins: seq[PluginConfig] = @[]
  if not dirExists(dir):
    return ok(plugins)  # no plugins dir is fine
  for kind, path in walkDir(dir):
    if kind == pcFile and path.endsWith(".toml"):
      try:
        let plugin = Toml.loadFile(path, PluginConfig)
        plugins.add(plugin)
      except CatchableError as e:
        return err("failed to parse plugin " & path & ": " & e.msg)
  ok(plugins)

proc loadInstances*(dir: string): Result[seq[InstanceConfig], string] =
  ## Load all instance TOML files from the instances/ directory.
  var instances: seq[InstanceConfig] = @[]
  if not dirExists(dir):
    return ok(instances)
  for kind, path in walkDir(dir):
    if kind == pcFile and path.endsWith(".toml"):
      try:
        let inst = Toml.loadFile(path, InstanceConfig)
        instances.add(inst)
      except CatchableError as e:
        return err("failed to parse instance " & path & ": " & e.msg)
  ok(instances)
```

### Step 3.3: Convert raw config to domain types

Write conversion procs from raw config types to domain types. This is where validation happens:

```nim
proc toPanelSize*(cfg: PluginSizeConfig): PanelSize =
  PanelSize(
    ratio: cfg.ratio,
    px: cfg.px,
    visiblePx: cfg.visiblePx,
    minPx: cfg.minPx,
    maxPx: cfg.maxPx,
  )

proc toProfileSizes*(cfg: Option[PluginSizesConfig]): ProfileSizes =
  if cfg.isNone:
    return default(ProfileSizes)
  let c = cfg.get
  if c.collapsed.isSome: result[Collapsed] = some(c.collapsed.get.toPanelSize)
  if c.inactive.isSome:  result[Inactive]  = some(c.inactive.get.toPanelSize)
  if c.active.isSome:    result[Active]    = some(c.active.get.toPanelSize)
  if c.focused.isSome:   result[Focused]   = some(c.focused.get.toPanelSize)
  if c.hidden.isSome:    result[Hidden]    = some(c.hidden.get.toPanelSize)

proc parsePosition*(s: string): Result[SidebarPosition, string] =
  case s.toLowerAscii
  of "left":   ok(Left)
  of "right":  ok(Right)
  of "bottom": ok(Bottom)
  of "top":    ok(Top)
  else: err("invalid sidebar position: " & s)

proc parseWhenStates*(states: seq[string]): Result[set[SidebarState], string] =
  var result: set[SidebarState] = {}
  for s in states:
    case s.toLowerAscii
    of "collapsed": result.incl Collapsed
    of "inactive":  result.incl Inactive
    of "active":    result.incl Active
    of "focused":   result.incl Focused
    of "hidden":    result.incl Hidden
    else: return err("invalid sidebar state: " & s)
  ok(result)

proc toActionSpec*(cfg: CommandActionConfig): Result[ActionSpec, string] =
  ## Convert a TOML action config to a typed ActionSpec.
  ## Exactly one action type field must be set.
  if cfg.shell.isSome:
    ok(ActionSpec(kind: akShellCmd, shellCmd: cfg.shell.get))
  elif cfg.rpc.isSome:
    ok(ActionSpec(kind: akInternalRpc, rpcMethod: cfg.rpc.get, rpcArgs: cfg.args.get("")))
  elif cfg.kanataKey.isSome:
    ok(ActionSpec(kind: akKanataFakeKey,
                  fakeKeyName: cfg.kanataKey.get,
                  fakeKeyAction: cfg.keyAction.get("Tap")))
  elif cfg.niri.isSome:
    # Basic niri action mapping — extend as needed
    err("niri action parsing not yet implemented")
  else:
    err("action has no recognized type field")

proc toCommand*(cfg: CommandConfig): Result[Command, string] =
  let actionRes = toActionSpec(cfg.action)
  if actionRes.isErr:
    return err("command " & cfg.id & ": " & actionRes.error)
  let statesRes = parseWhenStates(cfg.whenStates)
  if statesRes.isErr:
    return err("command " & cfg.id & ": " & statesRes.error)
  ok(Command(
    id: CommandId(cfg.id),
    title: cfg.title,
    description: cfg.description,
    category: cfg.category,
    tags: cfg.tags.toHashSet,
    sequence: cfg.sequence.mapIt(KeyToken(it)),
    whenStates: statesRes.get,
    action: actionRes.get,
    dangerous: cfg.dangerous,
  ))

proc toProfile*(plugin: PluginConfig): Result[Profile, string] =
  var commands: seq[Command] = @[]
  for cmdCfg in plugin.commands:
    let cmdRes = toCommand(cmdCfg)
    if cmdRes.isErr:
      return err(cmdRes.error)
    commands.add(cmdRes.get)

  ok(Profile(
    id: ProfileId(plugin.id & "/default"),
    pluginId: PluginId(plugin.id),
    title: plugin.profile.title,
    kanataLayer: plugin.profile.kanataLayer,
    sizes: toProfileSizes(plugin.profile.sizes),
    commands: commands,
    workspaceMatch: none(string),
  ))
```

### Step 3.4: Top-level config assembly

```nim
type
  LoadedConfig* = object
    raw*: RawConfig
    plugins*: seq[PluginConfig]
    instances*: seq[InstanceConfig]
    profiles*: Table[PluginId, Profile]
    sidebarInstances*: Table[InstanceId, SidebarInstance]
    pluginAppIdPatterns*: seq[tuple[pluginId: PluginId, patterns: seq[string]]]
    instanceDefaults*: Table[InstanceId, PluginId]

proc loadConfig*(configDir: string): Result[LoadedConfig, string] =
  ## Load the entire config hierarchy from a directory.
  let mainPath = configDir / "config.toml"
  let rawRes = loadMainConfig(mainPath)
  if rawRes.isErr: return err(rawRes.error)

  let pluginsRes = loadPlugins(configDir / "plugins")
  if pluginsRes.isErr: return err(pluginsRes.error)

  let instancesRes = loadInstances(configDir / "instances")
  if instancesRes.isErr: return err(instancesRes.error)

  var loaded = LoadedConfig(
    raw: rawRes.get,
    plugins: pluginsRes.get,
    instances: instancesRes.get,
  )

  # Convert plugins to profiles
  for plugin in loaded.plugins:
    let profileRes = toProfile(plugin)
    if profileRes.isErr: return err(profileRes.error)
    loaded.profiles[PluginId(plugin.id)] = profileRes.get
    loaded.pluginAppIdPatterns.add((PluginId(plugin.id), plugin.matchAppIds))

  # Convert instances
  for inst in loaded.instances:
    let posRes = parsePosition(inst.position)
    if posRes.isErr: return err(posRes.error)
    loaded.sidebarInstances[InstanceId(inst.id)] = SidebarInstance(
      id: InstanceId(inst.id),
      position: posRes.get,
      state: Hidden,
      windowIds: @[],
      hidden: true,
    )
    loaded.instanceDefaults[InstanceId(inst.id)] = PluginId(inst.defaultPlugin)

  ok(loaded)
```

### Step 3.5: Convert loaded config to SidebardConfig

```nim
proc toSidebardConfig*(loaded: LoadedConfig): SidebardConfig =
  SidebardConfig(
    daemonSocket: loaded.raw.daemon.socket,
    kanataHost: loaded.raw.kanata.host,
    kanataPort: loaded.raw.kanata.port,
    kanataReconnectMs: loaded.raw.kanata.reconnectMs,
    overlayTimeoutMs: loaded.raw.defaults.overlayTimeoutMs,
    collapsedVisiblePx: loaded.raw.defaults.collapsedVisiblePx,
  )
```

### Checkpoint

Create test fixtures in `tests/fixtures/`:

**`tests/fixtures/config.toml`:**
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

**`tests/fixtures/plugins/chat.toml`:**
```toml
id = "chat"
title = "Chat"
priority = 200
match_app_ids = ['^vesktop$', '^org\.telegram\.desktop$']

[profile]
title = "Chat"
kanata_layer = "sidebar-chat"

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
dangerous = false
```

Write `tests/test_config.nim` that loads these fixtures and verifies:
- Main config parses with correct values
- Plugin config parses with correct profile, commands, and match patterns
- Instance config parses with correct position and default plugin
- Invalid TOML returns an error
- Missing optional fields get `none`

---

## Phase 4: Profile resolution (`core/profile.nim`)

Profile resolution determines which plugin profile is active based on the current focus context.

### Step 4.1: Implement resolution logic

Create `src/core/profile.nim`:

```nim
import std/[options, tables, re]
import types

proc matchesPlugin*(window: NiriWindow, patterns: seq[string]): bool =
  ## Check if a window's appId matches any of the plugin's match patterns.
  if window.appId.isNone:
    return false
  let appId = window.appId.get
  for pattern in patterns:
    if appId.match(re(pattern)):
      return true
  false

proc findPluginForWindow*(
  window: NiriWindow,
  pluginPatterns: seq[tuple[pluginId: PluginId, patterns: seq[string]]]
): Option[PluginId] =
  ## Find the plugin that matches a window's appId.
  for (pluginId, patterns) in pluginPatterns:
    if matchesPlugin(window, patterns):
      return some(pluginId)
  none(PluginId)

proc resolveSize*(profile: Profile, state: SidebarState): PanelSize =
  ## Get the effective panel size for a given sidebar state.
  ## Falls back to a default if the profile doesn't specify one.
  if profile.sizes[state].isSome:
    profile.sizes[state].get
  else:
    PanelSize(ratio: some(0.25))  # default fallback

proc resolveProfile*(
  state: ShellState,
  profiles: Table[PluginId, Profile],
  pluginPatterns: seq[tuple[pluginId: PluginId, patterns: seq[string]]],
  instanceDefaults: Table[InstanceId, PluginId],
): Option[ResolvedProfile] =
  ## Resolve the active profile from the current shell state.
  ##
  ## Algorithm:
  ## 1. If a window is focused and owned by a sidebar, find matching plugin
  ## 2. If no match, use the active sidebar's default plugin
  ## 3. If no active sidebar, return none

  # Need an active instance to resolve anything
  if state.activeInstance.isNone:
    return none(ResolvedProfile)

  let activeInst = state.activeInstance.get
  if activeInst notin state.instances:
    return none(ResolvedProfile)

  let instance = state.instances[activeInst]
  var pluginId: Option[PluginId] = none(PluginId)

  # 1. Check focused window
  if state.focusedWindowId.isSome:
    let focusedId = state.focusedWindowId.get
    # Is it owned by a sidebar?
    if focusedId in state.ownership:
      let ownerInstance = state.ownership[focusedId]
      if focusedId in state.windows:
        let window = state.windows[focusedId]
        pluginId = findPluginForWindow(window, pluginPatterns)

  # 2. Fall back to active instance's default plugin
  if pluginId.isNone:
    if activeInst in instanceDefaults:
      pluginId = some(instanceDefaults[activeInst])

  # 3. Look up the profile
  if pluginId.isNone or pluginId.get notin profiles:
    return none(ResolvedProfile)

  let profile = profiles[pluginId.get]
  some(ResolvedProfile(
    profile: profile,
    instanceId: activeInst,
    state: instance.state,
    size: resolveSize(profile, instance.state),
  ))
```

### Checkpoint

Write `tests/test_profile.nim`:

- No active instance → `none`
- Active instance with default plugin → resolves to that plugin's profile
- Focused window matching a plugin's `matchAppIds` → resolves to that plugin
- Focused window not matching any plugin → falls back to default
- Focused window not owned by any sidebar → falls back to default

---

## Phase 5: Keymap engine (`core/keymap.nim`)

The keymap is a trie of key sequences that supports prefix tracking and text filtering.

### Step 5.1: Trie data structure

Create `src/core/keymap.nim`:

```nim
import std/[options, tables, sequtils, strutils, sets, algorithm]
import types

type
  TrieNode* = object
    children*: Table[KeyToken, TrieNode]
    commandIds*: seq[CommandId]

proc insertCommand*(root: var TrieNode, command: Command) =
  ## Insert a command's key sequence into the trie.
  var node = addr root
  for key in command.sequence:
    if key notin node.children:
      node.children[key] = TrieNode()
    node = addr node.children[key]
  node.commandIds.add(command.id)

proc buildTrie*(commands: seq[Command]): TrieNode =
  ## Build a trie from a list of commands.
  result = TrieNode()
  for cmd in commands:
    if cmd.sequence.len > 0:
      result.insertCommand(cmd)
```

### Step 5.2: Prefix navigation

```nim
proc findNode*(root: TrieNode, prefix: seq[KeyToken]): Option[TrieNode] =
  ## Walk the trie to the node at the given prefix.
  var node = root
  for key in prefix:
    if key notin node.children:
      return none(TrieNode)
    node = node.children[key]
  some(node)

proc collectAllCommandIds*(node: TrieNode): seq[CommandId] =
  ## Recursively collect all command IDs reachable from this node.
  result = node.commandIds
  for key, child in node.children:
    result.add(collectAllCommandIds(child))
```

### Step 5.3: State management

```nim
proc rebuildKeymap*(
  commands: seq[Command],
  sidebarState: SidebarState,
  profileId: ProfileId,
): KeymapState =
  ## Build a fresh keymap state from a command list.
  ## Only includes commands available in the current sidebar state.
  let available = commands.filterIt(sidebarState in it.whenStates)
  let trie = buildTrie(available)
  let nextKeys = trie.children.keys.toSeq.sorted  # sort for stable order

  KeymapState(
    profileId: profileId,
    prefix: @[],
    filter: "",
    available: available,
    nextKeys: nextKeys.mapIt(it),
    exactMatch: none(Command),
  )

proc advancePrefix*(state: var KeymapState, key: KeyToken, trie: TrieNode) =
  ## Push a key onto the prefix. Recompute available commands, next keys, exact match.
  state.prefix.add(key)

  let node = findNode(trie, state.prefix)
  if node.isNone:
    # Dead end — no commands match this prefix
    state.available = @[]
    state.nextKeys = @[]
    state.exactMatch = none(Command)
    return

  let n = node.get

  # Collect all reachable command IDs from this point
  let reachableIds = collectAllCommandIds(n).toHashSet

  # Filter available commands to only those reachable
  state.available = state.available.filterIt(it.id in reachableIds)

  # Next valid keys
  state.nextKeys = n.children.keys.toSeq.sorted

  # Exact match: if this node has command IDs and exactly one
  if n.commandIds.len == 1:
    let matchId = n.commandIds[0]
    state.exactMatch = state.available.filterIt(it.id == matchId).toSeq.firstOpt
  elif n.commandIds.len > 1:
    # Multiple exact matches at this prefix — unusual but handle gracefully
    state.exactMatch = none(Command)
  else:
    state.exactMatch = none(Command)

proc setFilter*(state: var KeymapState, text: string, allCommands: seq[Command], sidebarState: SidebarState) =
  ## Set text filter. Intersects with prefix-filtered commands.
  ## Matches against title, description, tags (case-insensitive substring).
  state.filter = text
  if text.len == 0:
    # Reset to all available for current state
    state.available = allCommands.filterIt(sidebarState in it.whenStates)
    return

  let lowerText = text.toLowerAscii
  state.available = state.available.filterIt(
    lowerText in it.title.toLowerAscii or
    lowerText in it.description.toLowerAscii or
    it.tags.anyIt(lowerText in it.toLowerAscii)
  )

proc resetPrefix*(state: var KeymapState, allCommands: seq[Command], sidebarState: SidebarState, trie: TrieNode) =
  ## Clear prefix and filter. Restore full command list.
  state.prefix = @[]
  state.filter = ""
  state.available = allCommands.filterIt(sidebarState in it.whenStates)
  state.nextKeys = trie.children.keys.toSeq.sorted
  state.exactMatch = none(Command)
```

**Note:** The `firstOpt` helper may not exist in stdlib. If needed:

```nim
proc firstOpt*[T](s: seq[T]): Option[T] =
  if s.len > 0: some(s[0]) else: none(T)
```

### Checkpoint

Write `tests/test_keymap.nim`:

- Build a trie from 3 commands with sequences `[Leader, R]`, `[Leader, J]`, `[Leader, M, A]`
- After `advancePrefix(Leader)`: 3 commands available, next keys = `[J, M, R]`, no exact match
- After `advancePrefix(R)`: 1 command available, exact match = that command
- After `advancePrefix(M)` from `[Leader]`: next keys = `[A]`, 1 command available, no exact match yet
- Dead-end prefix: `advancePrefix(X)` from root → 0 available, 0 next keys
- Filter "reply" matches only commands with "reply" in title/description/tags
- Reset restores full state

---

## Phase 6: State reducer (`core/state.nim`)

The reducer is the heart of sidebard. It is a **pure function** — no I/O, no async. It mutates `ShellState` in place and returns a `seq[Effect]`.

### Step 6.1: Create `src/core/state.nim`

```nim
import std/[options, tables, times]
import types
import ownership
import profile
import keymap

proc findCommand*(state: ShellState, id: CommandId): Option[Command] =
  ## Find a command by ID in the current resolved profile.
  if state.resolved.isNone:
    return none(Command)
  for cmd in state.resolved.get.profile.commands:
    if cmd.id == id:
      return some(cmd)
  none(Command)

proc reduce*(
  state: var ShellState,
  event: Event,
  profiles: Table[PluginId, Profile],
  pluginPatterns: seq[tuple[pluginId: PluginId, patterns: seq[string]]],
  instanceDefaults: Table[InstanceId, PluginId],
): seq[Effect] =
  ## The core reducer. Pure. Deterministic. I/O-free.
  ##
  ## INVARIANT: This proc MUST NOT:
  ##   - perform I/O (no file reads, no socket writes)
  ##   - call async procs
  ##   - access global mutable state
  ##   - produce different results for the same inputs
  ##
  ## It mutates `state` in place for performance and returns
  ## a seq[Effect] describing side effects the runtime should execute.

  result = @[]

  case event.kind

  # ─── niri events ───────────────────────────────
  of evWindowOpened, evWindowChanged:
    state.windows[event.window.id] = event.window

  of evWindowClosed:
    state.windows.del(event.closedWindowId)
    removeWindow(state, event.closedWindowId)
    # If closed window was focused, clear focus
    if state.focusedWindowId == some(event.closedWindowId):
      state.focusedWindowId = none(WindowId)

  of evWindowFocused:
    state.focusedWindowId = event.focusedId
    # Re-resolve profile on focus change
    let prev = state.resolved
    state.resolved = resolveProfile(state, profiles, pluginPatterns, instanceDefaults)
    if state.resolved != prev:
      # Profile changed — rebuild keymap
      if state.resolved.isSome:
        let r = state.resolved.get
        state.keymap = rebuildKeymap(r.profile.commands, r.state, r.profile.id)
        # Switch kanata layer if needed
        let layer = r.profile.kanataLayer
        if layer.isSome and layer.get != state.kanataLayer:
          result.add Effect(kind: efChangeKanataLayer, layer: layer.get)
      else:
        state.keymap = KeymapState()
      result.add Effect(kind: efNotifySubscribers)

  of evWorkspaceActivated:
    # Track workspace activation — currently no state change needed
    # beyond what niri events provide via window focus changes
    discard

  # ─── kanata events ─────────────────────────────
  of evKanataConnected:
    state.kanataConnected = true

  of evKanataDisconnected:
    state.kanataConnected = false

  of evKanataLayerChanged:
    state.kanataLayer = event.newLayer

  of evKanataMessage:
    discard  # log only

  # ─── sidebar state ─────────────────────────────
  of evSidebarStateRead:
    # Hydrate from niri-sidebar state.json
    if event.sidebarInstanceId in state.instances:
      state.instances[event.sidebarInstanceId].windowIds = event.sidebarWindows
      state.instances[event.sidebarInstanceId].hidden = event.sidebarHidden
      if event.sidebarHidden:
        state.instances[event.sidebarInstanceId].state = Hidden
      else:
        state.instances[event.sidebarInstanceId].state = Active
      # Update ownership table
      for wid in event.sidebarWindows:
        state.ownership[wid] = event.sidebarInstanceId
    result.add Effect(kind: efNotifySubscribers)

  # ─── user interactions ─────────────────────────
  of evActivateInstance:
    state.activeInstance = some(event.targetInstance)
    let prev = state.resolved
    state.resolved = resolveProfile(state, profiles, pluginPatterns, instanceDefaults)
    if state.resolved != prev:
      if state.resolved.isSome:
        let r = state.resolved.get
        state.keymap = rebuildKeymap(r.profile.commands, r.state, r.profile.id)
      else:
        state.keymap = KeymapState()
      result.add Effect(kind: efNotifySubscribers)

  of evToggleVisibility:
    if event.toggleInstance in state.instances:
      let inst = addr state.instances[event.toggleInstance]
      inst.hidden = not inst.hidden
      inst.state = if inst.hidden: Hidden else: Active
      result.add Effect(kind: efNotifySubscribers)

  of evPrefixAdvance:
    if state.resolved.isSome:
      let r = state.resolved.get
      let trie = buildTrie(r.profile.commands.filterIt(r.state in it.whenStates))
      advancePrefix(state.keymap, event.key, trie)
    result.add Effect(kind: efNotifySubscribers)

  of evPrefixReset:
    if state.resolved.isSome:
      let r = state.resolved.get
      let available = r.profile.commands.filterIt(r.state in it.whenStates)
      let trie = buildTrie(available)
      resetPrefix(state.keymap, r.profile.commands, r.state, trie)
    result.add Effect(kind: efNotifySubscribers)

  of evFilterSet:
    if state.resolved.isSome:
      let r = state.resolved.get
      setFilter(state.keymap, event.filterText, r.profile.commands, r.state)
    result.add Effect(kind: efNotifySubscribers)

  of evCommandInvoked:
    let cmd = findCommand(state, event.commandId)
    if cmd.isSome:
      result.add Effect(kind: efExecuteAction, action: cmd.get.action)
    # Reset prefix after command invocation
    if state.resolved.isSome:
      let r = state.resolved.get
      let available = r.profile.commands.filterIt(r.state in it.whenStates)
      let trie = buildTrie(available)
      resetPrefix(state.keymap, r.profile.commands, r.state, trie)
    result.add Effect(kind: efNotifySubscribers)

  # ─── system ────────────────────────────────────
  of evConfigReloaded:
    state.config = event.newConfig
    result.add Effect(kind: efNotifySubscribers)

  of evTimerFired:
    # Handle specific timer IDs as needed
    discard
```

### Step 6.2: Convenience constructors

```nim
proc initShellState*(config: SidebardConfig): ShellState =
  ShellState(
    windows: initTable[WindowId, NiriWindow](),
    focusedWindowId: none(WindowId),
    instances: initTable[InstanceId, SidebarInstance](),
    activeInstance: none(InstanceId),
    ownership: initTable[WindowId, InstanceId](),
    resolved: none(ResolvedProfile),
    keymap: KeymapState(),
    kanataConnected: false,
    kanataLayer: "",
    config: config,
  )
```

### Checkpoint

Write `tests/test_state.nim`. This is the most important test file. Test:

1. **Window tracking:**
   - `evWindowOpened` adds to `state.windows`
   - `evWindowClosed` removes from `state.windows` and `state.ownership`
   - `evWindowClosed` clears `focusedWindowId` if the closed window was focused

2. **Focus → profile resolution:**
   - Set up state with an active instance, a plugin with `matchAppIds = ["code"]`
   - Open a window with `appId = "code"`, assign ownership, focus it
   - Verify `state.resolved` contains the correct profile
   - Verify `efChangeKanataLayer` is emitted if the profile has a kanataLayer
   - Verify `efNotifySubscribers` is emitted

3. **Profile change clears keymap:**
   - Focus window A (matches plugin "chat") → keymap has chat commands
   - Focus window B (matches plugin "code") → keymap has code commands

4. **Prefix advance/reset:**
   - `evPrefixAdvance(Leader)` → keymap prefix is `[Leader]`, available commands filtered
   - `evPrefixReset` → prefix empty, full commands restored
   - Both emit `efNotifySubscribers`

5. **Command invocation:**
   - `evCommandInvoked("chat.quick_reply")` → emits `efExecuteAction` with the command's action
   - Also resets prefix

6. **Sidebar state hydration:**
   - `evSidebarStateRead` populates instance windowIds and ownership table

7. **Toggle visibility:**
   - `evToggleVisibility("left")` flips `hidden` and `state`

8. **Determinism:** Same sequence of events → same final state + same effects list

---

## Phase 7: Public RPC types (`core/api_types.nim`)

These are the **stable public contract**. Internal types can change; these must not break clients within a major version.

### Step 7.1: Create `src/core/api_types.nim`

```nim
import std/[options]

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
    position*: string
    state*: string
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

### Step 7.2: Conversion procs

```nim
import types

proc toApi*(w: NiriWindow): ApiWindow =
  ApiWindow(
    id: uint64(w.id),
    appId: w.appId,
    title: w.title,
    workspaceId: if w.workspaceId.isSome: some(uint64(w.workspaceId.get)) else: none(uint64),
    isFocused: w.isFocused,
    isFloating: w.isFloating,
  )

proc toApi*(inst: SidebarInstance): ApiSidebarInstance =
  ApiSidebarInstance(
    id: $inst.id,
    position: ($inst.position).toLowerAscii,
    state: ($inst.state).toLowerAscii,
    windowIds: inst.windowIds.mapIt(uint64(it)),
    hidden: inst.hidden,
  )

proc toApi*(cmd: Command): ApiCommand =
  ApiCommand(
    id: $cmd.id,
    title: cmd.title,
    description: cmd.description,
    category: cmd.category,
    tags: cmd.tags.toSeq,
    sequence: cmd.sequence.mapIt($it),
    dangerous: cmd.dangerous,
  )

proc toApi*(ks: KeymapState): ApiKeymapState =
  ApiKeymapState(
    profileId: $ks.profileId,
    prefix: ks.prefix.mapIt($it),
    filter: ks.filter,
    available: ks.available.mapIt(it.toApi),
    nextKeys: ks.nextKeys.mapIt($it),
    exactMatch: if ks.exactMatch.isSome: some(ks.exactMatch.get.toApi) else: none(ApiCommand),
  )

proc toApi*(rp: ResolvedProfile): ApiResolvedProfile =
  ApiResolvedProfile(
    profileId: $rp.profile.id,
    pluginId: $rp.profile.pluginId,
    title: rp.profile.title,
    instanceId: $rp.instanceId,
    state: ($rp.state).toLowerAscii,
    kanataLayer: rp.profile.kanataLayer,
  )

proc toApiSnapshot*(state: ShellState): ApiStateSnapshot =
  ApiStateSnapshot(
    focusedWindowId: if state.focusedWindowId.isSome: some(uint64(state.focusedWindowId.get)) else: none(uint64),
    activeInstance: if state.activeInstance.isSome: some($state.activeInstance.get) else: none(string),
    resolved: if state.resolved.isSome: some(state.resolved.get.toApi) else: none(ApiResolvedProfile),
    keymap: state.keymap.toApi,
    kanataConnected: state.kanataConnected,
    kanataLayer: state.kanataLayer,
  )
```

### Checkpoint

Verify that `toApiSnapshot` produces valid, serializable JSON via `jsony.toJson`. Write a test that round-trips: `ShellState → ApiStateSnapshot → JSON string → parse JSON → verify fields`.

---

## Phase 8: Niri adapter (`adapters/niri.nim`)

This adapter wraps `nimri-ipc` and translates between the library's types and sidebard's domain events.

### Step 8.1: Create `src/adapters/niri.nim`

```nim
import std/[options, tables, asyncdispatch]
import chronos
import results
import nimri_ipc
import ../core/types

type
  NiriAdapter* = ref object
    client*: nimri_ipc.NiriClient
    eventStream*: nimri_ipc.NiriEventStream

proc connect*(config: NiriConnectConfig = initNiriConnectConfig()): Future[Result[NiriAdapter, string]] {.async.} =
  let clientRes = await nimri_ipc.openClient(config)
  if clientRes.isErr:
    return err("Failed to connect command client: " & $clientRes.error)

  let streamRes = await nimri_ipc.openEventStream(config)
  if streamRes.isErr:
    await clientRes.get.close()
    return err("Failed to open event stream: " & $streamRes.error)

  ok(NiriAdapter(
    client: clientRes.get,
    eventStream: streamRes.get,
  ))
```

### Step 8.2: Type conversion procs

Convert `nimri-ipc` types to sidebard domain types:

```nim
proc toDomain*(w: nimri_ipc.Window): NiriWindow =
  NiriWindow(
    id: WindowId(uint64(w.id)),
    appId: w.appId,
    title: w.title,
    workspaceId: if w.workspaceId.isSome: some(WorkspaceId(uint64(w.workspaceId.get))) else: none(WorkspaceId),
    outputId: none(OutputId),
    isFocused: w.isFocused,
    isFloating: w.isFloating,
  )
```

### Step 8.3: Convert nimri-ipc events to domain events

```nim
proc toDomainEvent*(niriEvent: nimri_ipc.NiriEvent): Option[Event] =
  ## Convert a nimri-ipc event to a sidebard domain event.
  ## Returns none for events we don't care about.
  let ts = getMonoTime()

  case niriEvent.kind
  of nimri_ipc.neWindowOpenedOrChanged:
    some(Event(
      ts: ts,
      kind: evWindowOpened,  # or evWindowChanged — they're the same variant
      window: niriEvent.window.toDomain,
    ))
  of nimri_ipc.neWindowClosed:
    some(Event(
      ts: ts,
      kind: evWindowClosed,
      closedWindowId: WindowId(uint64(niriEvent.closedId)),
    ))
  of nimri_ipc.neWindowFocusChanged:
    some(Event(
      ts: ts,
      kind: evWindowFocused,
      focusedId: if niriEvent.focusedId.isSome: some(WindowId(uint64(niriEvent.focusedId.get))) else: none(WindowId),
    ))
  of nimri_ipc.neWorkspaceActivated:
    some(Event(
      ts: ts,
      kind: evWorkspaceActivated,
      workspaceId: WorkspaceId(uint64(niriEvent.activatedId)),
      workspaceFocused: niriEvent.activatedFocused,
    ))
  else:
    none(Event)
```

### Step 8.4: Seed initial state

```nim
proc seedState*(adapter: NiriAdapter, state: var ShellState): Future[Result[void, string]] {.async.} =
  ## Fetch initial windows and focus to seed the shell state.

  # Get all windows
  let windowsRes = await adapter.client.getWindows()
  if windowsRes.isErr:
    return err("Failed to get windows: " & $windowsRes.error)
  for w in windowsRes.get:
    state.windows[WindowId(uint64(w.id))] = w.toDomain

  # Get focused window
  let focusedRes = await adapter.client.getFocusedWindow()
  if focusedRes.isErr:
    return err("Failed to get focused window: " & $focusedRes.error)
  if focusedRes.get.isSome:
    state.focusedWindowId = some(WindowId(uint64(focusedRes.get.get.id)))

  ok()

proc readNextEvent*(adapter: NiriAdapter): Future[Result[Event, string]] {.async.} =
  ## Read the next event from the niri event stream and convert it.
  let eventRes = await adapter.eventStream.next()
  if eventRes.isErr:
    return err("Event stream error: " & $eventRes.error)

  let domainEvent = toDomainEvent(eventRes.get)
  if domainEvent.isNone:
    # Unhandled event type — caller should retry
    return err("unhandled event type")

  ok(domainEvent.get)
```

### Step 8.5: Execute effects that target Niri

```nim
proc executeNiriAction*(adapter: NiriAdapter, action: NiriActionSpec): Future[Result[void, string]] {.async.} =
  ## Execute a domain-level NiriActionSpec via the nimri-ipc client.
  let niriAction = case action.kind
    of naFocusWindow:
      nimri_ipc.focusWindow(nimri_ipc.WindowId(uint64(action.focusWindowId)))
    of naCloseWindow:
      nimri_ipc.closeWindow(some(nimri_ipc.WindowId(uint64(action.closeWindowId))))
    of naSetColumnWidth:
      # Parse the width change string — implementation depends on format
      return err("SetColumnWidth not yet implemented")
    of naMoveToFloating:
      nimri_ipc.moveWindowToFloating(some(nimri_ipc.WindowId(uint64(action.floatWindowId))))
    of naMoveToWorkspace:
      nimri_ipc.moveWindowToWorkspace(
        nimri_ipc.WorkspaceRef(kind: wrkById, id: nimri_ipc.WorkspaceId(uint64(action.moveWorkspaceId))),
        focus = false,
        windowId = some(nimri_ipc.WindowId(uint64(action.moveWindowId))),
      )

  let res = await adapter.client.doAction(niriAction)
  if res.isErr:
    return err("Niri action failed: " & $res.error)
  ok()
```

### Checkpoint

Integration test (requires a running Niri session):

- `connect()` succeeds
- `seedState()` populates `state.windows` with at least one window
- `readNextEvent()` returns an event when you open/close a window manually

For automated tests, write mock-based tests using `newClientWithSocket` and `newEventStreamWithSocket` with a test socket pair.

---

## Phase 9: Sidebar compatibility adapter (`adapters/sidebar_compat.nim`)

This reads `niri-sidebar`'s `state.json` files to hydrate sidebar ownership on startup.

### Step 9.1: Create `src/adapters/sidebar_compat.nim`

```nim
import std/[os, json, options, strutils]
import results
import ../core/types

type
  SidebarStateFile* = object
    windows*: seq[uint64]
    hidden*: bool

proc readSidebarState*(statePath: string): Result[SidebarStateFile, string] =
  ## Read a niri-sidebar state.json file.
  if not fileExists(statePath):
    return err("state file not found: " & statePath)
  try:
    let content = readFile(statePath)
    let json = parseJson(content)
    var state = SidebarStateFile()
    if json.hasKey("windows"):
      for w in json["windows"]:
        state.windows.add(w.getInt.uint64)
    if json.hasKey("hidden"):
      state.hidden = json["hidden"].getBool
    ok(state)
  except CatchableError as e:
    err("failed to parse " & statePath & ": " & e.msg)

proc loadSidebarStates*(stateDir: string, instances: seq[InstanceId]): seq[Event] =
  ## Read state.json for each known sidebar instance and produce
  ## evSidebarStateRead events.
  result = @[]
  for instanceId in instances:
    let path = stateDir / $instanceId / "state.json"
    let stateRes = readSidebarState(path)
    if stateRes.isOk:
      let s = stateRes.get
      result.add Event(
        ts: getMonoTime(),
        kind: evSidebarStateRead,
        sidebarInstanceId: instanceId,
        sidebarWindows: s.windows.mapIt(WindowId(it)),
        sidebarHidden: s.hidden,
      )
    # If file doesn't exist or fails to parse, skip silently
```

### Checkpoint

Create a test fixture `state.json` and verify `readSidebarState` parses it correctly. Verify `loadSidebarStates` produces the expected events.

---

## Phase 10: JSON-RPC server (`adapters/rpc.nim`)

This is the primary external interface. Implement it using `nim-json-rpc`.

### Step 10.1: Create `src/adapters/rpc.nim`

```nim
import std/[options, tables, json, sets]
import chronos
import json_rpc/rpcserver
import jsony
import ../core/[types, api_types, state]

type
  RpcContext* = ref object
    state*: ptr ShellState
    profiles*: ptr Table[PluginId, Profile]
    pluginPatterns*: ptr seq[tuple[pluginId: PluginId, patterns: seq[string]]]
    instanceDefaults*: ptr Table[InstanceId, PluginId]
    eventCallback*: proc(event: Event) {.gcsafe.}
    subscriptions*: Table[string, Subscription]

  Subscription* = object
    topics*: HashSet[string]
    # Connection handle for push — details depend on json-rpc library

proc setupRpcServer*(ctx: RpcContext, server: RpcServer) =
  ## Register all RPC methods on the server.

  # ─── Queries ─────────────────────────────────
  server.rpc("state") do() -> JsonNode:
    let snapshot = ctx.state[].toApiSnapshot()
    return snapshot.toJson.parseJson

  server.rpc("profile") do() -> JsonNode:
    if ctx.state[].resolved.isSome:
      return ctx.state[].resolved.get.toApi.toJson.parseJson
    return newJNull()

  server.rpc("keymap") do() -> JsonNode:
    return ctx.state[].keymap.toApi.toJson.parseJson

  server.rpc("commands") do() -> JsonNode:
    if ctx.state[].resolved.isSome:
      let cmds = ctx.state[].resolved.get.profile.commands.mapIt(it.toApi)
      return cmds.toJson.parseJson
    return newJArray()

  server.rpc("instances") do() -> JsonNode:
    var arr = newJArray()
    for _, inst in ctx.state[].instances:
      arr.add(inst.toApi.toJson.parseJson)
    return arr

  server.rpc("windows") do() -> JsonNode:
    var arr = newJArray()
    for _, w in ctx.state[].windows:
      arr.add(w.toApi.toJson.parseJson)
    return arr

  # ─── Actions ─────────────────────────────────
  server.rpc("activate") do(instance: string):
    ctx.eventCallback(Event(
      ts: getMonoTime(),
      kind: evActivateInstance,
      targetInstance: InstanceId(instance),
    ))

  server.rpc("toggle") do(instance: string):
    ctx.eventCallback(Event(
      ts: getMonoTime(),
      kind: evToggleVisibility,
      toggleInstance: InstanceId(instance),
    ))

  server.rpc("prefix.advance") do(key: string):
    ctx.eventCallback(Event(
      ts: getMonoTime(),
      kind: evPrefixAdvance,
      key: KeyToken(key),
    ))

  server.rpc("prefix.reset") do():
    ctx.eventCallback(Event(
      ts: getMonoTime(),
      kind: evPrefixReset,
    ))

  server.rpc("filter") do(text: string):
    ctx.eventCallback(Event(
      ts: getMonoTime(),
      kind: evFilterSet,
      filterText: text,
    ))

  server.rpc("run") do(command: string):
    ctx.eventCallback(Event(
      ts: getMonoTime(),
      kind: evCommandInvoked,
      commandId: CommandId(command),
    ))

  server.rpc("reload") do():
    # Config reload is handled by the main daemon — emit signal
    discard  # TODO: implement config reload

  # ─── Subscriptions ──────────────────────────
  server.rpc("subscribe") do(topics: seq[string]) -> string:
    # TODO: implement subscription tracking
    return "sub-001"

  server.rpc("unsubscribe") do(subscriptionId: string):
    # TODO: remove subscription
    discard
```

**Note on subscriptions:** Full push notification support depends on the `nim-json-rpc` library's notification capabilities. You may need to manage WebSocket or persistent socket connections manually. Start with request/response methods and add push notifications as a follow-up.

### Checkpoint

- Start the RPC server on a Unix socket
- Use `socat` or a simple client to send JSON-RPC requests and verify responses
- Verify `state` returns a valid `ApiStateSnapshot`
- Verify `activate "right"` triggers the event callback

---

## Phase 11: Kanata adapter (`adapters/kanata.nim`)

### Step 11.1: Create `src/adapters/kanata.nim`

```nim
import std/[json, options, strutils]
import chronos
import results
import ../core/types

type
  KanataAdapter* = ref object
    socket*: AsyncSocket
    host*: string
    port*: int
    connected*: bool
    reconnectMs*: int

proc connect*(host: string, port: int): Future[Result[KanataAdapter, string]] {.async.} =
  try:
    let socket = newAsyncSocket()
    await socket.connect(host, Port(port))
    ok(KanataAdapter(
      socket: socket,
      host: host,
      port: port,
      connected: true,
    ))
  except CatchableError as e:
    err("Failed to connect to Kanata: " & e.msg)

proc sendCommand*(adapter: KanataAdapter, command: JsonNode): Future[Result[void, string]] {.async.} =
  if not adapter.connected:
    return err("Not connected to Kanata")
  try:
    await adapter.socket.send($command & "\n")
    ok()
  except CatchableError as e:
    adapter.connected = false
    err("Kanata send failed: " & e.msg)

proc changeLayer*(adapter: KanataAdapter, layer: string): Future[Result[void, string]] {.async.} =
  let cmd = %*{"ChangeLayer": {"new": layer}}
  await adapter.sendCommand(cmd)

proc fakeKeyAction*(adapter: KanataAdapter, name: string, action: string): Future[Result[void, string]] {.async.} =
  let cmd = %*{"ActOnFakeKey": {"name": name, "action": action}}
  await adapter.sendCommand(cmd)

proc readEvent*(adapter: KanataAdapter): Future[Result[Event, string]] {.async.} =
  if not adapter.connected:
    return err("Not connected")
  try:
    let line = await adapter.socket.recvLine()
    if line.len == 0:
      adapter.connected = false
      return ok(Event(ts: getMonoTime(), kind: evKanataDisconnected))

    let json = parseJson(line)
    let ts = getMonoTime()

    if json.hasKey("LayerChange"):
      let lc = json["LayerChange"]
      return ok(Event(
        ts: ts,
        kind: evKanataLayerChanged,
        oldLayer: lc["old"].getStr,
        newLayer: lc["new"].getStr,
      ))

    ok(Event(ts: ts, kind: evKanataMessage, message: line))
  except CatchableError as e:
    adapter.connected = false
    err("Kanata read failed: " & e.msg)
```

### Checkpoint

If you have Kanata running, verify `connect` and `changeLayer`. Otherwise, test with a simple TCP echo server.

---

## Phase 12: Main daemon loop (`src/sidebard.nim`)

### Step 12.1: Create the entry point

```nim
import std/[os, options, tables, times]
import chronos
import chronicles
import results
import core/[types, config, state, ownership, profile, keymap, api_types]
import adapters/[niri, kanata, rpc, sidebar_compat]

proc runDaemon() {.async.} =
  # 1. Load config
  let configDir = getConfigDir() / "sidebard"
  let loadedConfigRes = loadConfig(configDir)
  if loadedConfigRes.isErr:
    error "Failed to load config", err = loadedConfigRes.error
    quit(1)
  let loadedConfig = loadedConfigRes.get

  # 2. Initialize state
  var shellState = initShellState(loadedConfig.toSidebardConfig())
  for instanceId, inst in loadedConfig.sidebarInstances:
    shellState.instances[instanceId] = inst

  # 3. Connect to Niri
  let niriRes = await niri.connect()
  if niriRes.isErr:
    error "Failed to connect to Niri", err = niriRes.error
    quit(1)
  let niriAdapter = niriRes.get
  info "Connected to Niri"

  # 4. Seed initial state
  let seedRes = await niriAdapter.seedState(shellState)
  if seedRes.isErr:
    error "Failed to seed state", err = seedRes.error
    quit(1)
  info "Seeded state", windowCount = shellState.windows.len

  # 5. Load sidebar compatibility state
  let sidebarStateDir = getDataDir() / "niri-sidebar"  # adjust path
  let sidebarEvents = loadSidebarStates(
    sidebarStateDir,
    loadedConfig.sidebarInstances.keys.toSeq
  )
  for ev in sidebarEvents:
    let effects = reduce(
      shellState, ev,
      loadedConfig.profiles,
      loadedConfig.pluginAppIdPatterns,
      loadedConfig.instanceDefaults,
    )
    # Execute effects (for initial state, these are just notifications)

  # 6. Resolve initial profile
  shellState.resolved = resolveProfile(
    shellState,
    loadedConfig.profiles,
    loadedConfig.pluginAppIdPatterns,
    loadedConfig.instanceDefaults,
  )
  if shellState.resolved.isSome:
    let r = shellState.resolved.get
    shellState.keymap = rebuildKeymap(r.profile.commands, r.state, r.profile.id)
    info "Initial profile resolved", profile = $r.profile.id

  # 7. Connect to Kanata (non-fatal)
  var kanataAdapter: Option[KanataAdapter] = none(KanataAdapter)
  let kanataRes = await kanata.connect(
    shellState.config.kanataHost,
    shellState.config.kanataPort,
  )
  if kanataRes.isOk:
    kanataAdapter = some(kanataRes.get)
    shellState.kanataConnected = true
    info "Connected to Kanata"
  else:
    warn "Kanata not available, continuing without", err = kanataRes.error

  # 8. Start JSON-RPC server
  # (Implementation depends on nim-json-rpc server setup)
  info "Starting RPC server", socket = shellState.config.daemonSocket

  # 9. Event loop
  info "Entering event loop"
  while true:
    # Read next event from niri
    let eventRes = await niriAdapter.readNextEvent()
    if eventRes.isErr:
      # Retry on unhandled events, fatal on connection errors
      continue

    let event = eventRes.get
    debug "Event received", kind = $event.kind

    # Reduce
    let effects = reduce(
      shellState, event,
      loadedConfig.profiles,
      loadedConfig.pluginAppIdPatterns,
      loadedConfig.instanceDefaults,
    )

    # Execute effects
    for eff in effects:
      case eff.kind
      of efChangeKanataLayer:
        if kanataAdapter.isSome:
          let res = await kanataAdapter.get.changeLayer(eff.layer)
          if res.isErr:
            warn "Failed to change Kanata layer", err = res.error
      of efExecuteAction:
        case eff.action.kind
        of akShellCmd:
          # Spawn shell command
          discard  # TODO: implement shell execution
        of akNiriAction:
          let res = await niriAdapter.executeNiriAction(eff.action.niriAction)
          if res.isErr:
            warn "Failed to execute Niri action", err = res.error
        of akKanataFakeKey:
          if kanataAdapter.isSome:
            let res = await kanataAdapter.get.fakeKeyAction(
              eff.action.fakeKeyName, eff.action.fakeKeyAction)
            if res.isErr:
              warn "Failed to execute Kanata fake key", err = res.error
        of akInternalRpc:
          discard  # TODO: route internal RPC
      of efStartTimer:
        discard  # TODO: implement timer management
      of efCancelTimer:
        discard  # TODO: implement timer cancellation
      of efNotifySubscribers:
        discard  # TODO: push to RPC subscribers
      of efNiriAction:
        let res = await niriAdapter.executeNiriAction(eff.niriAction)
        if res.isErr:
          warn "Failed to execute Niri action", err = res.error
```

### Step 12.2: CLI dispatch

Create `src/cli.nim`:

```nim
import std/[os, json]
import chronos
import jsony
import cligen
import core/api_types

proc daemon() =
  ## Start the sidebard daemon.
  waitFor runDaemon()

proc state(json: bool = true, pretty: bool = false) =
  ## Query the full shell state.
  # Connect to daemon RPC socket, call "state", print result
  discard  # TODO: implement RPC client mode

proc profile(json: bool = true) =
  ## Query the current resolved profile.
  discard

proc keymap(json: bool = true) =
  ## Query the current keymap state.
  discard

proc commands(json: bool = true) =
  ## List all commands for the active profile.
  discard

proc activate(instance: string) =
  ## Set the active sidebar instance.
  discard

proc toggle(instance: string) =
  ## Toggle sidebar visibility.
  discard

# ... other subcommands

when isMainModule:
  dispatchMulti(
    [daemon],
    [state],
    [profile],
    [keymap],
    [commands],
    [activate],
    [toggle],
  )
```

### Checkpoint

- `sidebard daemon` starts, connects to Niri, logs events
- `sidebard state --json` (once RPC client is wired) returns valid JSON
- Open/close/focus windows and verify the reducer produces correct effects

---

## Phase 13: CLI client mode

Each CLI subcommand should connect to the daemon's Unix socket, send a JSON-RPC request, print the result, and exit.

### Step 13.1: Implement RPC client helper

```nim
proc rpcCall*(socketPath: string, method: string, params: JsonNode = newJObject()): Future[JsonNode] {.async.} =
  let socket = newAsyncSocket(AF_UNIX, SOCK_STREAM, IPPROTO_IP)
  await socket.connectUnix(socketPath)

  let request = %*{
    "jsonrpc": "2.0",
    "id": 1,
    "method": method,
    "params": params,
  }
  await socket.send($request & "\n")
  let response = await socket.recvLine()
  socket.close()

  let json = parseJson(response)
  if json.hasKey("error"):
    raise newException(IOError, json["error"]["message"].getStr)
  json["result"]
```

### Step 13.2: Wire subcommands

```nim
proc state(json: bool = true, pretty: bool = false) =
  let socketPath = getSocketPath()
  let result = waitFor rpcCall(socketPath, "state")
  if pretty:
    echo result.pretty
  else:
    echo $result

proc activate(instance: string) =
  let socketPath = getSocketPath()
  discard waitFor rpcCall(socketPath, "activate", %*{"instance": instance})
  echo "Activated: " & instance
```

### Checkpoint

With the daemon running:

```bash
sidebard state --pretty
sidebard activate right
sidebard keymap
sidebard commands
sidebard prefix advance Leader
sidebard keymap  # should show filtered state
sidebard prefix reset
```

---

## Phase 14: Push subscriptions

### Step 14.1: Implement `sidebard watch`

The `watch` command subscribes to a topic and streams notifications to stdout:

```nim
proc watch(topic: string) =
  let socketPath = getSocketPath()
  let socket = waitFor connectUnix(socketPath)

  # Send subscribe request
  let subReq = %*{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "subscribe",
    "params": {"topics": [topic]},
  }
  waitFor socket.send($subReq & "\n")
  let subResp = waitFor socket.recvLine()
  # Verify subscription succeeded

  # Stream notifications
  while true:
    let line = waitFor socket.recvLine()
    if line.len == 0:
      break
    echo line
```

### Step 14.2: Server-side notification dispatch

In the effect executor, when `efNotifySubscribers` fires:

```nim
of efNotifySubscribers:
  for subId, sub in rpcCtx.subscriptions:
    for topic in sub.topics:
      let payload = case topic
        of "state": shellState.toApiSnapshot.toJson
        of "keymap": shellState.keymap.toApi.toJson
        of "profile":
          if shellState.resolved.isSome: shellState.resolved.get.toApi.toJson
          else: "null"
        of "instances":
          var arr: seq[ApiSidebarInstance]
          for _, inst in shellState.instances:
            arr.add(inst.toApi)
          arr.toJson
        else: continue

      let notification = %*{
        "jsonrpc": "2.0",
        "method": "notify." & topic,
        "params": parseJson(payload),
      }
      # Send to subscriber's connection
```

### Checkpoint

```bash
# Terminal 1:
sidebard watch keymap

# Terminal 2:
sidebard prefix advance Leader
# Terminal 1 should show a notification with updated keymap state

sidebard prefix reset
# Terminal 1 should show another notification
```

---

## Testing strategy

### Unit tests (pure, no I/O)

| Module | Test file | What to test |
|---|---|---|
| `core/types.nim` | `test_types.nim` | Type construction, distinct ID safety, enum completeness |
| `core/ownership.nim` | `test_ownership.nim` | Exclusive ownership, assign/remove/repair |
| `core/profile.nim` | `test_profile.nim` | Resolution with various focus/ownership combinations |
| `core/keymap.nim` | `test_keymap.nim` | Trie build, prefix advance, filter, reset |
| `core/state.nim` | `test_state.nim` | Full event → reduce → effects for every EventKind |
| `core/config.nim` | `test_config.nim` | TOML parsing, validation, type conversion |
| `core/api_types.nim` | `test_api_types.nim` | Conversion procs, JSON round-trip |

### Integration tests (require running services)

| Test | Requirements | What to test |
|---|---|---|
| Niri adapter | Running Niri | Connect, seed, event stream |
| Kanata adapter | Running Kanata | Connect, layer change |
| RPC server | Running daemon | All query/action methods |
| Full daemon | Running Niri | Startup → event → state change |

### Property tests

Write property-based tests (if using a Nim property testing library) for:

- **Reducer determinism:** Same events → same state + effects
- **Ownership exclusivity:** After any sequence of events, each window appears in at most one instance
- **Keymap consistency:** Available commands are always a subset of the profile's commands

---

## Common pitfalls

1. **Forgetting `{.borrow.}` on distinct types.** Without `==` and `hash`, they won't work in tables.

2. **Variant object case mismatch.** Accessing `event.window` when `event.kind` is `evWindowClosed` is a runtime error. Always match on `kind` first.

3. **Nim's `Table` iteration order is non-deterministic.** For stable RPC output, convert to `seq` and sort before serializing.

4. **`ref object` vs `object` for recursive types.** `MatchRule` in nirip uses `ref object` because Nim doesn't support recursive value types. Sidebard's types are non-recursive and should stay as `object`.

5. **Chronos vs std/asyncdispatch.** Pick one async runtime. Sidebard uses chronos (required by nim-json-rpc). Don't mix them.

6. **TOML field naming.** Nim uses camelCase; TOML uses snake_case. The `toml-serialization` library may or may not handle this automatically. Use `{.serialize: "snake_case_name".}` pragmas if needed.

7. **Thread safety.** The daemon is single-threaded. The reducer must remain I/O-free to guarantee this works. Never add blocking calls inside `reduce()`.

8. **Effect ordering.** Effects from a single `reduce()` call are executed in list order. Don't reorder them in the executor.

---

## Definition of done

The sidebard implementation is complete when:

1. `sidebard daemon` starts, connects to Niri and optionally Kanata
2. Window open/close/focus events update `ShellState` correctly
3. Profile resolution picks the correct plugin based on focused window
4. Keymap trie builds from profile commands and supports prefix navigation
5. All RPC methods return correct data
6. Push subscriptions deliver notifications on state changes
7. `sidebard watch keymap` streams live keymap updates
8. All unit tests pass
9. The reducer is provably I/O-free (no imports of async/net/os in `core/state.nim`)
10. Config reload works without daemon restart
