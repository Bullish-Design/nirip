import std/[unittest, options, tables]
import core/[config, types]

suite "config":
  test "load directory profile":
    let p = loadDirectoryProfile("tests/fixtures/profiles/backend-dev", none(GlobalDefaults), initTable[OutputAlias, seq[string]]())
    check p.isOk
    check p.get.workspaces.len == 1
    check p.get.workspaces[0].columns.len == 2

  test "load single file profile":
    let p = loadSingleFileProfile("tests/fixtures/profiles/personal.toml", none(GlobalDefaults), initTable[OutputAlias, seq[string]]())
    check p.isOk
    check p.get.workspaces.len == 1

  test "match any composition":
    let m = MatchConfig(any: some(@[MatchConfig(appId: some("a")), MatchConfig(title: some("b"))]))
    let r = toMatchRule(m)
    check r.isOk
    check r.get.kind == mrAny

  test "missing profile.toml":
    let p = loadDirectoryProfile("tests/fixtures/profiles", none(GlobalDefaults), initTable[OutputAlias, seq[string]]())
    check p.isErr
