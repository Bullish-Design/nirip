import std/[options, tables]
import types
import matcher
import nimri_ipc/nimri_ipc as nimri_ipc

proc planWorkspaces*(profile: Profile, snapshot: NiriSnapshot): seq[Operation] =
  var existing: Table[string, bool]
  for ws in snapshot.workspaces: existing[ws.name] = true
  for ws in profile.workspaces:
    if $ws.name notin existing:
      result.add(Operation(focusReq: frNone, focusTarget: none(nimri_ipc.WindowId), kind: opEnsureWorkspace, wsName: ws.name, wsOutput: ws.output))

proc plan*(profile: Profile, snapshot: NiriSnapshot): PlanResult =
  var ops = planWorkspaces(profile, snapshot)
  var matched = initTable[WindowRole, nimri_ipc.WindowId]()
  var unmatched: seq[WindowRole] = @[]
  for ws in profile.workspaces:
    for col in ws.columns:
      for win in col.windows:
        var found = false
        for w in snapshot.windows:
          let ctx = MatchContext(spawnTimestamps: initTable[WindowRole, MonoTime](), launchedPids: initTable[WindowRole, int](), workspaceNames: initTable[nimri_ipc.WorkspaceId, string]())
          if evaluate(win.match, w, ctx).matched:
            matched[win.id] = w.id
            found = true
            break
        if not found:
          unmatched.add(win.id)
          if profile.options.launchMissing and win.command.isSome:
            ops.add(Operation(focusReq: frNone, focusTarget: none(nimri_ipc.WindowId), kind: opSpawnWindow, spawnRole: win.id, spawnCmd: win.command.get, spawnCwd: win.cwd, spawnEnv: win.env, spawnMatch: win.match, spawnTimeout: profile.options.timeoutMs))
  PlanResult(operations: ops, matchedWindows: matched, unmatchedRoles: unmatched, warnings: @[])
