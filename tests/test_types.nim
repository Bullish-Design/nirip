import std/options
import unittest
import core/types
import nimri_ipc

suite "types":
  test "distinct IDs":
    let p = ProfileName("backend-dev")
    let w = WorkspaceName("code")
    let r = WindowRole("editor")
    check $p == "backend-dev"
    check $w == "code"
    check $r == "editor"

  test "SizeSpec variants":
    let proportion = SizeSpec(kind: skProportion, ratio: 0.62)
    let pixels = SizeSpec(kind: skPixels, px: 800)
    check proportion.ratio == 0.62
    check pixels.px == 800

  test "MatchRule recursive composition":
    let rule = MatchRule(kind: mrAll, allRules: @[
      MatchRule(kind: mrExactAppId, appId: "code"),
      MatchRule(kind: mrRegexTitle, titlePattern: "backend"),
    ])
    check rule.allRules.len == 2
    check rule.allRules[0].kind == mrExactAppId

  test "Operation with focus requirement":
    let op = Operation(
      focusReq: frWindow,
      focusTarget: some(nimri_ipc.WindowId(42)),
      kind: opSetColumnWidth,
      scwWindow: nimri_ipc.WindowId(42),
      scwSize: SizeSpec(kind: skProportion, ratio: 0.62),
    )
    check op.focusReq == frWindow
    check op.kind == opSetColumnWidth
