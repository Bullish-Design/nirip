import std/[options, tables, re]
import types
import nimri_ipc

proc evaluate*(rule: MatchRule, window: nimri_ipc.Window, context: MatchContext): MatchResult =
  case rule.kind
  of mrExactAppId:
    let okm = window.appId.isSome and window.appId.get == rule.appId
    MatchResult(matched: okm, explanation: @[if okm: "exact app_id matched" else: "exact app_id did not match"])
  of mrRegexAppId:
    let okm = window.appId.isSome and window.appId.get.match(re(rule.appIdPattern))
    MatchResult(matched: okm, explanation: @[if okm: "regex app_id matched" else: "regex app_id did not match"])
  of mrExactTitle:
    let okm = window.title.isSome and window.title.get == rule.title
    MatchResult(matched: okm, explanation: @[if okm: "exact title matched" else: "exact title did not match"])
  of mrRegexTitle:
    let okm = window.title.isSome and window.title.get.match(re(rule.titlePattern))
    MatchResult(matched: okm, explanation: @[if okm: "regex title matched" else: "regex title did not match"])
  of mrWorkspaceName:
    if window.workspaceId.isSome and window.workspaceId.get in context.workspaceNames:
      let okm = context.workspaceNames[window.workspaceId.get] == rule.workspace
      MatchResult(matched: okm, explanation: @[if okm: "workspace matched" else: "workspace mismatch"])
    else:
      MatchResult(matched: false, explanation: @["workspace unavailable"])
  of mrPidFromSpawn, mrOpenedAfter:
    MatchResult(matched: false, explanation: @["contextual matcher, executor-owned"])
  of mrAll:
    var ex: seq[string] = @[]
    for sub in rule.allRules:
      let r = evaluate(sub, window, context)
      ex.add(r.explanation)
      if not r.matched: return MatchResult(matched: false, explanation: ex)
    MatchResult(matched: true, explanation: ex)
  of mrAny:
    var ex: seq[string] = @[]
    for sub in rule.anyRules:
      let r = evaluate(sub, window, context)
      ex.add(r.explanation)
      if r.matched: return MatchResult(matched: true, explanation: ex)
    MatchResult(matched: false, explanation: ex)
  of mrNot:
    let r = evaluate(rule.negated, window, context)
    MatchResult(matched: not r.matched, explanation: r.explanation)

proc rankCandidates*(rule: MatchRule, windows: seq[nimri_ipc.Window], context: MatchContext): seq[(nimri_ipc.Window, MatchResult)] =
  for w in windows:
    let r = evaluate(rule, w, context)
    if r.matched:
      result.add((w, r))
