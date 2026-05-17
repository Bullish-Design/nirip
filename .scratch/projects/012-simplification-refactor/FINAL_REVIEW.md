# Final Code Review: nirip

**Reviewer**: Claude Opus 4.6
**Date**: 2026-05-17
**Commit**: `b31b18f` (post-simplification refactor)
**Scope**: Full library — 2,250 source lines across 33 files, 721 test lines across 20 files

---

## Executive Summary

nirip is a well-architected, tightly-scoped library. The simplification refactor successfully reduced conceptual overhead: the pipeline is now `spec → resolve → plan → execute` with no intermediate normalization layer, match quality uses discrete tiers instead of opaque floats, and policy decisions are cleanly separated from observation. The codebase reads like it was written by someone who has strong opinions about boundary discipline — and enforces them.

**Verdict**: Ship-ready for 0.2.0. The issues below are real but none are blocking. The architecture is sound, the code is clean, and the test suite covers the critical paths.

---

## Strengths

### 1. Exemplary Boundary Discipline
The `spec/`, `resolve/`, `planning/`, and `capture/` modules are genuinely pure — no asyncio, no I/O, no subprocess. This is rare in Python projects and pays massive dividends for testability. The dependency flow (`spec → resolve → planning → execution`) is unidirectional with no back-edges.

### 2. Frozen Pydantic Models as the Default
`NiripModel` (frozen, extra="forbid") eliminates entire categories of bugs. Immutable data structures flowing through a pipeline make the system trivially debuggable — you can snapshot any intermediate state without worrying about mutation.

### 3. Computed Fields Over Stored Redundancy
The refactor to `@computed_field` for `unmatched_apps`, `ambiguous_apps`, `has_drift`, etc. eliminates the dual-bookkeeping problem. There's now one source of truth (the `workspace_resolutions` list), and derived views are always consistent.

### 4. Clear Policy Separation
`_should_act()` in the compiler is exactly the right place for "should we spawn this?" decisions. The resolver no longer embeds policy, making it a pure observation layer. This means you can swap launch policies without touching resolution logic.

### 5. MatchTier Enum
Replacing float confidence with `IntEnum` is a genuine improvement. It makes the assignment algorithm's tie-breaking deterministic and comprehensible. The greedy assignment sorting by tier is correct and readable.

### 6. Table-Driven Handlers
The `_STATE_ACTIONS` and `_STATE_CHECKS` dictionaries in `handlers.py` replace what would otherwise be four near-identical case branches. Good DRY application without premature abstraction.

---

## Issues

### Critical (0)

None.

### High Severity (3)

#### H1: `_should_act()` Has No Exhaustive Return (**FIXED**)

**File**: `src/nirip/planning/compiler.py:32-44`

```python
def _should_act(ar: AppResolution, options: SessionOptions) -> bool:
    match ar.status:
        case ResolutionStatus.MATCHED:
            return False
        case ResolutionStatus.OPTIONAL_MISSING:
            return False
        case ResolutionStatus.MISSING:
            return options.launch_missing
        case ResolutionStatus.DRIFTED:
            return True
        case ResolutionStatus.AMBIGUOUS:
            return False
```

If `ResolutionStatus` gains a new variant, this function silently returns `None` (falsy, but not `False`). The type checker won't catch it because Python's `match` doesn't have exhaustiveness checking for StrEnum. Add a trailing `case _: return False` or, better, a `case _: raise ValueError(f"unhandled status: {ar.status}")` to fail loudly during development.

**Impact**: Silent incorrect behavior if enum extended.

#### H2: Greedy Assignment Is Not Optimal

**File**: `src/nirip/resolve/matcher.py:98-113`

The window assignment algorithm is a greedy approach: sort all (app, window, tier) triples by tier descending, then assign first-come-first-served. This is **not** guaranteed to produce an optimal 1:1 assignment. Consider:

- App A matches Window 1 (EXACT) and Window 2 (STRONG)
- App B matches Window 1 (EXACT) only

Greedy assigns Window 1 to whichever of A or B appears first in the sorted list (both are EXACT for Window 1). If A gets it, B is unmatched — even though the optimal assignment is A→2, B→1.

For a small number of apps/windows this rarely manifests, but it's a correctness issue in principle. The correct solution is a maximum weight bipartite matching (Hungarian algorithm), or at minimum, a greedy that prioritizes apps with fewer candidates.

**Impact**: Rare in practice (most users have distinct matchers), but could cause confusing "window not found" errors in dense multi-window setups.

#### H3: `apply_session()` Ignores `config` Parameter

**File**: `src/nirip/__init__.py:38-43`

```python
def apply_session(spec: SessionSpec) -> ApplyResult:
    async def _run() -> ApplyResult:
        async with await AsyncNirip.open() as nirip:
            return await nirip.apply(spec)
    return asyncio.run(_run())
```

Unlike `plan_session()` and `diff_session()`, `apply_session()` doesn't accept a `config` parameter and always uses the default config. This is an API inconsistency — the sync convenience functions should have uniform signatures.

**Impact**: Users who need custom timeouts or directories can't use `apply_session()`.

---

### Medium Severity (7)

#### M1: Duplicate `_STATE_CHECKS` Definition

**Files**: `src/nirip/execution/handlers.py:50-55` and `src/nirip/execution/predicates.py:15-20`

The same lambda dictionary is defined independently in both modules. If one is updated and the other isn't, behavior will silently diverge. Extract to a shared constant in `execution/models.py` or a dedicated `execution/_checks.py`.

#### M2: `use_enum_values=True` in NiripModel

**File**: `src/nirip/_base.py:17`

This Pydantic config option means that after instantiation, enum fields store their `.value` (the string) rather than the enum instance. This is why `matcher.py:101` and `matcher.py:123` need explicit `MatchTier(c.tier)` reconstruction casts. It also means `MatchDecision.is_ambiguous` needs `MatchTier(c.tier)` on line 42 of `resolve/models.py`.

This is a footgun: every time you access a tier from a model, you must remember to re-wrap it. Consider removing `use_enum_values=True` from the base config and handling serialization separately (via `model_serializer` or custom JSON encoders). Or at minimum, document this requirement prominently.

#### M3: Missing Timeout on Spawned Process Lifecycle

**File**: `src/nirip/execution/handlers.py:92-102`

`SpawnWindowStep` uses `asyncio.create_subprocess_exec()` but never awaits the process or tracks its lifecycle. If the spawned process crashes immediately, the subsequent `WaitForWindowStep` will time out after `timeout_s` seconds with no indication that the process already exited. Consider:
1. Storing the `Process` object in runtime state
2. In the `WaitForWindowStep` handler, racing `process.wait()` against the window appearance predicate
3. Failing fast with "process exited with code X" if the race is lost

#### M4: `_detect_drift()` Has Inconsistent Fullscreen/Maximized Handling

**File**: `src/nirip/resolve/resolver.py:91-129`

`_PROPERTY_CHECKS` handles floating and fullscreen via a loop, but maximized is handled separately with a `hasattr` check (line 121). This asymmetry suggests that at one point `is_maximized` wasn't guaranteed on the Window type. If that's still true, `is_fullscreen` has the same risk (no `hasattr` guard). If it's no longer true, the `hasattr` guard is dead logic. Either way, unify the approach.

#### M5: `compile_plan()` Emits Redundant State Steps for Newly-Spawned Windows

**File**: `src/nirip/planning/compiler.py:130-173`

When a window is `MISSING` (will be spawned), the compiler unconditionally emits `SetWindowStateStep` for floating/tiling, fullscreen, and maximized — even when the defaults match (e.g., tiling=True, fullscreen=False, maximized=False). For a newly-spawned window that opens in tiling mode, we emit a "set tiling" step that's a no-op.

The `is_already_satisfied` predicate in `predicates.py` will skip it at runtime, but this adds noise to plan output and makes `nirip plan` output harder to read. Consider only emitting state steps for non-default placements.

#### M6: `_parse_size()` Is Exported via Test Import

**File**: `tests/test_compiler.py:7`

```python
from nirip.planning.compiler import _parse_size, compile_plan
```

Tests import a private function directly. This couples tests to implementation details and prevents refactoring `_parse_size()` into a utility module. Consider either making it public (`parse_size()`) or testing it indirectly through `compile_plan()` with specs that use size values.

#### M7: No Validation of `ResizeWindowStep` Invariant

**File**: `src/nirip/planning/models.py:72-77`

`ResizeWindowStep` has `proportion: float | None` and `pixels: int | None`. Exactly one should be set, but there's no `@model_validator` enforcing this. A `ResizeWindowStep(axis=WIDTH, proportion=None, pixels=None)` would silently pass through to the handler where `actions.size_set_fixed(0)` would be called — setting a 0-pixel width.

---

### Low Severity (8)

#### L1: `FakeSnapshot` in conftest.py Doesn't Enforce `Snapshot` Protocol

The test fakes (`FakeWindow`, `FakeWorkspace`, `FakeSnapshot`) are dataclasses that happen to have matching attribute names but don't implement any protocol or inherit from the real types. If `niri_state.Snapshot` adds a required attribute, tests will still pass with the fakes — hiding a real breakage. Consider a `Protocol` or `typing.runtime_checkable` assertion.

#### L2: `compile_diff()` Doesn't Report `OPTIONAL_MISSING` Status

**File**: `src/nirip/planning/compiler.py:281-307`

Apps with `ResolutionStatus.OPTIONAL_MISSING` fall through all the `if/elif` branches and are silently omitted from the diff. This might be intentional (optional apps shouldn't clutter output), but it means `nirip diff` gives no feedback about optional apps that could be started. Consider a quiet indicator or summary count.

#### L3: `workspace_name` Field on Step Types Is Used Dual-Purpose

On `MoveWindowToWorkspaceStep`, both `workspace_name` (from `StepBase`, used for dependency tracking) and `target_workspace` (the actual move target) exist. They're always the same value in practice (set in compiler.py:120 and :125), which means one is redundant. Either use `workspace_name` as the target or drop `target_workspace`.

#### L4: `evaluate_rule()` Regex Compilation on Every Call

**File**: `src/nirip/resolve/matcher.py:29,47`

`re.search(rule.app_id_regex, ...)` and `re.search(rule.title_regex, ...)` compile regex patterns on every invocation. For resolution against many windows, this means O(apps × windows) compilations. Python's `re` module has an internal cache (default 512 patterns), so this is fine for typical session sizes but could become measurable for large captures. Consider `re.compile()` in the `MatchRule` validator or a process-level LRU.

#### L5: `AsyncNirip.open()` as Classmethod Returns Instance

**File**: `src/nirip/facade/async_nirip.py:29-32`

The pattern `async with await AsyncNirip.open() as nirip:` requires the user to `await` a classmethod that returns an instance, then use `async with` on it. This double-ceremony is unusual. Most async context manager patterns use either `async with AsyncNirip.open() as nirip:` (returning an async context manager) or `nirip = await AsyncNirip.create(); await nirip.close()`. The current pattern works but will surprise users familiar with `aiohttp.ClientSession()` or `asyncpg.connect()` style.

#### L6: `model_copy(update=...)` in `apply_defaults()` Creates O(apps) Frozen Copies

**File**: `src/nirip/spec/defaults.py:12-19`

For each app missing a timeout, `model_copy()` creates a new frozen Pydantic model. For each workspace with a modified app, another copy. This is O(workspaces × apps) allocations. Totally fine at current scale (sessions rarely exceed ~20 apps), but the pattern doesn't scale if nirip ever manages multi-session orchestration.

#### L7: CLI `main()` Catches All Exceptions

**File**: `src/nirip/cli/main.py:54`

```python
except Exception as e:
    print(f"error: {e}", file=sys.stderr)
    return 1
```

This swallows `KeyboardInterrupt` handling (which is `BaseException`, so it's fine) but also hides tracebacks for unexpected errors. During development, a `--verbose` flag that re-raises or prints the traceback would be invaluable.

#### L8: No `__all__` in Subpackage `__init__.py` Files

The `spec/`, `resolve/`, `planning/`, `execution/`, `capture/`, `facade/`, and `cli/` packages all have minimal `__init__.py` files that import key symbols but don't define `__all__`. This means `from nirip.resolve import *` pulls in everything, including private implementation details.

---

## Test Suite Assessment

### Coverage: 73% (1,246 statements, 335 missed)

**Well-covered (>80%)**:
- `spec/models.py` (98%), `spec/validators.py` (89%), `spec/defaults.py` (100%)
- `resolve/resolver.py` (93%), `resolve/models.py` (86%)
- `planning/compiler.py` (84%), `planning/models.py` (97%), `planning/ordering.py` (96%)
- `execution/executor.py` (81%), `execution/runtime.py` (100%)
- `errors.py` (94%), `config.py` (100%)

**Under-covered (<50%)**:
- `execution/handlers.py` (42%) — most step handlers untested
- `execution/predicates.py` (44%) — only CreateWorkspace case tested
- `cli/commands.py` (0%) — zero coverage
- `cli/main.py` (14%) — argparse setup only
- `cli/formatting.py` (45%) — format_diff partially tested
- `facade/async_nirip.py` (54%) — requires live connections

### Test Quality Observations

1. **Good**: Pure module tests (`test_matcher.py`, `test_compiler.py`, `test_resolver_drift.py`) are focused and correct.
2. **Good**: The integration test (`test_integration.py`) exercises the full `resolve → compile_plan → compile_diff` path.
3. **Concern**: Execution handlers are the riskiest code (they talk to IPC, spawn processes, wait for conditions) but have the least coverage. The `WaitForWindowStep` test uses monkeypatching to stub `_wait`, which is the right approach — more of this is needed for other handlers.
4. **Missing**: No tests for error paths in the executor (process spawn failure, IPC connection loss, timeout cascading).
5. **Missing**: No tests for `is_already_satisfied` predicate beyond the implicit call in `test_execute_plan_basic`.
6. **Missing**: No tests for `SetWindowStateStep` or `ResizeWindowStep` handler logic.

### Recommendations for Test Improvements

1. Add a `test_handlers.py` that monkeypatches `_request` and `_wait` to exercise each step handler in isolation.
2. Add predicate tests with real `FakeSnapshot` data to verify skip logic.
3. Add at least one CLI smoke test using `main(["diff", "fixtures/basic.yaml"])` with a fixture spec.
4. Add a test for the greedy assignment edge case (two apps competing for same window).

---

## Architecture Assessment

### Pipeline Clarity: Excellent

```
YAML → load_spec → SessionSpec → resolve(spec, snapshot) → Resolution
                                                               ↓
                                          compile_plan(resolution, options) → Plan
                                                                               ↓
                                                          execute_plan(plan, ports, options) → ApplyResult
```

Every stage has clear inputs, outputs, and ownership. No ambient state, no global mutable singletons.

### Modularity: Excellent

Each module can be tested in complete isolation. The `spec/` tests never touch `resolve/`, the `resolve/` tests never touch `planning/`, etc. This is the hallmark of well-separated concerns.

### Error Model: Good

The exception hierarchy (`NiripError → SpecError → SpecValidationError`, `PlanningError → CycleError`, `CaptureError`, `NiripConnectionError`) covers the key failure modes. `SpecValidationError` collecting multiple errors is a nice touch.

### API Surface: Clean

The top-level `__init__.py` exports exactly what a consumer needs: the main class (`AsyncNirip`), convenience functions (`apply_session`, `plan_session`, `diff_session`, `load_session`), and key types (`Plan`, `SessionDiff`, `ApplyResult`, `SessionSpec`, `NiripConfig`).

---

## Specific Code Observations

### Clever Patterns Worth Preserving

1. **Dependency wiring in `compile_plan()`** (lines 229-257): Building `app_first_step`/`app_last_step` indices and using them to wire `depends_on` edges before topological sort is elegant. It separates "what steps exist" from "what order do they run in."

2. **`is_already_satisfied()` as pre-execution skip gate**: Idempotency check before action execution is the right pattern for reconciliation loops. If you re-run a partially-completed plan, already-satisfied steps skip cleanly.

3. **`StepBase` with `app_name`/`workspace_name`**: These metadata fields enable the dependency wiring pattern above without type-specific inspection.

### Patterns to Watch

1. **The `_request()` helper** (handlers.py:35-38) does sync-or-async dispatch with `asyncio.iscoroutine()`. This suggests the `NiriClient` API is unstable about whether methods are sync or async. Pin this behavior or document the expectation.

2. **`WaitForWindowStep` handler uses nonlocal mutation** (handlers.py:106-112) to capture `matched_wid` from inside a predicate closure. This works but is fragile — if `_wait` evaluates the predicate multiple times (e.g., for debouncing), the last match wins. Ensure this is intentional.

3. **`model_copy()` for immutable updates** throughout — correct pattern but verbose. Consider a helper like `def with_deps(step: StepBase, extra_deps: list[str]) -> StepBase` to reduce ceremony.

---

## Refactoring Suggestions (Beyond Current Plan)

These are not bugs — they're potential future improvements if the project continues to grow:

1. **Extract `WindowAssigner` protocol**: The greedy assignment in `matcher.py` could be pluggable. A `Protocol` with `assign(apps, windows) -> list[MatchDecision]` would let you swap in optimal matching later without touching the resolver.

2. **Step builder pattern**: `compile_plan()` at 100+ lines is the longest function. It could benefit from a `PlanBuilder` class with methods like `.ensure_workspace(wr)`, `.spawn_app(ar, wr)`, `.place_window(ar, wr)` — each returning the step IDs for dependency wiring.

3. **Structured logging in executor**: Currently, execution produces `StepResult` objects but no live observability. Adding structured log events (or a callback/hook) would help debugging in production without polluting the return type.

4. **Config expansion in `apply_defaults()`**: The current approach of baking default_timeout into every AppSpec at load time means you can't change the timeout and re-apply without reloading. If you ever want "live config reload," you'd need to defer defaults to resolution time. This is fine for now.

---

## AGENTS.md Accuracy Check

The `AGENTS.md` file has a few stale references:
- Mentions `SyncNirip` in facade module table (line 32) — was deleted in Phase 6.
- Lists `nimri-ipc` as the IPC library name — the actual dependency is `niri-pypc` (pyproject.toml).
- References `SessionOptions.mode` and `SessionOptions.move_unmatched` (line 58) — these fields don't exist.
- States Python >= 3.11 (line 77) — pyproject.toml requires >= 3.13.

---

## Final Verdict

| Category | Rating |
|----------|--------|
| Architecture | ★★★★★ |
| Code Quality | ★★★★☆ |
| Test Coverage | ★★★☆☆ |
| API Design | ★★★★☆ |
| Documentation | ★★★☆☆ |
| Production Readiness | ★★★★☆ |

The library is well-designed, well-typed, and well-structured. The main gaps are in test coverage for execution handlers and CLI, and a few minor correctness concerns (exhaustive match, greedy assignment). None of these are blocking for a 0.2.0 release targeting developer tooling use cases.

**Recommended next actions (priority order):**
1. Add exhaustive fallback to `_should_act()`
2. Deduplicate `_STATE_CHECKS` between handlers and predicates
3. Add handler unit tests for `SetWindowStateStep`, `ResizeWindowStep`, `MoveWindowToWorkspaceStep`
4. Fix `apply_session()` to accept `config` parameter
5. Update AGENTS.md for accuracy
