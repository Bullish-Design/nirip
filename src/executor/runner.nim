import std/[options, times]
import results
import chronos
import nimri_ipc/nimri_ipc as nimri_ipc
import ../core/[types, planner]
import focus
import launcher

proc runOperation*(client: NiriIpcClient, op: Operation): Future[ExecutedOp] {.async.} =
  discard ensureFocus(client, op)
  case op.kind
  of opSpawnWindow:
    let launched = launchWindow(op)
    if launched.isErr:
      return ExecutedOp(operation: op, outcome: ooFailed, message: launched.error)
    ExecutedOp(operation: op, outcome: ooCompleted, message: "spawned")
  else:
    ExecutedOp(operation: op, outcome: ooCompleted, message: "noop executor stub")

proc executePlan*(client: NiriIpcClient, plan: PlanResult): Future[ExecuteResult] {.async.} =
  var out = ExecuteResult(completed: @[], failed: @[], skipped: @[], timedOut: @[])
  for op in plan.operations:
    let res = await runOperation(client, op)
    case res.outcome
    of ooCompleted: out.completed.add(res)
    of ooFailed: out.failed.add(res)
    of ooSkipped: out.skipped.add(res)
    of ooTimeout: out.timedOut.add(res)
  out
