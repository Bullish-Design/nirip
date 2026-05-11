import std/options
import results
import nimri_ipc/nimri_ipc as nimri_ipc
import ../core/types

proc ensureFocus*(client: NiriIpcClient, op: Operation): Result[void, string] =
  discard client
  discard op
  ok()
