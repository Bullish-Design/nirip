import std/[os, options, tables]
import cligen
import nimri_ipc
import results
import core/[types, config, planner, diagnostics, freezer]
import executor/runner
import state/managed

proc cmdListProfiles*(configDir = ".config/nirip"): int =
  for p in listProfiles(configDir):
    echo p
  0

proc cmdDiff*(profile: string, configDir = ".config/nirip"): int =
  let resolved = resolveProfilePath(configDir, profile)
  let loaded = loadProfile(resolved, none(GlobalDefaults), initTable[OutputAlias, seq[string]]())
  if loaded.isErr:
    stderr.writeLine loaded.error
    return 1
  let snapshot = NiriSnapshot(windows: @[], workspaces: @[], outputs: initTable[string, nimri_ipc.Output](), focusedWindowId: none(nimri_ipc.WindowId))
  let pr = plan(loaded.get, snapshot)
  echo formatDiff(loaded.get, pr)
  0

proc cmdFreeze*(name: string): int =
  let snapshot = NiriSnapshot(windows: @[], workspaces: @[], outputs: initTable[string, nimri_ipc.Output](), focusedWindowId: none(nimri_ipc.WindowId))
  discard freezeProfile(name, snapshot)
  0

proc main*() =
  dispatchMulti([("list-profiles", cmdListProfiles), ("diff", cmdDiff), ("freeze", cmdFreeze)])
