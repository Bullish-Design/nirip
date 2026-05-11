# Nirip Implementation Guide

A step-by-step guide for implementing the nirip declarative workspace orchestrator from scratch.

---

## Prerequisites

Before starting, ensure you have:

- **Nim >= 2.0.0** installed and on PATH
- **nimble** package manager (ships with Nim)
- **A running Niri compositor** with `$NIRI_SOCKET` set
- **The `nimri-ipc` library** cloned locally at `../nimri-ipc` (or installed via nimble)
- At least one named workspace in your Niri session (for testing)
- Familiarity with Nim's variant objects, `Option`, `Result`, and async/await
- Read the `FINAL_CONCEPT.md` in this directory — it is the architectural source of truth

### Key dependencies

| Package | Purpose | Install |
|---|---|---|
| chronos | Async runtime (executor) | `nimble install chronos` |
| nim-results | `Result[T, E]` | `nimble install results` |
| jsony | JSON serialization | `nimble install jsony` |
| toml-serialization | TOML profile loading | `nimble install toml_serialization` |
| cligen | CLI generation | `nimble install cligen` |
| chronicles | Structured logging | `nimble install chronicles` |

---

## Repository setup

### Step 1: Create the project

```bash
mkdir nirip && cd nirip
nimble init
```

Edit `nirip.nimble`:

```nim
# Package
version       = "0.1.0"
author        = "andrew"
description   = "Declarative workspace orchestrator for Niri compositor"
license       = "MIT"
srcDir        = "src"
bin           = @["nirip"]

# Dependencies
requires "nim >= 2.0.0"
requires "results >= 0.4.0"
requires "chronos >= 4.0.0"
requires "jsony >= 1.1.0"
requires "toml_serialization >= 0.2.0"
requires "cligen >= 1.7.0"
requires "chronicles >= 0.10.0"
requires "nimri_ipc >= 0.1.0"
```

### Step 2: Create the directory structure

```bash
mkdir -p src/core
mkdir -p src/executor
mkdir -p src/state
mkdir -p src/integrations
mkdir -p tests
mkdir -p tests/fixtures/profiles/backend-dev
mkdir -p tests/fixtures/profiles
mkdir -p tests/fixtures/niri
```

Target layout:

```
src/
├── nirip.nim                # entry point
├── cli.nim                  # CLI subcommands
├── core/
│   ├── types.nim            # domain types (profile, match, operation)
│   ├── config.nim           # TOML → typed profile, validation
│   ├── matcher.nim          # match rule evaluation
│   ├── planner.nim          # plan(desired, actual) → seq[Operation]
│   ├── freezer.nim          # niri state → profile
│   └── diagnostics.nim      # explain, format, diff
├── executor/
│   ├── runner.nim           # operation loop with event confirmation
│   ├── launcher.nim         # spawn processes, track PIDs
│   └── focus.nim            # focus management for focus-sensitive ops
├── state/
│   └── managed.nim          # active profiles + managed windows (JSON)
└── integrations/
    └── sidebard_rpc.nim     # optional sidebard queries
tests/
├── test_types.nim
├── test_config.nim
├── test_matcher.nim
├── test_planner.nim
├── test_freezer.nim
├── test_diagnostics.nim
└── fixtures/
    ├── profiles/
    │   ├── personal.toml
    │   └── backend-dev/
    │       ├── profile.toml
    │       └── code.toml
    └── niri/
        ├── windows.json
        ├── workspaces.json
        └── outputs.json
```

---

## Implementation phases

Each phase builds on the previous. Every phase ends with a checkpoint — tests that must pass before moving on.

---

## Phase 1: Domain types (`core/types.nim`)

### Step 1.1: Identifiers

Create `src/core/types.nim`:

```nim
import std/[options, tables, times, hashes, sets]
import results
import nimri_ipc

# ─── identifiers ─────────────────────────────────
type
  ProfileName*   = distinct string
  WorkspaceName* = distinct string
  WindowRole*    = distinct string   # "editor", "terminal", "browser"
  ColumnRole*    = distinct string   # "main", "tools", "reference"
  OutputAlias*   = distinct string   # "primary", "laptop"
```

Define `==`, `hash`, `$` for each:

```nim
proc `==`*(a, b: ProfileName): bool {.borrow.}
proc hash*(a: ProfileName): Hash {.borrow.}
proc `$`*(a: ProfileName): string {.borrow.}

proc `==`*(a, b: WorkspaceName): bool {.borrow.}
proc hash*(a: WorkspaceName): Hash {.borrow.}
proc `$`*(a: WorkspaceName): string {.borrow.}

proc `==`*(a, b: WindowRole): bool {.borrow.}
proc hash*(a: WindowRole): Hash {.borrow.}
proc `$`*(a: WindowRole): string {.borrow.}

proc `==`*(a, b: ColumnRole): bool {.borrow.}
proc hash*(a: ColumnRole): Hash {.borrow.}
proc `$`*(a: ColumnRole): string {.borrow.}

proc `==`*(a, b: OutputAlias): bool {.borrow.}
proc hash*(a: OutputAlias): Hash {.borrow.}
proc `$`*(a: OutputAlias): string {.borrow.}
```

### Step 1.2: Size specification

```nim
type
  SizeKind* = enum
    skProportion   ## 0.0..1.0 of available space
    skPixels       ## absolute pixel count

  SizeSpec* = object
    case kind*: SizeKind
    of skProportion: ratio*: float
    of skPixels:     px*: int

  ColumnDisplay* = enum
    cdNormal
    cdTabbed
```

### Step 1.3: Profile model

This is the core data model — what a workspace layout declaration looks like in memory.

```nim
type
  ProfileOptions* = object
    matchExisting*:  bool    ## try to match running windows before launching
    launchMissing*:  bool    ## spawn windows that don't match
    moveUnmanaged*:  bool    ## move non-profile windows out of the way
    closeExtra*:     bool    ## close windows from prior load that aren't in profile
    timeoutMs*:      int     ## max wait for window to appear after launch
    focusAfterLoad*: Option[string]  ## "workspace:column/window" path to focus

  OutputAliases* = Table[OutputAlias, seq[string]]

  Profile* = object
    name*:        ProfileName
    description*: string
    options*:     ProfileOptions
    outputs*:     OutputAliases
    workspaces*:  seq[WorkspaceSpec]

  WorkspaceSpec* = object
    name*:    WorkspaceName
    output*:  Option[string]     ## output name or alias
    index*:   Option[int]        ## ordering hint
    focus*:   Option[WindowRole] ## focus target after load
    columns*: seq[ColumnSpec]

  ColumnSpec* = object
    id*:      Option[ColumnRole]
    width*:   Option[SizeSpec]
    display*: ColumnDisplay
    windows*: seq[WindowSpec]

  WindowSpec* = object
    id*:       WindowRole
    command*:  Option[seq[string]]  ## argv to launch
    cwd*:      Option[string]
    env*:      Table[string, string]
    match*:    MatchRule
    height*:   Option[SizeSpec]
    floating*: bool
```

### Step 1.4: Match rules

Match rules are recursive (composable with `All`/`Any`/`Not`), so they must be `ref object`:

```nim
type
  MatchRuleKind* = enum
    mrExactAppId     ## exact string match on window appId
    mrRegexAppId     ## regex match on window appId
    mrExactTitle     ## exact string match on window title
    mrRegexTitle     ## regex match on window title
    mrWorkspaceName  ## window is on this workspace
    mrPidFromSpawn   ## window PID matches a spawned process
    mrOpenedAfter    ## window appeared after a timestamp
    mrAll            ## AND: all sub-rules must match
    mrAny            ## OR: at least one must match
    mrNot            ## negate a sub-rule

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
    explanation*: seq[string]  ## human-readable trace of what matched/failed

  MatchContext* = object
    spawnTimestamps*: Table[WindowRole, MonoTime]
    launchedPids*:    Table[WindowRole, int]
    workspaceNames*:  Table[nimri_ipc.WorkspaceId, string]
```

### Step 1.5: Operations

Operations are what the planner produces and the executor consumes. Each carries a `FocusReq` so the executor knows whether to set up focus before executing.

```nim
type
  OpKind* = enum
    opEnsureWorkspace       ## create workspace if it doesn't exist
    opMoveWorkspaceToOutput ## move workspace to a specific output
    opMoveWorkspaceToIndex  ## reorder workspace
    opSpawnWindow           ## launch a new process
    opWaitForWindow         ## wait for a launched window to appear
    opMatchExistingWindow   ## find an existing window matching a rule
    opMoveWindowToWorkspace ## move window to target workspace
    opMoveWindowToTiling    ## move floating window to tiling
    opMoveWindowToFloating  ## move tiled window to floating
    opConsumeIntoColumn     ## consume a window into an existing column
    opMoveColumnToIndex     ## reorder a column within its workspace
    opSetColumnWidth        ## set column width
    opSetWindowHeight       ## set window height
    opSetColumnDisplay      ## set normal/tabbed display
    opFocusWindow           ## focus a specific window
    opFocusWorkspace        ## focus a specific workspace

  FocusReq* = enum
    frNone     ## action is ID-addressed, no focus needed
    frWindow   ## requires specific window to be focused
    frColumn   ## requires a window in the target column to be focused

  Operation* = object
    focusReq*:    FocusReq
    focusTarget*: Option[nimri_ipc.WindowId]
    case kind*: OpKind
    of opEnsureWorkspace:
      wsName*:   WorkspaceName
      wsOutput*: Option[string]
    of opMoveWorkspaceToOutput:
      mwsName*:   WorkspaceName
      mwsOutput*: string
    of opMoveWorkspaceToIndex:
      mwiName*:  WorkspaceName
      mwiIndex*: int
    of opSpawnWindow:
      spawnRole*:    WindowRole
      spawnCmd*:     seq[string]
      spawnCwd*:     Option[string]
      spawnEnv*:     Table[string, string]
      spawnMatch*:   MatchRule
      spawnTimeout*: int
    of opWaitForWindow:
      waitRole*:    WindowRole
      waitMatch*:   MatchRule
      waitTimeout*: int
    of opMatchExistingWindow:
      matchRole*: WindowRole
      matchRule*: MatchRule
    of opMoveWindowToWorkspace:
      mtwWindow*:    nimri_ipc.WindowId
      mtwWorkspace*: WorkspaceName
    of opMoveWindowToTiling:
      mttWindow*: nimri_ipc.WindowId
    of opMoveWindowToFloating:
      mtfWindow*: nimri_ipc.WindowId
    of opConsumeIntoColumn:
      cicWindow*: nimri_ipc.WindowId   ## window to consume
      cicTarget*: nimri_ipc.WindowId   ## window already in target column
    of opMoveColumnToIndex:
      mciWindow*: nimri_ipc.WindowId   ## any window in the column
      mciIndex*:  int
    of opSetColumnWidth:
      scwWindow*: nimri_ipc.WindowId
      scwSize*:   SizeSpec
    of opSetWindowHeight:
      swhWindow*: nimri_ipc.WindowId
      swhSize*:   SizeSpec
    of opSetColumnDisplay:
      scdWindow*:  nimri_ipc.WindowId
      scdDisplay*: ColumnDisplay
    of opFocusWindow:
      fwWindow*: nimri_ipc.WindowId
    of opFocusWorkspace:
      fwsName*: WorkspaceName
```

### Step 1.6: Plan result

```nim
type
  PlanResult* = object
    operations*:     seq[Operation]
    matchedWindows*: Table[WindowRole, nimri_ipc.WindowId]
    unmatchedRoles*: seq[WindowRole]
    warnings*:       seq[string]
```

### Step 1.7: Snapshot type

A convenience type that bundles the full Niri state at a point in time. This is the input to the planner and freezer.

```nim
type
  NiriSnapshot* = object
    windows*:         seq[nimri_ipc.Window]
    workspaces*:      seq[nimri_ipc.Workspace]
    outputs*:         Table[string, nimri_ipc.Output]
    focusedWindowId*: Option[nimri_ipc.WindowId]
```

### Step 1.8: Executor result types

```nim
type
  OpOutcome* = enum
    ooCompleted   ## operation executed and confirmed
    ooSkipped     ## already satisfied, no action needed
    ooFailed      ## execution failed
    ooTimeout     ## confirmation event not received in time

  ExecutedOp* = object
    operation*: Operation
    outcome*:   OpOutcome
    message*:   string

  ExecuteResult* = object
    completed*: seq[ExecutedOp]
    failed*:    seq[ExecutedOp]
    skipped*:   seq[ExecutedOp]
    timedOut*:  seq[ExecutedOp]
```

### Checkpoint

Write `tests/test_types.nim`:

```nim
import unittest
import core/types
import nimri_ipc

suite "types":
  test "distinct IDs":
    let p = ProfileName("backend-dev")
    let w = WorkspaceName("code")
    let r = WindowRole("editor")
    check $p == "backend-dev"
    check $w == "code"
    check $r == "editor"

  test "SizeSpec variants":
    let proportion = SizeSpec(kind: skProportion, ratio: 0.62)
    let pixels = SizeSpec(kind: skPixels, px: 800)
    check proportion.ratio == 0.62
    check pixels.px == 800

  test "MatchRule recursive composition":
    let rule = MatchRule(kind: mrAll, allRules: @[
      MatchRule(kind: mrExactAppId, appId: "code"),
      MatchRule(kind: mrRegexTitle, titlePattern: "backend"),
    ])
    check rule.allRules.len == 2
    check rule.allRules[0].kind == mrExactAppId

  test "Operation with focus requirement":
    let op = Operation(
      focusReq: frWindow,
      focusTarget: some(nimri_ipc.WindowId(42)),
      kind: opSetColumnWidth,
      scwWindow: nimri_ipc.WindowId(42),
      scwSize: SizeSpec(kind: skProportion, ratio: 0.62),
    )
    check op.focusReq == frWindow
    check op.kind == opSetColumnWidth
```

---

## Phase 2: Config loader (`core/config.nim`)

The config loader reads TOML profile files and converts them to typed `Profile` objects. It must support both single-file and directory-based profiles.

### Step 2.1: Define raw TOML types

Create `src/core/config.nim`:

```nim
import std/[os, options, tables, strutils, sequtils]
import results
import toml_serialization
import types

# ─── Raw TOML deserialization types ──────────────
# These mirror the TOML structure exactly. Conversion to domain types
# happens in separate procs — this keeps parsing and validation separate.

type
  GlobalConfig* = object
    defaults*: Option[GlobalDefaults]
    outputs*:  Option[Table[string, seq[string]]]
    sidebard*: Option[SidebardIntegrationConfig]

  GlobalDefaults* = object
    timeoutMs*:      Option[int]
    matchExisting*:  Option[bool]
    launchMissing*:  Option[bool]

  SidebardIntegrationConfig* = object
    socket*:          Option[string]
    queryOwnership*:  Option[bool]

  ProfileMetaConfig* = object
    name*:        string
    description*: Option[string]
    options*:     Option[ProfileOptionsConfig]
    outputs*:     Option[Table[string, seq[string]]]

  ProfileOptionsConfig* = object
    matchExisting*:  Option[bool]
    launchMissing*:  Option[bool]
    moveUnmanaged*:  Option[bool]
    closeExtra*:     Option[bool]
    timeoutMs*:      Option[int]
    focusAfterLoad*: Option[string]

  WorkspaceConfig* = object
    workspace*: WorkspaceMetaConfig
    columns*:   seq[ColumnConfig]

  WorkspaceMetaConfig* = object
    name*:   string
    output*: Option[string]
    index*:  Option[int]
    focus*:  Option[string]

  ColumnConfig* = object
    id*:      Option[string]
    width*:   Option[float]
    widthPx*: Option[int]
    display*: Option[string]
    windows*: seq[WindowConfig]

  WindowConfig* = object
    id*:       string
    command*:  Option[seq[string]]
    cwd*:      Option[string]
    env*:      Option[Table[string, string]]
    match*:    Option[MatchConfig]
    height*:   Option[float]
    heightPx*: Option[int]
    floating*: Option[bool]

  MatchConfig* = object
    appId*:      Option[string]
    appIdRegex*: Option[string]
    title*:      Option[string]
    titleRegex*: Option[string]
    workspace*:  Option[string]
    any*:        Option[seq[MatchConfig]]
    not_rule*:   Option[MatchConfig]  # "not" is a keyword

  SingleFileProfileConfig* = object
    name*:        string
    description*: Option[string]
    options*:     Option[ProfileOptionsConfig]
    outputs*:     Option[Table[string, seq[string]]]
    workspaces*:  seq[SingleFileWorkspaceConfig]

  SingleFileWorkspaceConfig* = object
    name*:    string
    output*:  Option[string]
    index*:   Option[int]
    focus*:   Option[string]
    columns*: seq[ColumnConfig]
```

### Step 2.2: Match rule conversion

Convert a `MatchConfig` (flat TOML representation) to a `MatchRule` (recursive typed tree):

```nim
proc toMatchRule*(cfg: MatchConfig): Result[MatchRule, string] =
  ## Convert a TOML match config to a typed MatchRule.
  ## Flat fields (app_id, title_regex, etc.) become an implicit All(...).
  ## Explicit `any` and `not` keys enable composition.
  var rules: seq[MatchRule] = @[]

  if cfg.appId.isSome:
    rules.add(MatchRule(kind: mrExactAppId, appId: cfg.appId.get))
  if cfg.appIdRegex.isSome:
    rules.add(MatchRule(kind: mrRegexAppId, appIdPattern: cfg.appIdRegex.get))
  if cfg.title.isSome:
    rules.add(MatchRule(kind: mrExactTitle, title: cfg.title.get))
  if cfg.titleRegex.isSome:
    rules.add(MatchRule(kind: mrRegexTitle, titlePattern: cfg.titleRegex.get))
  if cfg.workspace.isSome:
    rules.add(MatchRule(kind: mrWorkspaceName, workspace: cfg.workspace.get))

  if cfg.any.isSome:
    var anyRules: seq[MatchRule] = @[]
    for sub in cfg.any.get:
      let subRes = toMatchRule(sub)
      if subRes.isErr: return err(subRes.error)
      anyRules.add(subRes.get)
    rules.add(MatchRule(kind: mrAny, anyRules: anyRules))

  if cfg.not_rule.isSome:
    let negRes = toMatchRule(cfg.not_rule.get)
    if negRes.isErr: return err(negRes.error)
    rules.add(MatchRule(kind: mrNot, negated: negRes.get))

  if rules.len == 0:
    return err("match rule has no criteria")
  elif rules.len == 1:
    ok(rules[0])
  else:
    ok(MatchRule(kind: mrAll, allRules: rules))
```

### Step 2.3: Full profile conversion

```nim
proc toSizeSpec*(ratio: Option[float], px: Option[int]): Option[SizeSpec] =
  if ratio.isSome:
    some(SizeSpec(kind: skProportion, ratio: ratio.get))
  elif px.isSome:
    some(SizeSpec(kind: skPixels, px: px.get))
  else:
    none(SizeSpec)

proc toColumnDisplay*(s: Option[string]): ColumnDisplay =
  if s.isNone: return cdNormal
  case s.get.toLowerAscii
  of "tabbed": cdTabbed
  else: cdNormal

proc toWindowSpec*(cfg: WindowConfig): Result[WindowSpec, string] =
  var matchRule: MatchRule
  if cfg.match.isSome:
    let matchRes = toMatchRule(cfg.match.get)
    if matchRes.isErr:
      return err("window " & cfg.id & ": " & matchRes.error)
    matchRule = matchRes.get
  else:
    # No match rule — at minimum require a command so we can spawn
    if cfg.command.isNone:
      return err("window " & cfg.id & ": must have either match or command")
    # Create an empty match rule (will rely on PID-from-spawn)
    matchRule = MatchRule(kind: mrPidFromSpawn)

  ok(WindowSpec(
    id: WindowRole(cfg.id),
    command: cfg.command,
    cwd: cfg.cwd,
    env: if cfg.env.isSome: cfg.env.get else: initTable[string, string](),
    match: matchRule,
    height: toSizeSpec(cfg.height, cfg.heightPx),
    floating: cfg.floating.get(false),
  ))

proc toColumnSpec*(cfg: ColumnConfig): Result[ColumnSpec, string] =
  var windows: seq[WindowSpec] = @[]
  for winCfg in cfg.windows:
    let winRes = toWindowSpec(winCfg)
    if winRes.isErr: return err(winRes.error)
    windows.add(winRes.get)

  ok(ColumnSpec(
    id: if cfg.id.isSome: some(ColumnRole(cfg.id.get)) else: none(ColumnRole),
    width: toSizeSpec(cfg.width, cfg.widthPx),
    display: toColumnDisplay(cfg.display),
    windows: windows,
  ))

proc toWorkspaceSpec*(cfg: WorkspaceMetaConfig, columns: seq[ColumnConfig]): Result[WorkspaceSpec, string] =
  var colSpecs: seq[ColumnSpec] = @[]
  for colCfg in columns:
    let colRes = toColumnSpec(colCfg)
    if colRes.isErr: return err(colRes.error)
    colSpecs.add(colRes.get)

  ok(WorkspaceSpec(
    name: WorkspaceName(cfg.name),
    output: cfg.output,
    index: cfg.index,
    focus: if cfg.focus.isSome: some(WindowRole(cfg.focus.get)) else: none(WindowRole),
    columns: colSpecs,
  ))

proc defaultOptions*(globalDefaults: Option[GlobalDefaults]): ProfileOptions =
  result = ProfileOptions(
    matchExisting: true,
    launchMissing: true,
    moveUnmanaged: false,
    closeExtra: false,
    timeoutMs: 20000,
    focusAfterLoad: none(string),
  )
  if globalDefaults.isSome:
    let d = globalDefaults.get
    if d.timeoutMs.isSome: result.timeoutMs = d.timeoutMs.get
    if d.matchExisting.isSome: result.matchExisting = d.matchExisting.get
    if d.launchMissing.isSome: result.launchMissing = d.launchMissing.get

proc mergeOptions*(base: ProfileOptions, override: Option[ProfileOptionsConfig]): ProfileOptions =
  result = base
  if override.isNone: return
  let o = override.get
  if o.matchExisting.isSome: result.matchExisting = o.matchExisting.get
  if o.launchMissing.isSome: result.launchMissing = o.launchMissing.get
  if o.moveUnmanaged.isSome: result.moveUnmanaged = o.moveUnmanaged.get
  if o.closeExtra.isSome:    result.closeExtra = o.closeExtra.get
  if o.timeoutMs.isSome:     result.timeoutMs = o.timeoutMs.get
  if o.focusAfterLoad.isSome: result.focusAfterLoad = o.focusAfterLoad
```

### Step 2.4: Profile loaders

```nim
proc loadGlobalConfig*(configDir: string): Result[GlobalConfig, string] =
  let path = configDir / "config.toml"
  if not fileExists(path):
    return ok(GlobalConfig())  # global config is optional
  try:
    ok(Toml.loadFile(path, GlobalConfig))
  except CatchableError as e:
    err("failed to parse " & path & ": " & e.msg)

proc loadDirectoryProfile*(
  dir: string,
  globalDefaults: Option[GlobalDefaults],
  globalOutputs: OutputAliases,
): Result[Profile, string] =
  ## Load a directory-based profile: profile.toml + workspace *.toml files.
  let metaPath = dir / "profile.toml"
  if not fileExists(metaPath):
    return err("profile.toml not found in " & dir)

  let meta = try:
    Toml.loadFile(metaPath, ProfileMetaConfig)
  except CatchableError as e:
    return err("failed to parse " & metaPath & ": " & e.msg)

  var options = defaultOptions(globalDefaults)
  options = mergeOptions(options, meta.options)

  # Merge output aliases: global, then profile-level
  var outputs = globalOutputs
  if meta.outputs.isSome:
    for alias, names in meta.outputs.get:
      outputs[OutputAlias(alias)] = names

  # Load workspace files (all .toml files except profile.toml)
  var workspaces: seq[WorkspaceSpec] = @[]
  for kind, path in walkDir(dir):
    if kind == pcFile and path.endsWith(".toml") and extractFilename(path) != "profile.toml":
      let wsCfg = try:
        Toml.loadFile(path, WorkspaceConfig)
      except CatchableError as e:
        return err("failed to parse " & path & ": " & e.msg)

      let wsRes = toWorkspaceSpec(wsCfg.workspace, wsCfg.columns)
      if wsRes.isErr: return err(extractFilename(path) & ": " & wsRes.error)
      workspaces.add(wsRes.get)

  # Sort workspaces by index if provided
  workspaces.sort(proc(a, b: WorkspaceSpec): int =
    let ai = a.index.get(high(int))
    let bi = b.index.get(high(int))
    cmp(ai, bi)
  )

  ok(Profile(
    name: ProfileName(meta.name),
    description: meta.description.get(""),
    options: options,
    outputs: outputs,
    workspaces: workspaces,
  ))

proc loadSingleFileProfile*(
  path: string,
  globalDefaults: Option[GlobalDefaults],
  globalOutputs: OutputAliases,
): Result[Profile, string] =
  ## Load a single-file profile (all workspaces in one TOML).
  let cfg = try:
    Toml.loadFile(path, SingleFileProfileConfig)
  except CatchableError as e:
    return err("failed to parse " & path & ": " & e.msg)

  var options = defaultOptions(globalDefaults)
  options = mergeOptions(options, cfg.options)

  var outputs = globalOutputs
  if cfg.outputs.isSome:
    for alias, names in cfg.outputs.get:
      outputs[OutputAlias(alias)] = names

  var workspaces: seq[WorkspaceSpec] = @[]
  for wsCfg in cfg.workspaces:
    let meta = WorkspaceMetaConfig(
      name: wsCfg.name,
      output: wsCfg.output,
      index: wsCfg.index,
      focus: wsCfg.focus,
    )
    let wsRes = toWorkspaceSpec(meta, wsCfg.columns)
    if wsRes.isErr: return err(wsRes.error)
    workspaces.add(wsRes.get)

  ok(Profile(
    name: ProfileName(cfg.name),
    description: cfg.description.get(""),
    options: options,
    outputs: outputs,
    workspaces: workspaces,
  ))

proc loadProfile*(
  profilePath: string,
  globalDefaults: Option[GlobalDefaults],
  globalOutputs: OutputAliases,
): Result[Profile, string] =
  ## Load a profile from either a directory or a single file.
  if dirExists(profilePath):
    loadDirectoryProfile(profilePath, globalDefaults, globalOutputs)
  elif fileExists(profilePath):
    loadSingleFileProfile(profilePath, globalDefaults, globalOutputs)
  else:
    err("profile not found: " & profilePath)

proc resolveProfilePath*(configDir: string, name: string): string =
  ## Resolve a profile name to its path.
  ## Checks: profiles/<name>/ (directory) then profiles/<name>.toml (file).
  let dirPath = configDir / "profiles" / name
  if dirExists(dirPath): return dirPath
  let filePath = configDir / "profiles" / name & ".toml"
  if fileExists(filePath): return filePath
  return dirPath  # will fail in loadProfile with a clear error

proc listProfiles*(configDir: string): seq[string] =
  ## List all profile names found in the profiles directory.
  let profilesDir = configDir / "profiles"
  if not dirExists(profilesDir): return @[]
  for kind, path in walkDir(profilesDir):
    let name = extractFilename(path)
    case kind
    of pcDir:
      if fileExists(path / "profile.toml"):
        result.add(name)
    of pcFile:
      if name.endsWith(".toml"):
        result.add(name.changeFileExt(""))
    else: discard
```

### Step 2.5: Output alias resolution

```nim
proc resolveOutput*(
  alias: string,
  aliases: OutputAliases,
  availableOutputs: Table[string, nimri_ipc.Output],
): Option[string] =
  ## Resolve an output alias to an actual connected output name.
  ## If the alias is already a real output name, return it directly.

  # Direct name?
  if alias in availableOutputs:
    return some(alias)

  # Alias lookup?
  let aliasId = OutputAlias(alias)
  if aliasId in aliases:
    for candidate in aliases[aliasId]:
      if candidate in availableOutputs:
        return some(candidate)

  none(string)
```

### Checkpoint

Create test fixtures:

**`tests/fixtures/profiles/backend-dev/profile.toml`:**
```toml
name = "backend-dev"
description = "Backend development layout"

[options]
match_existing = true
launch_missing = true
timeout_ms = 15000
focus_after_load = "code/editor"

[outputs]
primary = ["DP-1", "eDP-1"]
```

**`tests/fixtures/profiles/backend-dev/code.toml`:**
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

**`tests/fixtures/profiles/personal.toml`:**
```toml
name = "personal"
description = "Chat and media"

[[workspaces]]
name = "personal:chat"

[[workspaces.columns]]
width = 1.0

[[workspaces.columns.windows]]
id = "discord"
command = ["vesktop"]

[workspaces.columns.windows.match]
app_id = "vesktop"
```

Write `tests/test_config.nim`:
- Load directory profile → verify 1 workspace, 2 columns, correct match rules
- Load single-file profile → verify structure
- Load with global config → verify option merging
- Invalid TOML → returns error
- Missing profile.toml → returns error
- Match rule composition: `any = [...]` produces `mrAny`
- Output alias resolution with available outputs

---

## Phase 3: Matcher (`core/matcher.nim`)

The matcher evaluates `MatchRule` trees against windows. It is **pure** — no I/O.

### Step 3.1: Create `src/core/matcher.nim`

```nim
import std/[options, tables, re, strutils, sequtils, algorithm, times]
import types
import nimri_ipc

proc evaluate*(rule: MatchRule, window: nimri_ipc.Window,
               context: MatchContext): MatchResult =
  ## Recursively evaluate a match rule against a window.
  ## Returns matched=true/false with full explanation trace.

  case rule.kind

  of mrExactAppId:
    if window.appId.isSome and window.appId.get == rule.appId:
      MatchResult(matched: true,
        explanation: @["✓ app_id = \"" & rule.appId & "\" (exact match)"])
    else:
      let actual = window.appId.get("")
      MatchResult(matched: false,
        explanation: @["✗ app_id = \"" & rule.appId & "\" did not match \"" & actual & "\""])

  of mrRegexAppId:
    if window.appId.isSome and window.appId.get.match(re(rule.appIdPattern)):
      MatchResult(matched: true,
        explanation: @["✓ app_id_regex \"" & rule.appIdPattern & "\" matched \"" & window.appId.get & "\""])
    else:
      let actual = window.appId.get("")
      MatchResult(matched: false,
        explanation: @["✗ app_id_regex \"" & rule.appIdPattern & "\" did not match \"" & actual & "\""])

  of mrExactTitle:
    if window.title.isSome and window.title.get == rule.title:
      MatchResult(matched: true,
        explanation: @["✓ title = \"" & rule.title & "\" (exact match)"])
    else:
      let actual = window.title.get("")
      MatchResult(matched: false,
        explanation: @["✗ title = \"" & rule.title & "\" did not match \"" & actual & "\""])

  of mrRegexTitle:
    if window.title.isSome and window.title.get.match(re(rule.titlePattern)):
      MatchResult(matched: true,
        explanation: @["✓ title_regex \"" & rule.titlePattern & "\" matched \"" & window.title.get & "\""])
    else:
      let actual = window.title.get("")
      MatchResult(matched: false,
        explanation: @["✗ title_regex \"" & rule.titlePattern & "\" did not match \"" & actual & "\""])

  of mrWorkspaceName:
    let wid = window.workspaceId
    if wid.isSome and wid.get in context.workspaceNames:
      let wsName = context.workspaceNames[wid.get]
      if wsName == rule.workspace:
        MatchResult(matched: true,
          explanation: @["✓ workspace = \"" & rule.workspace & "\""])
      else:
        MatchResult(matched: false,
          explanation: @["✗ workspace = \"" & rule.workspace & "\" but window is on \"" & wsName & "\""])
    else:
      MatchResult(matched: false,
        explanation: @["✗ workspace = \"" & rule.workspace & "\" — window has no workspace"])

  of mrPidFromSpawn:
    # This is evaluated contextually by the executor, not the matcher
    MatchResult(matched: false,
      explanation: @["? pid_from_spawn — evaluated during execution"])

  of mrOpenedAfter:
    # Also contextual — requires knowing when the window opened
    MatchResult(matched: false,
      explanation: @["? opened_after — evaluated during execution"])

  of mrAll:
    var explanations: seq[string] = @[]
    for sub in rule.allRules:
      let r = evaluate(sub, window, context)
      explanations.add(r.explanation)
      if not r.matched:
        return MatchResult(matched: false, explanation: explanations.concat)
    MatchResult(matched: true, explanation: explanations.concat)

  of mrAny:
    var explanations: seq[string] = @[]
    for sub in rule.anyRules:
      let r = evaluate(sub, window, context)
      explanations.add(r.explanation)
      if r.matched:
        return MatchResult(matched: true, explanation: explanations.concat)
    MatchResult(matched: false, explanation: explanations.concat)

  of mrNot:
    let r = evaluate(rule.negated, window, context)
    if r.matched:
      MatchResult(matched: false,
        explanation: @["✗ NOT matched: "] & r.explanation)
    else:
      MatchResult(matched: true,
        explanation: @["✓ NOT (correctly did not match): "] & r.explanation)
```

### Step 3.2: Candidate ranking

```nim
type
  RankedMatch* = object
    window*:      nimri_ipc.Window
    result*:      MatchResult
    specificity*: int       ## number of non-trivial rules that matched
    recency*:     uint64    ## focus timestamp for tie-breaking

proc countSpecificity(rule: MatchRule, window: nimri_ipc.Window, context: MatchContext): int =
  ## Count how many "leaf" rules in the tree matched.
  let r = evaluate(rule, window, context)
  if not r.matched: return 0
  case rule.kind
  of mrAll:
    var count = 0
    for sub in rule.allRules:
      count += countSpecificity(sub, window, context)
    count
  of mrAny:
    # For OR, count the best-matching branch
    var best = 0
    for sub in rule.anyRules:
      best = max(best, countSpecificity(sub, window, context))
    best
  of mrNot:
    1  # negation counts as one criterion
  of mrPidFromSpawn, mrOpenedAfter:
    0  # contextual, not counted
  else:
    1  # each leaf rule counts as one

proc findMatches*(
  rule: MatchRule,
  windows: seq[nimri_ipc.Window],
  context: MatchContext,
): seq[RankedMatch] =
  ## Evaluate rule against all candidate windows.
  ## Return matched windows sorted by specificity (descending), then recency.
  for w in windows:
    let r = evaluate(rule, w, context)
    if r.matched:
      let ts = if w.focusTimestamp.isSome: w.focusTimestamp.get.secs else: 0'u64
      result.add(RankedMatch(
        window: w,
        result: r,
        specificity: countSpecificity(rule, w, context),
        recency: ts,
      ))

  # Sort: highest specificity first, then most recent
  result.sort(proc(a, b: RankedMatch): int =
    let specCmp = cmp(b.specificity, a.specificity)  # descending
    if specCmp != 0: specCmp
    else: cmp(b.recency, a.recency)  # descending
  )
```

### Checkpoint

Write `tests/test_matcher.nim`:

1. **Exact appId match:** rule `mrExactAppId("code")` matches window with `appId = "code"`
2. **Regex appId match:** rule `mrRegexAppId("(?i)chrome|chromium")` matches both
3. **Title regex:** `mrRegexTitle("backend")` matches window with title containing "backend"
4. **Composition:** `All(ExactAppId("code"), RegexTitle("backend"))` — both must match
5. **Any:** `Any(ExactAppId("chrome"), ExactAppId("firefox"))` — either matches
6. **Not:** `All(ExactAppId("code"), Not(RegexTitle("Settings")))` — excludes settings window
7. **No match:** rule doesn't match → `matched = false` with explanation
8. **Ranking:** multiple candidates, verify sorted by specificity then recency
9. **Explanation trace:** verify that explanation strings describe what happened

---

## Phase 4: Freezer (`core/freezer.nim`)

The freezer captures current Niri state as a `Profile`. It's **pure** — takes a snapshot, returns a profile.

### Step 4.1: Create `src/core/freezer.nim`

```nim
import std/[options, tables, sequtils, strutils, algorithm]
import types
import nimri_ipc

type
  FreezeOptions* = object
    includeAll*:       bool           ## include unnamed workspaces
    workspaceFilter*:  Option[string] ## glob pattern for workspace names
    annotateCommands*: bool           ## look up launch commands from state file
    outputFormat*:     FreezeFormat
    profileName*:      string

  FreezeFormat* = enum
    ffSingleFile    ## one TOML file
    ffDirectory     ## split into workspace files

proc matchesGlob(name: string, pattern: string): bool =
  ## Simple glob matching: "*" matches anything, "?" matches one char.
  ## For v1, just support prefix* and exact match.
  if pattern.endsWith("*"):
    name.startsWith(pattern[0..^2])
  else:
    name == pattern

proc shouldIncludeWorkspace(ws: nimri_ipc.Workspace, options: FreezeOptions): bool =
  if ws.name.isNone and not options.includeAll:
    return false
  if options.workspaceFilter.isSome and ws.name.isSome:
    return matchesGlob(ws.name.get, options.workspaceFilter.get)
  true

proc groupWindowsByColumn(
  windows: seq[nimri_ipc.Window],
  wsId: nimri_ipc.WorkspaceId,
): seq[seq[nimri_ipc.Window]] =
  ## Group windows belonging to a workspace by their column index.
  ## Uses posInScrollingLayout from WindowLayout.
  var byColumn: Table[int, seq[nimri_ipc.Window]] = initTable[int, seq[nimri_ipc.Window]]()

  for w in windows:
    if w.workspaceId != some(wsId): continue
    if w.isFloating: continue  # floating windows handled separately

    let colIdx = if w.layout.posInScrollingLayout.isSome:
      w.layout.posInScrollingLayout.get.col
    else:
      0

    if colIdx notin byColumn:
      byColumn[colIdx] = @[]
    byColumn[colIdx].add(w)

  # Sort by column index
  var indices = byColumn.keys.toSeq.sorted
  for idx in indices:
    # Sort windows within column by tile index
    var winsInCol = byColumn[idx]
    winsInCol.sort(proc(a, b: nimri_ipc.Window): int =
      let ai = if a.layout.posInScrollingLayout.isSome: a.layout.posInScrollingLayout.get.win else: 0
      let bi = if b.layout.posInScrollingLayout.isSome: b.layout.posInScrollingLayout.get.win else: 0
      cmp(ai, bi)
    )
    result.add(winsInCol)

proc windowToSpec(w: nimri_ipc.Window, managed: Option[ManagedState]): WindowSpec =
  ## Generate a WindowSpec from a live window.
  var matchRule: MatchRule
  if w.appId.isSome:
    matchRule = MatchRule(kind: mrExactAppId, appId: w.appId.get)
  else:
    matchRule = MatchRule(kind: mrPidFromSpawn)

  # Look up launch command from managed state if available
  var command: Option[seq[string]] = none(seq[string])
  if managed.isSome:
    for _, profile in managed.get.profiles:
      for role, mw in profile.windows:
        if mw.niriId == some(w.id) and mw.launchCommand.isSome:
          command = mw.launchCommand

  let roleId = if w.appId.isSome:
    w.appId.get.split('.')[^1].toLowerAscii
  else:
    "window-" & $w.id

  WindowSpec(
    id: WindowRole(roleId),
    command: command,
    cwd: none(string),
    env: initTable[string, string](),
    match: matchRule,
    height: none(SizeSpec),
    floating: w.isFloating,
  )

proc columnToSpec(
  windows: seq[nimri_ipc.Window],
  colIdx: int,
  managed: Option[ManagedState],
): ColumnSpec =
  ## Generate a ColumnSpec from a group of windows in a column.
  var winSpecs: seq[WindowSpec] = @[]
  for w in windows:
    winSpecs.add(windowToSpec(w, managed))

  # Estimate column width from tile sizes
  var width: Option[SizeSpec] = none(SizeSpec)
  if windows.len > 0 and windows[0].layout.tileSize.w > 0:
    # tileSize.w is a proportion when in scrolling layout
    let ratio = windows[0].layout.tileSize.w
    if ratio > 0.0 and ratio <= 1.0:
      width = some(SizeSpec(kind: skProportion, ratio: ratio))

  ColumnSpec(
    id: some(ColumnRole("col-" & $colIdx)),
    width: width,
    display: cdNormal,
    windows: winSpecs,
  )

proc freeze*(
  snapshot: NiriSnapshot,
  options: FreezeOptions,
  managed: Option[ManagedState] = none(ManagedState),
): Profile =
  ## Pure function: Niri state → Profile.
  var workspaces: seq[WorkspaceSpec] = @[]

  for ws in snapshot.workspaces:
    if not shouldIncludeWorkspace(ws, options):
      continue

    let columns = groupWindowsByColumn(snapshot.windows, ws.id)
    var colSpecs: seq[ColumnSpec] = @[]
    for i, colWindows in columns:
      colSpecs.add(columnToSpec(colWindows, i, managed))

    workspaces.add(WorkspaceSpec(
      name: WorkspaceName(ws.name.get("workspace-" & $ws.id)),
      output: ws.output,
      index: some(int(ws.idx)),
      focus: none(WindowRole),
      columns: colSpecs,
    ))

  Profile(
    name: ProfileName(options.profileName),
    description: "Frozen from live state",
    options: ProfileOptions(
      matchExisting: true,
      launchMissing: true,
      moveUnmanaged: false,
      closeExtra: false,
      timeoutMs: 20000,
      focusAfterLoad: none(string),
    ),
    outputs: initTable[OutputAlias, seq[string]](),
    workspaces: workspaces,
  )
```

### Step 4.2: TOML serialization

```nim
proc profileToToml*(profile: Profile): string =
  ## Serialize a Profile to TOML format.
  ## For v1, produce single-file format.
  var lines: seq[string] = @[]
  lines.add("name = " & profile.name.string.quoteToml)
  lines.add("description = " & profile.description.quoteToml)
  lines.add("")

  for ws in profile.workspaces:
    lines.add("[[workspaces]]")
    lines.add("name = " & ws.name.string.quoteToml)
    if ws.output.isSome:
      lines.add("output = " & ws.output.get.quoteToml)
    if ws.index.isSome:
      lines.add("index = " & $ws.index.get)
    lines.add("")

    for col in ws.columns:
      lines.add("[[workspaces.columns]]")
      if col.width.isSome:
        case col.width.get.kind
        of skProportion: lines.add("width = " & $col.width.get.ratio)
        of skPixels:     lines.add("width_px = " & $col.width.get.px)
      lines.add("")

      for win in col.windows:
        lines.add("[[workspaces.columns.windows]]")
        lines.add("id = " & win.id.string.quoteToml)
        if win.command.isSome:
          lines.add("command = [" & win.command.get.mapIt(it.quoteToml).join(", ") & "]")
        lines.add("")
        lines.add("[workspaces.columns.windows.match]")
        case win.match.kind
        of mrExactAppId:
          lines.add("app_id = " & win.match.appId.quoteToml)
        of mrRegexAppId:
          lines.add("app_id_regex = " & win.match.appIdPattern.quoteToml)
        else: discard
        lines.add("")

  lines.join("\n")

proc quoteToml(s: string): string =
  "\"" & s.replace("\\", "\\\\").replace("\"", "\\\"") & "\""
```

### Checkpoint

Write `tests/test_freezer.nim`:

- Create a `NiriSnapshot` with 2 named workspaces, 3 windows across 2 columns
- `freeze(snapshot, options)` produces a `Profile` with correct workspace/column/window structure
- Column widths are captured from layout data
- Unnamed workspaces excluded when `includeAll = false`
- Workspace filter `"backend:*"` includes only matching workspaces
- Frozen profile serializes to valid TOML that can be re-parsed by the config loader (round-trip test)

---

## Phase 5: Planner (`core/planner.nim`)

The planner is the core algorithm. It compares a desired `Profile` against the current `NiriSnapshot` and produces a `seq[Operation]`. It is **pure** — no I/O, no async.

### Step 5.1: Create `src/core/planner.nim`

```nim
import std/[options, tables, sequtils, algorithm, strutils]
import types
import matcher
import nimri_ipc

type
  PlanContext = object
    profile: Profile
    snapshot: NiriSnapshot
    managed: ManagedState
    matchContext: MatchContext
    matched: Table[WindowRole, nimri_ipc.WindowId]
    claimed: HashSet[nimri_ipc.WindowId]  # windows already matched to a role
    warnings: seq[string]
```

### Step 5.2: Workspace planning

```nim
proc planWorkspaces(ctx: var PlanContext): seq[Operation] =
  ## Ensure all profile workspaces exist.
  result = @[]

  let existingWsByName = ctx.snapshot.workspaces.filterIt(it.name.isSome)
    .mapIt((it.name.get, it)).toTable

  for wsSpec in ctx.profile.workspaces:
    let name = $wsSpec.name
    if name in existingWsByName:
      let existing = existingWsByName[name]
      # Workspace exists — check output
      if wsSpec.output.isSome:
        let targetOutput = wsSpec.output.get
        if existing.output.isSome and existing.output.get != targetOutput:
          result.add Operation(
            focusReq: frNone,
            focusTarget: none(nimri_ipc.WindowId),
            kind: opMoveWorkspaceToOutput,
            mwsName: wsSpec.name,
            mwsOutput: targetOutput,
          )
      # Check index
      if wsSpec.index.isSome:
        let targetIdx = wsSpec.index.get
        if int(existing.idx) != targetIdx:
          result.add Operation(
            focusReq: frNone,
            focusTarget: none(nimri_ipc.WindowId),
            kind: opMoveWorkspaceToIndex,
            mwiName: wsSpec.name,
            mwiIndex: targetIdx,
          )
    else:
      # Workspace doesn't exist — create it (by setting its name)
      result.add Operation(
        focusReq: frNone,
        focusTarget: none(nimri_ipc.WindowId),
        kind: opEnsureWorkspace,
        wsName: wsSpec.name,
        wsOutput: wsSpec.output,
      )
```

### Step 5.3: Window matching

```nim
proc planWindowMatching(ctx: var PlanContext): seq[Operation] =
  ## Match existing windows to profile roles.
  result = @[]

  if not ctx.profile.options.matchExisting:
    return

  for wsSpec in ctx.profile.workspaces:
    for colSpec in wsSpec.columns:
      for winSpec in colSpec.windows:
        if winSpec.id in ctx.matched:
          continue  # already matched

        # Find candidates (windows not yet claimed by another role)
        let candidates = ctx.snapshot.windows.filterIt(
          it.id notin ctx.claimed
        )

        let matches = findMatches(winSpec.match, candidates, ctx.matchContext)
        if matches.len > 0:
          let best = matches[0]
          ctx.matched[winSpec.id] = best.window.id
          ctx.claimed.incl(best.window.id)

          result.add Operation(
            focusReq: frNone,
            focusTarget: none(nimri_ipc.WindowId),
            kind: opMatchExistingWindow,
            matchRole: winSpec.id,
            matchRule: winSpec.match,
          )
```

### Step 5.4: Launch planning

```nim
proc planLaunches(ctx: var PlanContext): seq[Operation] =
  ## Plan spawns for unmatched roles that have commands.
  result = @[]

  if not ctx.profile.options.launchMissing:
    return

  for wsSpec in ctx.profile.workspaces:
    for colSpec in wsSpec.columns:
      for winSpec in colSpec.windows:
        if winSpec.id in ctx.matched:
          continue
        if winSpec.command.isNone:
          ctx.warnings.add("Window role \"" & $winSpec.id &
            "\" has no match and no command — cannot spawn")
          continue

        result.add Operation(
          focusReq: frNone,
          focusTarget: none(nimri_ipc.WindowId),
          kind: opSpawnWindow,
          spawnRole: winSpec.id,
          spawnCmd: winSpec.command.get,
          spawnCwd: winSpec.cwd,
          spawnEnv: winSpec.env,
          spawnMatch: winSpec.match,
          spawnTimeout: ctx.profile.options.timeoutMs,
        )
```

### Step 5.5: Movement planning

```nim
proc planMoves(ctx: var PlanContext): seq[Operation] =
  ## Plan moves for matched windows not in the correct workspace.
  result = @[]

  let wsByName = ctx.snapshot.workspaces.filterIt(it.name.isSome)
    .mapIt((it.name.get, it)).toTable

  for wsSpec in ctx.profile.workspaces:
    let wsName = $wsSpec.name
    if wsName notin wsByName:
      continue  # workspace hasn't been created yet — moves will happen in re-plan
    let targetWs = wsByName[wsName]

    for colSpec in wsSpec.columns:
      for winSpec in colSpec.windows:
        if winSpec.id notin ctx.matched:
          continue

        let windowId = ctx.matched[winSpec.id]
        # Find the window's current workspace
        let window = ctx.snapshot.windows.filterIt(it.id == windowId)
        if window.len == 0:
          continue

        let currentWsId = window[0].workspaceId
        if currentWsId != some(targetWs.id):
          result.add Operation(
            focusReq: frNone,
            focusTarget: none(nimri_ipc.WindowId),
            kind: opMoveWindowToWorkspace,
            mtwWindow: windowId,
            mtwWorkspace: wsSpec.name,
          )

        # Check floating state
        if winSpec.floating and not window[0].isFloating:
          result.add Operation(
            focusReq: frNone,
            focusTarget: none(nimri_ipc.WindowId),
            kind: opMoveWindowToFloating,
            mtfWindow: windowId,
          )
        elif not winSpec.floating and window[0].isFloating:
          result.add Operation(
            focusReq: frNone,
            focusTarget: none(nimri_ipc.WindowId),
            kind: opMoveWindowToTiling,
            mttWindow: windowId,
          )
```

### Step 5.6: Column formation

This is the hardest part of the planner. Windows need to be consumed into columns in the correct order, then sized.

```nim
proc planColumnFormation(ctx: var PlanContext): seq[Operation] =
  ## Plan column formation: consume windows into columns, set widths.
  result = @[]

  let wsByName = ctx.snapshot.workspaces.filterIt(it.name.isSome)
    .mapIt((it.name.get, it)).toTable

  for wsSpec in ctx.profile.workspaces:
    let wsName = $wsSpec.name
    if wsName notin wsByName:
      continue

    for colIdx, colSpec in wsSpec.columns:
      if colSpec.windows.len <= 1:
        continue  # single-window columns don't need consuming

      # First window becomes the column anchor
      let anchorRole = colSpec.windows[0].id
      if anchorRole notin ctx.matched:
        continue
      let anchorId = ctx.matched[anchorRole]

      # Remaining windows need to be consumed into the anchor's column
      for i in 1..<colSpec.windows.len:
        let winRole = colSpec.windows[i].id
        if winRole notin ctx.matched:
          continue
        let windowId = ctx.matched[winRole]

        # Check if already in the same column
        let anchor = ctx.snapshot.windows.filterIt(it.id == anchorId)
        let window = ctx.snapshot.windows.filterIt(it.id == windowId)
        if anchor.len > 0 and window.len > 0:
          let anchorCol = anchor[0].layout.posInScrollingLayout.map(proc(p: auto): int = p.col)
          let windowCol = window[0].layout.posInScrollingLayout.map(proc(p: auto): int = p.col)
          if anchorCol == windowCol:
            continue  # already in the same column

        result.add Operation(
          focusReq: frWindow,
          focusTarget: some(windowId),
          kind: opConsumeIntoColumn,
          cicWindow: windowId,
          cicTarget: anchorId,
        )
```

### Step 5.7: Sizing

```nim
proc planSizing(ctx: var PlanContext): seq[Operation] =
  ## Plan column widths and window heights.
  result = @[]

  for wsSpec in ctx.profile.workspaces:
    for colSpec in wsSpec.columns:
      if colSpec.width.isNone:
        continue

      # Use the first matched window in the column as the sizing target
      for winSpec in colSpec.windows:
        if winSpec.id in ctx.matched:
          let windowId = ctx.matched[winSpec.id]

          # Check current width approximately
          let window = ctx.snapshot.windows.filterIt(it.id == windowId)
          if window.len > 0:
            let currentRatio = window[0].layout.tileSize.w
            let targetSize = colSpec.width.get

            # Only resize if off by more than 2%
            if targetSize.kind == skProportion:
              if abs(currentRatio - targetSize.ratio) > 0.02:
                result.add Operation(
                  focusReq: frColumn,
                  focusTarget: some(windowId),
                  kind: opSetColumnWidth,
                  scwWindow: windowId,
                  scwSize: targetSize,
                )
          break  # only need to size via one window per column

      # Window heights
      for winSpec in colSpec.windows:
        if winSpec.height.isNone: continue
        if winSpec.id notin ctx.matched: continue
        let windowId = ctx.matched[winSpec.id]
        result.add Operation(
          focusReq: frWindow,
          focusTarget: some(windowId),
          kind: opSetWindowHeight,
          swhWindow: windowId,
          swhSize: winSpec.height.get,
        )

      # Column display mode
      if colSpec.display != cdNormal:
        for winSpec in colSpec.windows:
          if winSpec.id in ctx.matched:
            result.add Operation(
              focusReq: frColumn,
              focusTarget: some(ctx.matched[winSpec.id]),
              kind: opSetColumnDisplay,
              scdWindow: ctx.matched[winSpec.id],
              scdDisplay: colSpec.display,
            )
            break
```

### Step 5.8: Focus planning

```nim
proc planFocus(ctx: var PlanContext): seq[Operation] =
  ## Plan final focus after all operations.
  result = @[]

  if ctx.profile.options.focusAfterLoad.isSome:
    let focusPath = ctx.profile.options.focusAfterLoad.get
    # Parse "workspace/role" or just "role"
    let role = WindowRole(focusPath.split("/")[^1])
    if role in ctx.matched:
      result.add Operation(
        focusReq: frNone,
        focusTarget: none(nimri_ipc.WindowId),
        kind: opFocusWindow,
        fwWindow: ctx.matched[role],
      )
  else:
    # Focus the first workspace's focus target, if specified
    for wsSpec in ctx.profile.workspaces:
      if wsSpec.focus.isSome and wsSpec.focus.get in ctx.matched:
        result.add Operation(
          focusReq: frNone,
          focusTarget: none(nimri_ipc.WindowId),
          kind: opFocusWindow,
          fwWindow: ctx.matched[wsSpec.focus.get],
        )
        break
```

### Step 5.9: Top-level planner

```nim
proc plan*(
  profile: Profile,
  snapshot: NiriSnapshot,
  managed: ManagedState,
): PlanResult =
  ## Pure function. No I/O.
  ## Returns the minimum set of operations to reconcile state toward profile.

  # Build workspace name → ID mapping for match context
  var wsNames = initTable[nimri_ipc.WorkspaceId, string]()
  for ws in snapshot.workspaces:
    if ws.name.isSome:
      wsNames[ws.id] = ws.name.get

  var ctx = PlanContext(
    profile: profile,
    snapshot: snapshot,
    managed: managed,
    matchContext: MatchContext(
      spawnTimestamps: initTable[WindowRole, MonoTime](),
      launchedPids: initTable[WindowRole, int](),
      workspaceNames: wsNames,
    ),
    matched: initTable[WindowRole, nimri_ipc.WindowId](),
    claimed: initHashSet[nimri_ipc.WindowId](),
    warnings: @[],
  )

  var ops: seq[Operation] = @[]
  ops.add planWorkspaces(ctx)
  ops.add planWindowMatching(ctx)
  ops.add planLaunches(ctx)
  ops.add planMoves(ctx)
  ops.add planColumnFormation(ctx)
  ops.add planSizing(ctx)
  ops.add planFocus(ctx)

  PlanResult(
    operations: ops,
    matchedWindows: ctx.matched,
    unmatchedRoles: ctx.profile.workspaces
      .mapIt(it.columns.mapIt(it.windows.mapIt(it.id)).concat).concat
      .filterIt(it notin ctx.matched),
    warnings: ctx.warnings,
  )
```

### Checkpoint

Write `tests/test_planner.nim`. This is the most important test file — the planner is the core algorithm.

1. **Empty desktop + full profile:** produces `EnsureWorkspace` + `SpawnWindow` ops
2. **Windows already in place:** produces zero ops (idempotent)
3. **Window matched but wrong workspace:** produces `MoveWindowToWorkspace`
4. **Windows in wrong columns:** produces `ConsumeIntoColumn`
5. **Column width drift > 2%:** produces `SetColumnWidth`
6. **Column width within tolerance:** no sizing op
7. **Missing command, no match:** warning, no crash
8. **`matchExisting = false`:** skips matching, only spawns
9. **`launchMissing = false`:** skips spawning
10. **Focus after load:** final `FocusWindow` op

---

## Phase 6: Diagnostics (`core/diagnostics.nim`)

Human-readable formatting for plans, diffs, and doctor output.

### Step 6.1: Create `src/core/diagnostics.nim`

```nim
import std/[strutils, options, sequtils, tables, terminal]
import types
import nimri_ipc

proc formatPlan*(plan: PlanResult, profile: Profile): string =
  ## Format a plan for human display.
  var lines: seq[string] = @[]
  lines.add("Profile: " & $profile.name)
  lines.add("")

  # Workspaces section
  lines.add("Workspaces:")
  for op in plan.operations:
    case op.kind
    of opEnsureWorkspace:
      let output = if op.wsOutput.isSome: " on " & op.wsOutput.get else: ""
      lines.add("  + " & $op.wsName & " will be created" & output)
    of opMoveWorkspaceToOutput:
      lines.add("  ~ " & $op.mwsName & " will move to " & op.mwsOutput)
    else: discard
  # Mark existing workspaces
  for wsSpec in profile.workspaces:
    let isCreated = plan.operations.anyIt(
      it.kind == opEnsureWorkspace and it.wsName == wsSpec.name)
    if not isCreated:
      let output = wsSpec.output.get("")
      lines.add("  ✓ " & $wsSpec.name & " exists" & (if output.len > 0: " on " & output else: ""))
  lines.add("")

  # Windows section
  lines.add("Windows:")
  for role, winId in plan.matchedWindows:
    let moveOp = plan.operations.filterIt(
      it.kind == opMoveWindowToWorkspace and it.mtwWindow == winId)
    if moveOp.len > 0:
      lines.add("  ~ " & $role & ": matched window " & $winId & " (needs move to " & $moveOp[0].mtwWorkspace & ")")
    else:
      lines.add("  ✓ " & $role & ": matched window " & $winId)

  for role in plan.unmatchedRoles:
    let spawnOp = plan.operations.filterIt(
      it.kind == opSpawnWindow and it.spawnRole == role)
    if spawnOp.len > 0:
      lines.add("  + " & $role & ": will launch " & spawnOp[0].spawnCmd.join(" ").quoteShell)
    else:
      lines.add("  ✗ " & $role & ": missing (no command to spawn)")
  lines.add("")

  # Operations section
  lines.add("Operations (" & $plan.operations.len & "):")
  for i, op in plan.operations:
    lines.add("  " & $(i + 1) & ". " & formatOp(op))
  lines.add("")

  if plan.warnings.len > 0:
    lines.add("Warnings:")
    for w in plan.warnings:
      lines.add("  ⚠ " & w)

  lines.join("\n")

proc formatOp*(op: Operation): string =
  case op.kind
  of opEnsureWorkspace:
    "EnsureWorkspace \"" & $op.wsName & "\"" &
      (if op.wsOutput.isSome: " on " & op.wsOutput.get else: "")
  of opMoveWorkspaceToOutput:
    "MoveWorkspace \"" & $op.mwsName & "\" → " & op.mwsOutput
  of opMoveWorkspaceToIndex:
    "MoveWorkspace \"" & $op.mwiName & "\" → index " & $op.mwiIndex
  of opSpawnWindow:
    "SpawnWindow \"" & $op.spawnRole & "\" → " & op.spawnCmd.join(" ")
  of opWaitForWindow:
    "WaitForWindow \"" & $op.waitRole & "\""
  of opMatchExistingWindow:
    "MatchWindow \"" & $op.matchRole & "\""
  of opMoveWindowToWorkspace:
    "MoveWindow " & $op.mtwWindow & " → workspace \"" & $op.mtwWorkspace & "\""
  of opMoveWindowToTiling:
    "MoveToTiling " & $op.mttWindow
  of opMoveWindowToFloating:
    "MoveToFloating " & $op.mtfWindow
  of opConsumeIntoColumn:
    "ConsumeIntoColumn " & $op.cicWindow & " → column of " & $op.cicTarget
  of opMoveColumnToIndex:
    "MoveColumn [" & $op.mciWindow & "] → index " & $op.mciIndex
  of opSetColumnWidth:
    let sizeStr = case op.scwSize.kind
      of skProportion: $op.scwSize.ratio
      of skPixels: $op.scwSize.px & "px"
    "SetColumnWidth [" & $op.scwWindow & "] → " & sizeStr
  of opSetWindowHeight:
    let sizeStr = case op.swhSize.kind
      of skProportion: $op.swhSize.ratio
      of skPixels: $op.swhSize.px & "px"
    "SetWindowHeight " & $op.swhWindow & " → " & sizeStr
  of opSetColumnDisplay:
    "SetColumnDisplay [" & $op.scdWindow & "] → " & $op.scdDisplay
  of opFocusWindow:
    "FocusWindow " & $op.fwWindow
  of opFocusWorkspace:
    "FocusWorkspace \"" & $op.fwsName & "\""

proc formatDiff*(profile: Profile, snapshot: NiriSnapshot,
                 matched: Table[WindowRole, nimri_ipc.WindowId]): string =
  ## Format a diff between profile and current state.
  var lines: seq[string] = @[]
  lines.add("Profile: " & $profile.name & " vs current state")
  lines.add("")

  var okCount, driftCount, missingCount = 0

  for wsSpec in profile.workspaces:
    lines.add($wsSpec.name)
    for colSpec in wsSpec.columns:
      for winSpec in colSpec.windows:
        if winSpec.id in matched:
          let winId = matched[winSpec.id]
          let wins = snapshot.windows.filterIt(it.id == winId)
          if wins.len > 0:
            # Check if in correct workspace and approximate column
            lines.add("  " & $winSpec.id & "       ✓  matched window " & $winId)
            inc okCount
          else:
            lines.add("  " & $winSpec.id & "       ~  matched but window disappeared")
            inc driftCount
        else:
          lines.add("  " & $winSpec.id & "       ✗  missing (not running)")
          inc missingCount
    lines.add("")

  lines.add("Summary: " & $okCount & " ok, " & $driftCount & " drifted, " & $missingCount & " missing")
  lines.join("\n")

proc formatDoctor*(profile: Profile, snapshot: NiriSnapshot): string =
  ## Validate profile and environment, report issues.
  var lines: seq[string] = @[]
  lines.add("Profile: " & $profile.name)
  lines.add("")
  lines.add("Environment:")

  # Check NIRI_SOCKET
  let socket = getEnv("NIRI_SOCKET")
  if socket.len > 0:
    lines.add("  ✓ $NIRI_SOCKET exists")
  else:
    lines.add("  ✗ $NIRI_SOCKET not set")

  # Check outputs
  for wsSpec in profile.workspaces:
    if wsSpec.output.isSome:
      let output = wsSpec.output.get
      let found = output in snapshot.outputs
      if found:
        lines.add("  ✓ Output \"" & output & "\" present")
      else:
        lines.add("  ⚠ Output \"" & output & "\" not connected")
  lines.add("")

  # Check commands
  lines.add("Windows:")
  for wsSpec in profile.workspaces:
    for colSpec in wsSpec.columns:
      for winSpec in colSpec.windows:
        if winSpec.command.isSome:
          let cmd = winSpec.command.get[0]
          let found = findExe(cmd).len > 0
          if found:
            lines.add("  ✓ " & $winSpec.id & ": \"" & cmd & "\" is on PATH")
          else:
            lines.add("  ✗ " & $winSpec.id & ": \"" & cmd & "\" NOT on PATH")

  lines.join("\n")
```

### Checkpoint

Write `tests/test_diagnostics.nim`: verify formatting produces expected output strings for sample plans, diffs, and doctor results.

---

## Phase 7: Executor (`executor/runner.nim`, `executor/launcher.nim`, `executor/focus.nim`)

The executor is the **only async, I/O-performing** component. It takes a `PlanResult` and executes operations against Niri one at a time, confirming each via the event stream.

### Step 7.1: Focus management (`executor/focus.nim`)

```nim
import std/[options, times]
import chronos
import results
import nimri_ipc
import ../core/types

proc ensureFocus*(
  client: nimri_ipc.NiriClient,
  events: nimri_ipc.NiriEventStream,
  op: Operation,
): Future[Result[void, string]] {.async.} =
  ## If the operation requires focus, focus the target and verify.
  if op.focusReq == frNone:
    return ok()

  if op.focusTarget.isNone:
    return err("Operation requires focus but has no target")

  let targetId = op.focusTarget.get

  # Issue focus command
  let focusAction = nimri_ipc.focusWindow(targetId)
  let actionRes = await client.doAction(focusAction)
  if actionRes.isErr:
    return err("Failed to focus window " & $targetId & ": " & $actionRes.error)

  # Wait for focus confirmation event
  let confirmRes = await events.waitFor(
    proc(e: nimri_ipc.NiriEvent): bool =
      e.kind == nimri_ipc.neWindowFocusChanged and
      e.focusedId == some(targetId),
    initDuration(milliseconds = 2000),
  )

  if confirmRes.isErr:
    return err("Focus on window " & $targetId & " not confirmed: " & $confirmRes.error)

  ok()
```

### Step 7.2: Process launcher (`executor/launcher.nim`)

```nim
import std/[osproc, os, options, tables]
import results
import ../core/types

proc launchProcess*(
  cmd: seq[string],
  cwd: Option[string],
  env: Table[string, string],
): Result[int, string] =
  ## Launch a process and return its PID.
  if cmd.len == 0:
    return err("empty command")

  let workDir = if cwd.isSome: cwd.get.expandTilde else: getCurrentDir()

  try:
    var process: Process
    if env.len > 0:
      # Merge with current environment
      var fullEnv: seq[(string, string)] = @[]
      for key, val in envPairs():
        fullEnv.add((key, val))
      for key, val in env:
        fullEnv.add((key, val))
      process = startProcess(
        cmd[0],
        workingDir = workDir,
        args = cmd[1..^1],
        env = newStringTable(fullEnv),
        options = {poUsePath, poDaemon},
      )
    else:
      process = startProcess(
        cmd[0],
        workingDir = workDir,
        args = cmd[1..^1],
        options = {poUsePath, poDaemon},
      )

    let pid = process.processID
    process.close()  # detach — we don't manage the child
    ok(pid)
  except CatchableError as e:
    err("Failed to launch " & cmd.join(" ") & ": " & e.msg)
```

### Step 7.3: Main executor (`executor/runner.nim`)

```nim
import std/[options, tables, times, sequtils]
import chronos
import results
import chronicles
import nimri_ipc
import ../core/types
import focus
import launcher

proc executeOperation*(
  client: nimri_ipc.NiriClient,
  events: nimri_ipc.NiriEventStream,
  op: Operation,
  snapshot: var NiriSnapshot,
  matchContext: var MatchContext,
): Future[ExecutedOp] {.async.} =
  ## Execute a single operation, verify, return outcome.

  # 1. Ensure focus if needed
  let focusRes = await ensureFocus(client, events, op)
  if focusRes.isErr:
    return ExecutedOp(operation: op, outcome: ooFailed, message: focusRes.error)

  # 2. Execute
  case op.kind

  of opEnsureWorkspace:
    # Niri creates workspaces on demand when you switch to them by name
    let action = nimri_ipc.focusWorkspace(
      nimri_ipc.WorkspaceRef(kind: wrkByName, name: $op.wsName))
    let res = await client.doAction(action)
    if res.isErr:
      return ExecutedOp(operation: op, outcome: ooFailed, message: $res.error)

    # Also set the workspace name if needed
    let nameAction = nimri_ipc.setWorkspaceName($op.wsName)
    discard await client.doAction(nameAction)

    return ExecutedOp(operation: op, outcome: ooCompleted,
      message: "Created workspace " & $op.wsName)

  of opSpawnWindow:
    let launchRes = launchProcess(op.spawnCmd, op.spawnCwd, op.spawnEnv)
    if launchRes.isErr:
      return ExecutedOp(operation: op, outcome: ooFailed, message: launchRes.error)

    let pid = launchRes.get
    info "Spawned process", role = $op.spawnRole, pid = pid

    # Wait for matching window to appear
    let confirmRes = await events.waitFor(
      proc(e: nimri_ipc.NiriEvent): bool =
        if e.kind != nimri_ipc.neWindowOpenedOrChanged:
          return false
        # Basic match: check appId from the match rule
        case op.spawnMatch.kind
        of mrExactAppId:
          e.window.appId == some(op.spawnMatch.appId)
        of mrRegexAppId:
          import re
          e.window.appId.isSome and e.window.appId.get.match(re(op.spawnMatch.appIdPattern))
        else:
          false,
      initDuration(milliseconds = op.spawnTimeout),
    )

    if confirmRes.isErr:
      return ExecutedOp(operation: op, outcome: ooTimeout,
        message: "Window for " & $op.spawnRole & " did not appear within timeout")

    return ExecutedOp(operation: op, outcome: ooCompleted,
      message: "Spawned and matched " & $op.spawnRole)

  of opMoveWindowToWorkspace:
    # Find the target workspace ID by name
    let targetWs = snapshot.workspaces.filterIt(
      it.name == some($op.mtwWorkspace))
    if targetWs.len == 0:
      return ExecutedOp(operation: op, outcome: ooFailed,
        message: "Target workspace " & $op.mtwWorkspace & " not found")

    let action = nimri_ipc.moveWindowToWorkspace(
      nimri_ipc.WorkspaceRef(kind: wrkById, id: targetWs[0].id),
      focus = false,
      windowId = some(op.mtwWindow),
    )
    let res = await client.doAction(action)
    if res.isErr:
      return ExecutedOp(operation: op, outcome: ooFailed, message: $res.error)

    return ExecutedOp(operation: op, outcome: ooCompleted,
      message: "Moved window " & $op.mtwWindow & " to " & $op.mtwWorkspace)

  of opSetColumnWidth:
    let change = case op.scwSize.kind
      of skProportion:
        nimri_ipc.SizeChange(kind: sckSetProportion, propVal: op.scwSize.ratio)
      of skPixels:
        nimri_ipc.SizeChange(kind: sckSetFixed, fixedVal: int32(op.scwSize.px))

    let action = nimri_ipc.setColumnWidth(change)
    let res = await client.doAction(action)
    if res.isErr:
      return ExecutedOp(operation: op, outcome: ooFailed, message: $res.error)

    return ExecutedOp(operation: op, outcome: ooCompleted,
      message: "Set column width for " & $op.scwWindow)

  of opFocusWindow:
    let action = nimri_ipc.focusWindow(op.fwWindow)
    let res = await client.doAction(action)
    if res.isErr:
      return ExecutedOp(operation: op, outcome: ooFailed, message: $res.error)

    return ExecutedOp(operation: op, outcome: ooCompleted,
      message: "Focused window " & $op.fwWindow)

  of opConsumeIntoColumn:
    # Focus the window to consume, then use consumeOrExpelWindowLeft/Right
    let action = nimri_ipc.consumeOrExpelWindowLeft()
    let res = await client.doAction(action)
    if res.isErr:
      return ExecutedOp(operation: op, outcome: ooFailed, message: $res.error)

    return ExecutedOp(operation: op, outcome: ooCompleted,
      message: "Consumed " & $op.cicWindow & " into column")

  of opMatchExistingWindow:
    # Matching is done in the planner — this op is informational
    return ExecutedOp(operation: op, outcome: ooSkipped,
      message: "Match resolved during planning")

  else:
    return ExecutedOp(operation: op, outcome: ooFailed,
      message: "Operation " & $op.kind & " not yet implemented")


proc execute*(
  client: nimri_ipc.NiriClient,
  events: nimri_ipc.NiriEventStream,
  plan: PlanResult,
  snapshot: var NiriSnapshot,
): Future[ExecuteResult] {.async.} =
  ## Execute a plan, operation by operation.
  var result = ExecuteResult()
  var matchContext = MatchContext()

  for op in plan.operations:
    if op.kind == opMatchExistingWindow:
      result.skipped.add(ExecutedOp(operation: op, outcome: ooSkipped, message: "match-only"))
      continue

    info "Executing", op = formatOp(op)
    let outcome = await executeOperation(client, events, op, snapshot, matchContext)

    case outcome.outcome
    of ooCompleted: result.completed.add(outcome)
    of ooSkipped:   result.skipped.add(outcome)
    of ooFailed:    result.failed.add(outcome)
    of ooTimeout:   result.timedOut.add(outcome)

    if outcome.outcome == ooFailed:
      warn "Operation failed", op = formatOp(op), message = outcome.message
      # Continue with remaining ops — don't abort the whole plan

  return result
```

### Checkpoint

Integration test (requires running Niri with at least one window):

- Execute a plan with `opFocusWindow` → verify focus changed
- Execute `opEnsureWorkspace` → verify workspace created
- Execute `opSpawnWindow` with a known command (e.g., `["foot"]`) → verify window appears

---

## Phase 8: Managed state (`state/managed.nim`)

### Step 8.1: Create `src/state/managed.nim`

```nim
import std/[os, json, options, tables, times]
import results
import ../core/types
import nimri_ipc

proc statePath*(): string =
  getEnv("XDG_STATE_HOME", getHomeDir() / ".local/share") / "nirip" / "state.json"

proc loadManagedState*(path: string = statePath()): ManagedState =
  if not fileExists(path):
    return ManagedState(profiles: initTable[ProfileName, LoadedProfile]())
  try:
    let content = readFile(path)
    let json = parseJson(content)
    # Deserialize — implementation depends on json schema
    # For now, return empty state
    ManagedState(profiles: initTable[ProfileName, LoadedProfile]())
  except CatchableError:
    ManagedState(profiles: initTable[ProfileName, LoadedProfile]())

proc saveManagedState*(state: ManagedState, path: string = statePath()) =
  createDir(path.parentDir)
  let json = %*{}  # Serialize state to JSON
  # Implementation: convert each LoadedProfile to JSON
  writeFile(path, json.pretty)

proc recordLoad*(state: var ManagedState, profile: ProfileName,
                 matched: Table[WindowRole, nimri_ipc.WindowId],
                 commands: Table[WindowRole, seq[string]]) =
  var windows = initTable[WindowRole, ManagedWindow]()
  for role, winId in matched:
    windows[role] = ManagedWindow(
      role: role,
      niriId: some(winId),
      pid: none(int),
      launchCommand: if role in commands: some(commands[role]) else: none(seq[string]),
      matchedAt: $now(),
    )
  state.profiles[profile] = LoadedProfile(
    name: profile,
    loadedAt: $now(),
    windows: windows,
  )

proc recordClose*(state: var ManagedState, profile: ProfileName) =
  state.profiles.del(profile)

proc pruneDeadWindows*(state: var ManagedState, liveWindowIds: HashSet[nimri_ipc.WindowId]) =
  ## Remove managed windows whose Niri IDs no longer exist.
  for profileName, profile in state.profiles.mpairs:
    var dead: seq[WindowRole] = @[]
    for role, mw in profile.windows:
      if mw.niriId.isSome and mw.niriId.get notin liveWindowIds:
        dead.add(role)
    for role in dead:
      profile.windows.del(role)
```

### Checkpoint

Write `tests/test_managed.nim`: round-trip save/load, prune dead windows, record/close lifecycle.

---

## Phase 9: CLI (`src/cli.nim` + `src/nirip.nim`)

### Step 9.1: Create `src/cli.nim`

```nim
import std/[os, options, tables, times]
import chronos
import chronicles
import results
import cligen
import nimri_ipc
import core/[types, config, matcher, planner, freezer, diagnostics]
import executor/runner
import state/managed

proc getConfigDir(): string =
  getEnv("XDG_CONFIG_HOME", getHomeDir() / ".config") / "nirip"

proc takeSnapshot(client: nimri_ipc.NiriClient): Future[NiriSnapshot] {.async.} =
  let windows = (await client.getWindows()).get(@[])
  let workspaces = (await client.getWorkspaces()).get(@[])
  let outputs = (await client.getOutputs()).get(initTable[string, nimri_ipc.Output]())
  let focused = (await client.getFocusedWindow()).get(none(nimri_ipc.Window))
  NiriSnapshot(
    windows: windows,
    workspaces: workspaces,
    outputs: outputs,
    focusedWindowId: if focused.isSome: some(focused.get.id) else: none(nimri_ipc.WindowId),
  )

proc load(profile: string, workspace = "", force = false, verbose = false, sidebard = false) =
  ## Reconcile desktop toward a profile.
  let configDir = getConfigDir()
  let globalRes = loadGlobalConfig(configDir)
  if globalRes.isErr:
    echo "Error: " & globalRes.error
    quit(1)
  let global = globalRes.get

  let profilePath = resolveProfilePath(configDir, profile)
  var globalOutputs = initTable[OutputAlias, seq[string]]()
  if global.outputs.isSome:
    for alias, names in global.outputs.get:
      globalOutputs[OutputAlias(alias)] = names

  let profileRes = loadProfile(profilePath, global.defaults, globalOutputs)
  if profileRes.isErr:
    echo "Error: " & profileRes.error
    quit(1)
  let prof = profileRes.get

  waitFor proc() {.async.} =
    let clientRes = await nimri_ipc.openClient()
    if clientRes.isErr:
      echo "Error: Failed to connect to Niri: " & $clientRes.error
      quit(1)
    let client = clientRes.get

    let eventsRes = await nimri_ipc.openEventStream()
    if eventsRes.isErr:
      echo "Error: Failed to open event stream: " & $eventsRes.error
      quit(1)
    let events = eventsRes.get

    var snapshot = await takeSnapshot(client)
    let managed = loadManagedState()

    let plan = plan(prof, snapshot, managed)
    if plan.operations.len == 0:
      echo "Already in sync — nothing to do."
      return

    if verbose or not force:
      echo formatPlan(plan, prof)
      if not force:
        echo "\nProceed? [Y/n] "
        let answer = readLine(stdin)
        if answer.toLowerAscii notin ["", "y", "yes"]:
          echo "Aborted."
          return

    let result = await execute(client, events, plan, snapshot)

    echo "\nCompleted: " & $result.completed.len
    echo "Skipped: " & $result.skipped.len
    echo "Failed: " & $result.failed.len
    echo "Timed out: " & $result.timedOut.len

    # Update managed state
    var commands = initTable[WindowRole, seq[string]]()
    for wsSpec in prof.workspaces:
      for colSpec in wsSpec.columns:
        for winSpec in colSpec.windows:
          if winSpec.command.isSome:
            commands[winSpec.id] = winSpec.command.get
    var state = managed
    state.recordLoad(prof.name, plan.matchedWindows, commands)
    state.saveManagedState()

    await client.close()
    await events.close()
  ()

proc planCmd(profile: string, json = false, workspace = "") =
  ## Show what load would do (dry-run).
  let configDir = getConfigDir()
  let globalRes = loadGlobalConfig(configDir)
  let global = if globalRes.isOk: globalRes.get else: GlobalConfig()

  let profilePath = resolveProfilePath(configDir, profile)
  var globalOutputs = initTable[OutputAlias, seq[string]]()
  if global.outputs.isSome:
    for alias, names in global.outputs.get:
      globalOutputs[OutputAlias(alias)] = names

  let profileRes = loadProfile(profilePath, global.defaults, globalOutputs)
  if profileRes.isErr:
    echo "Error: " & profileRes.error
    quit(1)
  let prof = profileRes.get

  waitFor proc() {.async.} =
    let clientRes = await nimri_ipc.openClient()
    if clientRes.isErr:
      echo "Error: " & $clientRes.error
      quit(1)
    let client = clientRes.get

    let snapshot = await takeSnapshot(client)
    let managed = loadManagedState()
    let plan = plan(prof, snapshot, managed)

    if json:
      echo plan.toJson  # needs jsony serialization
    else:
      echo formatPlan(plan, prof)

    await client.close()
  ()

proc freezeCmd(
  name = "frozen",
  workspace = "",
  all = false,
  dir = "",
  json = false,
) =
  ## Capture current state as a profile.
  waitFor proc() {.async.} =
    let clientRes = await nimri_ipc.openClient()
    if clientRes.isErr:
      echo "Error: " & $clientRes.error
      quit(1)
    let client = clientRes.get

    let snapshot = await takeSnapshot(client)
    let managed = loadManagedState()

    let options = FreezeOptions(
      includeAll: all,
      workspaceFilter: if workspace.len > 0: some(workspace) else: none(string),
      annotateCommands: true,
      outputFormat: if dir.len > 0: ffDirectory else: ffSingleFile,
      profileName: name,
    )

    let profile = freeze(snapshot, options, some(managed))
    let toml = profileToToml(profile)

    if dir.len > 0:
      # Write to directory
      createDir(dir)
      writeFile(dir / "profile.toml", toml)
      echo "Frozen to " & dir
    else:
      echo toml

    await client.close()
  ()

proc diff(profile: string) =
  ## Compare profile against current state.
  let configDir = getConfigDir()
  let globalRes = loadGlobalConfig(configDir)
  let global = if globalRes.isOk: globalRes.get else: GlobalConfig()

  let profilePath = resolveProfilePath(configDir, profile)
  var globalOutputs = initTable[OutputAlias, seq[string]]()
  if global.outputs.isSome:
    for alias, names in global.outputs.get:
      globalOutputs[OutputAlias(alias)] = names

  let profileRes = loadProfile(profilePath, global.defaults, globalOutputs)
  if profileRes.isErr:
    echo "Error: " & profileRes.error
    quit(1)
  let prof = profileRes.get

  waitFor proc() {.async.} =
    let clientRes = await nimri_ipc.openClient()
    if clientRes.isErr:
      echo "Error: " & $clientRes.error
      quit(1)
    let client = clientRes.get

    let snapshot = await takeSnapshot(client)
    let managed = loadManagedState()
    let plan = plan(prof, snapshot, managed)

    echo formatDiff(prof, snapshot, plan.matchedWindows)
    await client.close()
  ()

proc doctor(profile: string) =
  ## Validate profile and check environment.
  let configDir = getConfigDir()
  let globalRes = loadGlobalConfig(configDir)
  let global = if globalRes.isOk: globalRes.get else: GlobalConfig()

  let profilePath = resolveProfilePath(configDir, profile)
  var globalOutputs = initTable[OutputAlias, seq[string]]()
  if global.outputs.isSome:
    for alias, names in global.outputs.get:
      globalOutputs[OutputAlias(alias)] = names

  let profileRes = loadProfile(profilePath, global.defaults, globalOutputs)
  if profileRes.isErr:
    echo "Error: " & profileRes.error
    quit(1)
  let prof = profileRes.get

  waitFor proc() {.async.} =
    let clientRes = await nimri_ipc.openClient()
    if clientRes.isErr:
      echo "Error: " & $clientRes.error
      quit(1)
    let client = clientRes.get

    let snapshot = await takeSnapshot(client)
    echo formatDoctor(prof, snapshot)
    await client.close()
  ()

proc list() =
  ## List known profiles.
  let configDir = getConfigDir()
  for name in listProfiles(configDir):
    echo name

proc close(profile: string, force = false) =
  ## Close all windows managed by a profile.
  var managed = loadManagedState()
  let profileName = ProfileName(profile)
  if profileName notin managed.profiles:
    echo "Profile \"" & profile & "\" is not loaded."
    quit(1)

  let loaded = managed.profiles[profileName]
  if not force:
    echo "Will close " & $loaded.windows.len & " windows from \"" & profile & "\""
    echo "Proceed? [y/N] "
    let answer = readLine(stdin)
    if answer.toLowerAscii notin ["y", "yes"]:
      echo "Aborted."
      return

  waitFor proc() {.async.} =
    let clientRes = await nimri_ipc.openClient()
    if clientRes.isErr:
      echo "Error: " & $clientRes.error
      quit(1)
    let client = clientRes.get

    for role, mw in loaded.windows:
      if mw.niriId.isSome:
        let action = nimri_ipc.closeWindow(some(mw.niriId.get))
        let res = await client.doAction(action)
        if res.isOk:
          echo "Closed " & $role & " (window " & $mw.niriId.get & ")"
        else:
          echo "Failed to close " & $role & ": " & $res.error

    managed.recordClose(profileName)
    managed.saveManagedState()
    await client.close()
  ()

proc status() =
  ## Show loaded profiles and managed windows.
  let managed = loadManagedState()
  if managed.profiles.len == 0:
    echo "No profiles loaded."
    return

  for name, profile in managed.profiles:
    echo $name & " (loaded " & profile.loadedAt & ")"
    for role, mw in profile.windows:
      let idStr = if mw.niriId.isSome: $mw.niriId.get else: "?"
      echo "  " & $role & ": window " & idStr
```

### Step 9.2: Entry point (`src/nirip.nim`)

```nim
import cligen
import cli

when isMainModule:
  dispatchMulti(
    [load, help = {"profile": "Profile name or path"}],
    [planCmd, cmdName = "plan", help = {"profile": "Profile name or path"}],
    [freezeCmd, cmdName = "freeze"],
    [diff, help = {"profile": "Profile name or path"}],
    [doctor, help = {"profile": "Profile name or path"}],
    [list],
    [close, help = {"profile": "Profile name to close"}],
    [status],
  )
```

### Checkpoint

End-to-end test:

```bash
# Create a test profile
mkdir -p ~/.config/nirip/profiles/test
cat > ~/.config/nirip/profiles/test/profile.toml << 'EOF'
name = "test"
description = "Test profile"

[options]
match_existing = true
launch_missing = false
EOF

cat > ~/.config/nirip/profiles/test/main.toml << 'EOF'
[workspace]
name = "test:main"

[[columns]]
width = 1.0

[[columns.windows]]
id = "terminal"

[columns.windows.match]
app_id = "foot"
EOF

# Test commands
nirip list               # should show "test"
nirip doctor test        # should validate
nirip plan test          # should show plan
nirip freeze > /tmp/frozen.toml  # should produce valid TOML
nirip status             # should show nothing loaded
nirip load test          # should execute plan
nirip status             # should show loaded profile
nirip diff test          # should show current state
nirip close test         # should close managed windows
```

---

## Phase 10: Sidebard integration (`integrations/sidebard_rpc.nim`)

Optional module — query sidebard for sidebar ownership to exclude sidebar-owned windows from matching.

### Step 10.1: Create `src/integrations/sidebard_rpc.nim`

```nim
import std/[json, options, sets]
import chronos
import results
import nimri_ipc

type
  SidebardClient* = ref object
    socketPath: string

proc connect*(socketPath: string): Future[Result[SidebardClient, string]] {.async.} =
  # Verify socket exists
  if not fileExists(socketPath):
    return err("sidebard socket not found: " & socketPath)
  ok(SidebardClient(socketPath: socketPath))

proc getOwnedWindowIds*(client: SidebardClient): Future[Result[HashSet[nimri_ipc.WindowId], string]] {.async.} =
  ## Query sidebard for all sidebar-owned window IDs.
  ## These should be excluded from nirip's window matching.
  try:
    # Connect, send JSON-RPC "windows" request, parse response
    # Extract window IDs from sidebar instances
    let socket = newAsyncSocket(AF_UNIX, SOCK_STREAM, IPPROTO_IP)
    await socket.connectUnix(client.socketPath)

    let request = %*{
      "jsonrpc": "2.0",
      "id": 1,
      "method": "instances",
    }
    await socket.send($request & "\n")
    let response = await socket.recvLine()
    socket.close()

    let json = parseJson(response)
    if json.hasKey("error"):
      return err(json["error"]["message"].getStr)

    var owned = initHashSet[nimri_ipc.WindowId]()
    for instance in json["result"]:
      for wid in instance["windowIds"]:
        owned.incl(nimri_ipc.WindowId(wid.getInt.uint64))

    ok(owned)
  except CatchableError as e:
    err("sidebard query failed: " & e.msg)
```

Then in the planner, filter out sidebar-owned windows before matching:

```nim
# In cli.nim load command, after taking snapshot:
if sidebard:
  let sidebardRes = await sidebardClient.getOwnedWindowIds()
  if sidebardRes.isOk:
    let ownedIds = sidebardRes.get
    snapshot.windows = snapshot.windows.filterIt(it.id notin ownedIds)
```

### Checkpoint

With sidebard running: `nirip load --sidebard` excludes sidebar-owned windows from matching.

---

## Testing strategy

### Unit tests (pure, no I/O)

| Module | What to test |
|---|---|
| `core/types.nim` | Distinct IDs, variant construction, enum completeness |
| `core/config.nim` | TOML parsing, match rule conversion, option merging, both profile formats |
| `core/matcher.nim` | Every MatchRuleKind, composition, ranking, explanation traces |
| `core/planner.nim` | Every OpKind generation, idempotency, edge cases |
| `core/freezer.nim` | Column grouping, window-to-spec, round-trip with config loader |
| `core/diagnostics.nim` | Format strings for plan, diff, doctor |
| `state/managed.nim` | Save/load round-trip, prune dead windows |

### Integration tests (require running Niri)

| Test | What to test |
|---|---|
| Snapshot | Connect, fetch windows/workspaces/outputs |
| Focus | `ensureFocus` changes focus and receives confirmation event |
| Spawn | `launchProcess` starts a process, window appears |
| Full load | `nirip load` with a real profile against a real desktop |

### Property tests

- **Planner idempotency:** `plan(profile, result_of_load) == empty plan`
- **Matcher determinism:** same rule + same window → same result
- **Freezer round-trip:** `freeze(snapshot) |> plan(_, snapshot) == empty plan`

---

## Common pitfalls

1. **`ref object` for MatchRule is mandatory.** Nim doesn't support recursive value types. If you try `object` instead of `ref object`, the compiler will reject it.

2. **TOML `[[array.of.tables]]` parsing.** The double-bracket syntax is how TOML represents arrays of tables. Make sure your config types use `seq[T]` for these, not `Table`.

3. **Window IDs are transient.** Niri window IDs change across sessions and may be reused. Never persist them as durable identifiers. The managed state file stores them as hints, but always re-validates against live state.

4. **Focus-sensitive operations are the hardest part.** Many Niri actions (set column width, consume into column) require the target to be focused. Always verify focus landed correctly before executing.

5. **Column formation order matters.** Consume operations must happen after windows are in the right workspace. Sizing must happen after columns are formed. The planner produces ops in the right order — don't reorder them.

6. **TOML snake_case vs Nim camelCase.** Configure `toml-serialization` to handle the mapping, or use `{.serialize: "snake_case".}` pragmas.

7. **The planner must be re-invokable.** During execution, state changes. The executor should re-plan periodically to handle drift. Don't assume the initial plan is still valid after several ops.

8. **Output alias resolution must be done at plan time**, not config load time, because available outputs can change between config load and plan execution.

9. **`posInScrollingLayout` may be `none`.** Floating windows and some edge cases don't have scroll layout positions. Handle this gracefully.

10. **Timeout for spawned windows.** Some apps (VS Code, Chrome) take seconds to start. The default 20s timeout should be configurable per-window.

---

## Definition of done

The nirip implementation is complete when:

1. `nirip list` shows available profiles
2. `nirip doctor <profile>` validates config, environment, and commands
3. `nirip plan <profile>` shows a correct, human-readable plan
4. `nirip load <profile>` reconciles the desktop toward the profile
5. `nirip load <profile>` a second time produces zero operations (idempotent)
6. `nirip freeze` captures current state as valid, re-loadable TOML
7. `nirip diff <profile>` shows meaningful differences
8. `nirip close <profile>` closes managed windows
9. `nirip status` shows loaded profiles
10. All unit tests pass
11. The planner is provably I/O-free (no async/net/os imports in `core/planner.nim`)
12. Match rules support composition (`All`, `Any`, `Not`) and produce explanation traces
13. Focus-sensitive operations verify focus before executing
