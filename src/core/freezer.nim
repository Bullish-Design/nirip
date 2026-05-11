import std/[options, tables, sequtils]
import types
import nimri_ipc

proc freezeWorkspace*(ws: nimri_ipc.Workspace, windows: seq[nimri_ipc.Window]): WorkspaceSpec =
  var col = ColumnSpec(id: none(ColumnRole), width: none(SizeSpec), display: cdNormal, windows: @[])
  for w in windows:
    if w.workspaceId.isSome and w.workspaceId.get == ws.id:
      col.windows.add(WindowSpec(id: WindowRole("window-" & $w.id), command: none(seq[string]), cwd: none(string), env: initTable[string, string](), match: MatchRule(kind: mrExactAppId, appId: w.appId.get("")), height: none(SizeSpec), floating: false))
  WorkspaceSpec(name: WorkspaceName(ws.name), output: none(string), index: none(int), focus: none(WindowRole), columns: @[col])

proc freezeProfile*(name: string, snapshot: NiriSnapshot): Profile =
  var workspaces: seq[WorkspaceSpec] = @[]
  for ws in snapshot.workspaces:
    workspaces.add(freezeWorkspace(ws, snapshot.windows))
  Profile(name: ProfileName(name), description: "frozen profile", options: ProfileOptions(matchExisting: true, launchMissing: false, moveUnmanaged: false, closeExtra: false, timeoutMs: 20000, focusAfterLoad: none(string)), outputs: initTable[OutputAlias, seq[string]](), workspaces: workspaces)
