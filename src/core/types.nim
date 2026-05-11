import std/[options, tables, times, hashes]
import results
import nimri_ipc

type
  ProfileName* = distinct string
  WorkspaceName* = distinct string
  WindowRole* = distinct string
  ColumnRole* = distinct string
  OutputAlias* = distinct string

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

type
  SizeKind* = enum
    skProportion
    skPixels

  SizeSpec* = object
    case kind*: SizeKind
    of skProportion:
      ratio*: float
    of skPixels:
      px*: int

  ColumnDisplay* = enum
    cdNormal
    cdTabbed

type
  ProfileOptions* = object
    matchExisting*: bool
    launchMissing*: bool
    moveUnmanaged*: bool
    closeExtra*: bool
    timeoutMs*: int
    focusAfterLoad*: Option[string]

  OutputAliases* = Table[OutputAlias, seq[string]]

  Profile* = object
    name*: ProfileName
    description*: string
    options*: ProfileOptions
    outputs*: OutputAliases
    workspaces*: seq[WorkspaceSpec]

  WorkspaceSpec* = object
    name*: WorkspaceName
    output*: Option[string]
    index*: Option[int]
    focus*: Option[WindowRole]
    columns*: seq[ColumnSpec]

  ColumnSpec* = object
    id*: Option[ColumnRole]
    width*: Option[SizeSpec]
    display*: ColumnDisplay
    windows*: seq[WindowSpec]

  WindowSpec* = object
    id*: WindowRole
    command*: Option[seq[string]]
    cwd*: Option[string]
    env*: Table[string, string]
    match*: MatchRule
    height*: Option[SizeSpec]
    floating*: bool

type
  MatchRuleKind* = enum
    mrExactAppId
    mrRegexAppId
    mrExactTitle
    mrRegexTitle
    mrWorkspaceName
    mrPidFromSpawn
    mrOpenedAfter
    mrAll
    mrAny
    mrNot

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
    explanation*: seq[string]

  MatchContext* = object
    spawnTimestamps*: Table[WindowRole, MonoTime]
    launchedPids*: Table[WindowRole, int]
    workspaceNames*: Table[nimri_ipc.WorkspaceId, string]

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
    of opMoveWindowToTiling:
      mttWindow*: nimri_ipc.WindowId
    of opMoveWindowToFloating:
      mtfWindow*: nimri_ipc.WindowId
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
    of opFocusWindow:
      fwWindow*: nimri_ipc.WindowId
    of opFocusWorkspace:
      fwsName*: WorkspaceName

type
  PlanResult* = object
    operations*: seq[Operation]
    matchedWindows*: Table[WindowRole, nimri_ipc.WindowId]
    unmatchedRoles*: seq[WindowRole]
    warnings*: seq[string]

  NiriSnapshot* = object
    windows*: seq[nimri_ipc.Window]
    workspaces*: seq[nimri_ipc.Workspace]
    outputs*: Table[string, nimri_ipc.Output]
    focusedWindowId*: Option[nimri_ipc.WindowId]

type
  OpOutcome* = enum
    ooCompleted
    ooSkipped
    ooFailed
    ooTimeout

  ExecutedOp* = object
    operation*: Operation
    outcome*: OpOutcome
    message*: string

  ExecuteResult* = object
    completed*: seq[ExecutedOp]
    failed*: seq[ExecutedOp]
    skipped*: seq[ExecutedOp]
    timedOut*: seq[ExecutedOp]
