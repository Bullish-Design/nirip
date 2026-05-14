# nirip Code Review Report

**Date:** 2026-05-14
**Scope:** Full codebase review — src/nirip/ (34 files, ~946 statements) + tests/ (8 test files, 20 tests)
**Test results:** 20/20 pass, 67% line coverage, ruff clean

---

## 1. Architecture Assessment

### 1.1 Module Boundary Compliance

The actual layout (`spec/`, `resolve/`, `planning/`, `execution/`, `capture/`, `facade/`, `cli/`) **diverges from AGENTS.md** which documents a `core/` + `executor/` flat layout. The implemented structure is arguably *better* — more granular separation of concerns — but the AGENTS.md is stale and should be updated to match reality.

**Verdict:** The real architecture is sound. The dependency flow is clean:
```
spec → resolve → planning → execution
                                ↓
capture ← facade → cli
```

All pure modules (spec, resolve, planning) are side-effect free. Execution/facade/cli correctly own I/O. **This is good.**

### 1.2 Core/Executor Boundary Discipline

- `spec/`, `resolve/`, `planning/` — zero I/O, zero imports of asyncio/subprocess/socket. ✅
- `execution/` — owns async execution, time measurement. ✅
- `capture/` — uses `getattr` duck-typing on snapshot objects. No I/O. ✅
- `facade/` — orchestrates pipeline, owns `asyncio.run`. ✅
- `cli/` — owns argparse, file I/O, stdout. ✅

**No forbidden couplings detected.**

---

## 2. Bugs and Correctness Issues

### 2.1 CRITICAL: `apply_defaults` uses sentinel comparison for timeout override

**File:** `src/nirip/spec/defaults.py:15`
```python
if app.startup_timeout_s == 20.0 and default_timeout != 20.0:
```

This compares against the magic number `20.0` rather than detecting "user didn't set this." If a user explicitly sets `startup_timeout_s: 20.0` in their YAML and the global default is different, the user's explicit value will be *overwritten* by the global default. This is incorrect — explicit values should always win.

**Fix:** Use a sentinel value (e.g., `None` as default in `AppSpec.startup_timeout_s`) or track whether the field was explicitly set.

### 2.2 HIGH: `predicate_for_step` is a stub that doesn't verify anything useful

**File:** `src/nirip/execution/predicates.py:14-19`
```python
def predicate_for_step(step: PlanStep):
    if step.kind == StepKind.WAIT_FOR_WINDOW:
        return lambda snapshot: bool(snapshot.windows)
    return lambda _snapshot: True
```

The WAIT_FOR_WINDOW predicate just checks `bool(snapshot.windows)` — whether *any* windows exist, not whether the *specific* window appeared. This means:
- In a non-empty desktop, WAIT_FOR_WINDOW will *always* be satisfied immediately
- The executor will skip the step as "already satisfied" before the spawn even happens

This effectively makes the executor fire-and-forget rather than event-confirmed, violating a core design principle.

### 2.3 HIGH: Executor skips steps that are already "satisfied" before action execution

**File:** `src/nirip/execution/executor.py:31-41`

The executor checks the predicate *before* executing the action. For spawn+wait pairs, the wait step will likely be satisfied by pre-existing windows. The predicate check should occur *after* the associated spawn, not before.

### 2.4 MEDIUM: `SyncNirip` creates a new `AsyncNirip` per method call

**File:** `src/nirip/facade/sync_nirip.py:29-58`

Each `diff()`, `plan()`, `apply()`, `capture()` creates a brand new `AsyncNirip` instance inside a fresh `asyncio.run()`. This means:
- No state sharing between calls (the snapshot must be re-bound each time internally)
- When actual niri-state integration exists, each call would open a new connection
- `asyncio.run()` will fail if called from an existing event loop

### 2.5 MEDIUM: `__init__.py` public API uses `object` return types

**File:** `src/nirip/__init__.py:9-17`
```python
def load_session(path: str) -> object:
def apply_session(spec: object) -> object:
```

These should use the proper types (`SessionSpec`, `ApplyResult`). Using `object` erases type safety for consumers.

### 2.6 MEDIUM: `capture_from_snapshot` uses `getattr` duck-typing instead of the Protocol

**File:** `src/nirip/capture/capturer.py:30-31`
```python
workspaces = getattr(snapshot, "workspaces", {})
windows = getattr(snapshot, "windows", {})
```

The `resolver.py` already defines `SnapshotLike` Protocol. The capturer should use the same protocol rather than opaque `object` + getattr.

### 2.7 LOW: `topological_sort` silently returns unsorted input on cycle

**File:** `src/nirip/planning/ordering.py:34-35`
```python
if len(ordered) != len(steps):
    return steps
```

If there's a dependency cycle among plan steps, this silently falls back to the original order with no warning. This could cause steps to execute in wrong order without any indication.

### 2.8 LOW: `NiripConfig.session_dir` doesn't expand `~`

**File:** `src/nirip/config.py:10`
```python
session_dir: Path = Path("~/.config/nirip/sessions")
```

`Path("~/.config/...")` doesn't expand the tilde. Any code using `config.session_dir` directly will look for a literal `~` directory. Need `Path.home() / ".config/nirip/sessions"` or call `.expanduser()` at usage sites.

---

## 3. Design Issues

### 3.1 No actual niri-ipc integration

The executor has an `ActionClient` protocol but no implementation that actually calls niri. The facade `open()` classmethod is a no-op. Currently the entire execution pipeline is a dry-run skeleton. This is acceptable for an initial implementation but should be called out — the library cannot actually orchestrate anything yet.

### 3.2 Missing `stop_on_error` enforcement

`SessionOptions.stop_on_error` exists in the spec model but is never consulted by the executor. When a step fails, execution continues regardless. The option is dead code.

### 3.3 Missing `mode` enforcement

`SessionOptions.mode` (defaulting to `"reconcile"`) is never used anywhere. There's no validation of allowed values and no branching logic.

### 3.4 Missing `match_existing` / `launch_missing` / `move_unmatched` enforcement

All three `SessionOptions` flags are defined but never referenced by the resolver or compiler. They're dead configuration.

### 3.5 Missing fullscreen/maximized drift detection

The resolver only checks `WRONG_WORKSPACE` and `WRONG_FLOATING` drift. `WRONG_FULLSCREEN` and `WRONG_MAXIMIZED` are defined as `DriftKind` variants but never emitted. The `PlacementSpec` allows setting these but they're never enforced.

### 3.6 Untyped `action_for_step` return

**File:** `src/nirip/execution/actions.py:9`

Returns `dict[str, Any] | None` — an untyped bag. This should be a proper model/dataclass per the "typed contracts" design principle.

---

## 4. Test Suite Assessment

### 4.1 Coverage Gaps (67% overall)

| Module | Coverage | Notes |
|--------|----------|-------|
| `cli/` | 0% | No CLI tests at all |
| `execution/executor.py` | 37% | Only tests via integration path, no direct executor tests |
| `execution/runtime.py` | 0% | Completely untested |
| `capture/` | 24-44% | No capture tests |
| `facade/` | 43-49% | No direct facade tests |
| `__main__.py` | 0% | No entrypoint test |

### 4.2 Missing Test Categories

**No negative/edge case tests for:**
- Matcher: regex match, title match, pid match, any_of, not_rule, ambiguous matches, no-match scenarios
- Resolver: missing workspace, drifted windows, floating drift, optional missing apps
- Compiler: workspace creation steps, move steps, floating adjustment steps, ambiguous skipping
- Executor: failed steps, skipped steps, stop-on-error behavior
- Capture: empty snapshot, windows without workspace, name inference
- CLI: argument parsing, command dispatch, error handling

**No integration test that exercises the full pipeline** (load YAML → normalize → resolve → plan → execute → verify result).

### 4.3 Test Quality Issues

- `test_config.py:14` — uses `pytest.raises(Exception)` with bare `Exception` and `# noqa: B017`. Should use `ValidationError` specifically.
- `test_matcher_resolver_planning.py` — only tests the happy path with a matched window. Doesn't test missing windows, spawn planning, or drift detection.
- Test fixtures (`Win`, `Ws`, `Snap` dataclasses) are defined inline in one test file. Should be shared fixtures in `conftest.py`.
- `conftest.py` is empty — missed opportunity for shared fixtures.

### 4.4 Missing Fixture Coverage

The `tests/fixtures/dev-day.yaml` file exists but is never loaded in any test. No test exercises `load_spec_from_file`.

---

## 5. Code Quality Notes

### 5.1 Good Patterns
- Pydantic models with `computed_field` for derived properties — clean and cacheable
- `StrEnum` for all enums — good for serialization
- `ValidationResult` dataclass for accumulating errors/warnings — composable
- DFS cycle detection in validator — correct algorithm
- Protocol-based structural typing for `WindowLike` — good decoupling

### 5.2 Minor Issues
- `spec/__init__.py`, `resolve/__init__.py`, `planning/__init__.py`, `capture/__init__.py`, `execution/__init__.py`, `facade/__init__.py` — five of these have identical `"""Module docstring."""` placeholders. Should have meaningful docstrings or be empty.
- `MatchRule.any_of` uses `alias="any"` for YAML but `populate_by_name=True` means both work. This is fine but should be documented since `any` is a Python builtin and `builtins.any` is needed in the validator (which the code does correctly handle).

---

## 6. Prioritized Recommendations

### Must Fix (before any real usage)
1. **Fix `apply_defaults` sentinel comparison** — use `None` default + explicit-set tracking
2. **Fix `predicate_for_step`** — must check for the *specific* spawned window, not any window
3. **Fix executor step-skip logic** — predicates must not skip steps that haven't had their dependencies executed yet
4. **Update AGENTS.md** — module table is completely wrong vs actual layout
5. **Fix `NiripConfig` tilde expansion** — `Path("~/.config/...")` won't work

### Should Fix (code quality)
6. **Type the public API** — `load_session` and `apply_session` should return proper types
7. **Use SnapshotLike protocol in capturer** — instead of `getattr` duck-typing
8. **Type `action_for_step`** — use a proper model instead of `dict[str, Any]`
9. **Wire `stop_on_error`** — or remove the dead option
10. **Add fullscreen/maximized drift detection** — or remove the dead DriftKind variants

### Should Add (test coverage)
11. **Executor unit tests** — test failed steps, skipped steps, client errors
12. **Matcher edge case tests** — regex, any_of, not_rule, ambiguous, no-match
13. **Resolver drift tests** — workspace mismatch, floating drift, optional missing
14. **CLI tests** — argument parsing, each subcommand
15. **Capture tests** — empty snapshot, inference edge cases
16. **Full integration test** — YAML → apply result with mock snapshot

---

## 7. Summary

The architecture is well-structured with clean separation between pure planning and effectful execution. The spec/resolve/planning pipeline is logically sound. However, the execution layer is largely a skeleton — predicates don't verify specific outcomes, options are defined but not enforced, and there's no actual niri-ipc client.

The test suite covers the happy path for spec loading and validation but has significant gaps in matcher edge cases, resolver drift detection, executor behavior, and CLI coverage. The `apply_defaults` sentinel bug is the most immediately impactful correctness issue.

Overall this is a solid foundation that needs the execution layer fleshed out and test coverage expanded before it can be relied upon.
