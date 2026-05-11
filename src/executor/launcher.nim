import std/[osproc, options, tables]
import results
import ../core/types

type SpawnedProcess* = object
  role*: WindowRole
  pid*: int

proc launchWindow*(op: Operation): Result[SpawnedProcess, string] =
  if op.kind != opSpawnWindow:
    return err("operation is not opSpawnWindow")
  let p = startProcess(op.spawnCmd[0], args = op.spawnCmd[1..^1], workingDir = op.spawnCwd.get(""), env = op.spawnEnv)
  ok(SpawnedProcess(role: op.spawnRole, pid: p.processID))
