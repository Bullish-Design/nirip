import std/[options, httpclient, json]
import results

proc lookupWorkspaceOwner*(socket: string, workspaceName: string): Result[Option[string], string] =
  discard socket
  discard workspaceName
  ok(none(string))
