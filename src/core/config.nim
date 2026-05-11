import std/[os, options, tables, strutils, sequtils, algorithm]
import results
import toml_serialization
import types
from nimri_ipc/models import Output

type
  GlobalConfig* = object
    defaults*: Option[GlobalDefaults]
    outputs*: Option[Table[string, seq[string]]]
    sidebard*: Option[SidebardIntegrationConfig]

  GlobalDefaults* = object
    timeoutMs*: Option[int]
    matchExisting*: Option[bool]
    launchMissing*: Option[bool]

  SidebardIntegrationConfig* = object
    socket*: Option[string]
    queryOwnership*: Option[bool]

  ProfileMetaConfig* = object
    name*: string
    description*: Option[string]
    options*: Option[ProfileOptionsConfig]
    outputs*: Option[Table[string, seq[string]]]

  ProfileOptionsConfig* = object
    matchExisting*: Option[bool]
    launchMissing*: Option[bool]
    moveUnmanaged*: Option[bool]
    closeExtra*: Option[bool]
    timeoutMs*: Option[int]
    focusAfterLoad*: Option[string]

  WorkspaceConfig* = object
    workspace*: WorkspaceMetaConfig
    columns*: seq[ColumnConfig]

  WorkspaceMetaConfig* = object
    name*: string
    output*: Option[string]
    index*: Option[int]
    focus*: Option[string]

  ColumnConfig* = object
    id*: Option[string]
    width*: Option[float]
    widthPx*: Option[int]
    display*: Option[string]
    windows*: seq[WindowConfig]

  WindowConfig* = object
    id*: string
    command*: Option[seq[string]]
    cwd*: Option[string]
    env*: Option[Table[string, string]]
    match*: Option[MatchConfig]
    height*: Option[float]
    heightPx*: Option[int]
    floating*: Option[bool]

  MatchConfig* = ref object
    appId*: Option[string]
    appIdRegex*: Option[string]
    title*: Option[string]
    titleRegex*: Option[string]
    workspace*: Option[string]
    any*: Option[seq[MatchConfig]]
    not_rule*: Option[MatchConfig]

  SingleFileProfileConfig* = object
    name*: string
    description*: Option[string]
    options*: Option[ProfileOptionsConfig]
    outputs*: Option[Table[string, seq[string]]]
    workspaces*: seq[SingleFileWorkspaceConfig]

  SingleFileWorkspaceConfig* = object
    name*: string
    output*: Option[string]
    index*: Option[int]
    focus*: Option[string]
    columns*: seq[ColumnConfig]

proc toMatchRule*(cfg: MatchConfig): Result[MatchRule, string] =
  var rules: seq[MatchRule] = @[]
  if cfg.appId.isSome: rules.add(MatchRule(kind: mrExactAppId, appId: cfg.appId.get))
  if cfg.appIdRegex.isSome: rules.add(MatchRule(kind: mrRegexAppId, appIdPattern: cfg.appIdRegex.get))
  if cfg.title.isSome: rules.add(MatchRule(kind: mrExactTitle, title: cfg.title.get))
  if cfg.titleRegex.isSome: rules.add(MatchRule(kind: mrRegexTitle, titlePattern: cfg.titleRegex.get))
  if cfg.workspace.isSome: rules.add(MatchRule(kind: mrWorkspaceName, workspace: cfg.workspace.get))
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
  if rules.len == 0: return err("match rule has no criteria")
  if rules.len == 1: return ok(rules[0])
  ok(MatchRule(kind: mrAll, allRules: rules))

proc toSizeSpec*(ratio: Option[float], px: Option[int]): Option[SizeSpec] =
  if ratio.isSome: return some(SizeSpec(kind: skProportion, ratio: ratio.get))
  if px.isSome: return some(SizeSpec(kind: skPixels, px: px.get))
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
    if matchRes.isErr: return err("window " & cfg.id & ": " & matchRes.error)
    matchRule = matchRes.get
  else:
    if cfg.command.isNone:
      return err("window " & cfg.id & ": must have either match or command")
    matchRule = MatchRule(kind: mrPidFromSpawn)

  ok(WindowSpec(
    id: WindowRole(cfg.id),
    command: cfg.command,
    cwd: cfg.cwd,
    env: (if cfg.env.isSome: cfg.env.get else: initTable[string, string]()),
    match: matchRule,
    height: toSizeSpec(cfg.height, cfg.heightPx),
    floating: cfg.floating.get(false),
  ))

proc toColumnSpec*(cfg: ColumnConfig): Result[ColumnSpec, string] =
  var windows: seq[WindowSpec] = @[]
  for w in cfg.windows:
    let wr = toWindowSpec(w)
    if wr.isErr: return err(wr.error)
    windows.add(wr.get)
  ok(ColumnSpec(
    id: (if cfg.id.isSome: some(ColumnRole(cfg.id.get)) else: none(ColumnRole)),
    width: toSizeSpec(cfg.width, cfg.widthPx),
    display: toColumnDisplay(cfg.display),
    windows: windows,
  ))

proc toWorkspaceSpec*(cfg: WorkspaceMetaConfig, columns: seq[ColumnConfig]): Result[WorkspaceSpec, string] =
  var colSpecs: seq[ColumnSpec] = @[]
  for c in columns:
    let cr = toColumnSpec(c)
    if cr.isErr: return err(cr.error)
    colSpecs.add(cr.get)
  ok(WorkspaceSpec(
    name: WorkspaceName(cfg.name),
    output: cfg.output,
    index: cfg.index,
    focus: (if cfg.focus.isSome: some(WindowRole(cfg.focus.get)) else: none(WindowRole)),
    columns: colSpecs,
  ))

proc defaultOptions*(globalDefaults: Option[GlobalDefaults]): ProfileOptions =
  result = ProfileOptions(matchExisting: true, launchMissing: true, moveUnmanaged: false, closeExtra: false, timeoutMs: 20000, focusAfterLoad: none(string))
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
  if o.closeExtra.isSome: result.closeExtra = o.closeExtra.get
  if o.timeoutMs.isSome: result.timeoutMs = o.timeoutMs.get
  if o.focusAfterLoad.isSome: result.focusAfterLoad = o.focusAfterLoad

proc loadGlobalConfig*(configDir: string): Result[GlobalConfig, string] =
  let path = configDir / "config.toml"
  if not fileExists(path): return ok(GlobalConfig())
  try:
    ok(Toml.loadFile(path, GlobalConfig))
  except CatchableError as e:
    err("failed to parse " & path & ": " & e.msg)

proc loadDirectoryProfile*(dir: string, globalDefaults: Option[GlobalDefaults], globalOutputs: OutputAliases): Result[Profile, string] =
  let metaPath = dir / "profile.toml"
  if not fileExists(metaPath): return err("profile.toml not found in " & dir)
  let meta = try: Toml.loadFile(metaPath, ProfileMetaConfig)
             except CatchableError as e: return err("failed to parse " & metaPath & ": " & e.msg)
  var options = mergeOptions(defaultOptions(globalDefaults), meta.options)
  var outputs = globalOutputs
  if meta.outputs.isSome:
    for alias, names in meta.outputs.get:
      outputs[OutputAlias(alias)] = names
  var workspaces: seq[WorkspaceSpec] = @[]
  for kind, path in walkDir(dir):
    if kind == pcFile and path.endsWith(".toml") and extractFilename(path) != "profile.toml":
      let wsCfg = try: Toml.loadFile(path, WorkspaceConfig)
                  except CatchableError as e: return err("failed to parse " & path & ": " & e.msg)
      let wsRes = toWorkspaceSpec(wsCfg.workspace, wsCfg.columns)
      if wsRes.isErr: return err(extractFilename(path) & ": " & wsRes.error)
      workspaces.add(wsRes.get)
  workspaces.sort(proc(a, b: WorkspaceSpec): int = cmp(a.index.get(high(int)), b.index.get(high(int))))
  ok(Profile(name: ProfileName(meta.name), description: meta.description.get(""), options: options, outputs: outputs, workspaces: workspaces))

proc loadSingleFileProfile*(path: string, globalDefaults: Option[GlobalDefaults], globalOutputs: OutputAliases): Result[Profile, string] =
  let cfg = try: Toml.loadFile(path, SingleFileProfileConfig)
            except CatchableError as e: return err("failed to parse " & path & ": " & e.msg)
  var options = mergeOptions(defaultOptions(globalDefaults), cfg.options)
  var outputs = globalOutputs
  if cfg.outputs.isSome:
    for alias, names in cfg.outputs.get:
      outputs[OutputAlias(alias)] = names
  var workspaces: seq[WorkspaceSpec] = @[]
  for ws in cfg.workspaces:
    let meta = WorkspaceMetaConfig(name: ws.name, output: ws.output, index: ws.index, focus: ws.focus)
    let wres = toWorkspaceSpec(meta, ws.columns)
    if wres.isErr: return err(wres.error)
    workspaces.add(wres.get)
  ok(Profile(name: ProfileName(cfg.name), description: cfg.description.get(""), options: options, outputs: outputs, workspaces: workspaces))

proc loadProfile*(profilePath: string, globalDefaults: Option[GlobalDefaults], globalOutputs: OutputAliases): Result[Profile, string] =
  if dirExists(profilePath): return loadDirectoryProfile(profilePath, globalDefaults, globalOutputs)
  if fileExists(profilePath): return loadSingleFileProfile(profilePath, globalDefaults, globalOutputs)
  err("profile not found: " & profilePath)

proc resolveProfilePath*(configDir: string, name: string): string =
  let dirPath = configDir / "profiles" / name
  if dirExists(dirPath): return dirPath
  let filePath = configDir / "profiles" / (name & ".toml")
  if fileExists(filePath): return filePath
  dirPath

proc listProfiles*(configDir: string): seq[string] =
  let profilesDir = configDir / "profiles"
  if not dirExists(profilesDir): return @[]
  for kind, path in walkDir(profilesDir):
    let name = extractFilename(path)
    case kind
    of pcDir:
      if fileExists(path / "profile.toml"): result.add(name)
    of pcFile:
      if name.endsWith(".toml"): result.add(name.changeFileExt(""))
    else:
      discard

proc resolveOutput*(alias: string, aliases: OutputAliases, availableOutputs: Table[string, Output]): Option[string] =
  if alias in availableOutputs: return some(alias)
  let aliasId = OutputAlias(alias)
  if aliasId in aliases:
    for candidate in aliases[aliasId]:
      if candidate in availableOutputs:
        return some(candidate)
  none(string)
