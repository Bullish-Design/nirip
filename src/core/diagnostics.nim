import std/[strformat, sequtils, tables]
import types

proc explainOperation*(op: Operation): string =
  case op.kind
  of opEnsureWorkspace: &"ensure workspace {$op.wsName}"
  of opSpawnWindow: &"spawn {$op.spawnRole}"
  of opMoveWindowToWorkspace: &"move window {$op.mtwWindow} to {$op.mtwWorkspace}"
  else: $op.kind

proc formatPlan*(plan: PlanResult): string =
  var lines: seq[string] = @[]
  for op in plan.operations:
    lines.add("- " & explainOperation(op))
  if lines.len == 0: return "No operations required"
  lines.join("\n")

proc formatDiff*(profile: Profile, plan: PlanResult): string =
  &"Profile {$profile.name}: {plan.operations.len} operations, {plan.unmatchedRoles.len} unmatched roles"
