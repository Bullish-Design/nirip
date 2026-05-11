import std/[json, os, tables, options]
import results
import ../core/types
import nimri_ipc/nimri_ipc as nimri_ipc

type ManagedState* = object
  activeProfile*: Option[ProfileName]
  managedWindows*: Table[WindowRole, nimri_ipc.WindowId]

proc loadManagedState*(path: string): Result[ManagedState, string] =
  if not fileExists(path):
    return ok(ManagedState(activeProfile: none(ProfileName), managedWindows: initTable[WindowRole, nimri_ipc.WindowId]()))
  try:
    discard parseFile(path)
    ok(ManagedState(activeProfile: none(ProfileName), managedWindows: initTable[WindowRole, nimri_ipc.WindowId]()))
  except CatchableError as e:
    err(e.msg)

proc saveManagedState*(path: string, state: ManagedState): Result[void, string] =
  discard state
  try:
    writeFile(path, "{}")
    ok()
  except CatchableError as e:
    err(e.msg)
