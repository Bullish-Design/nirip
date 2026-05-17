# Nirip Code Review

A detailed review of the nirip codebase as of commit `605a9f9`, evaluated against the refined concept document and implementation guide.

---

## Executive Summary

The codebase has been successfully rewritten to match the refined concept architecture. The three root problems identified in the concept document — phantom abstractions, structurally dishonest plan model, and locally greedy matching — have all been addressed. The implementation is clean, well-structured, and faithful to the design.

**Overall assessment: Strong implementation with minor gaps.** The code is production-ready for its core pipeline (spec → resolve → plan → compile). The execution layer is correctly structured but has some rough edges around error handling and action API compatibility. The test suite covers the happy path but needs significant expansion.

---

## 1. Alignment with Refined Concept

### 1.1 Problem #1: Phantom Abstractions — RESOLVED ✓

The concept identified that nirip defined `SnapshotLike`, `WindowLike`, and `ActionClient` protocols instead of consuming the real types.

**Current state:** These protocols are completely absent from the codebase. The implementation directly uses:
- `niri_pypc.types.generated.models.Window` in `resolve/matcher.py` and `capture/inference.py`
- `niri_state.Snapshot` in `resolve/resolver.py`, `execution/predicates.py`, `capture/capturer.py`
- `niri_pypc.NiriClient` in `execution/models.py`, `facade/async_nirip.py`
- `niri_state.NiriState` in `execution/models.py`, `facade/async_nirip.py`

**However**, the `resolve/resolver.py` _detect_drift function uses `getattr()` extensively:
```python
def _detect_drift(window: object, napp: object, ws_name: str, ws_by_name: dict[str, object]) -> list[DriftItem]:
```

This accepts `object` types and uses `getattr(window, "is_floating", False)`. While this enables test fakes to work without importing real types, it contradicts the "concrete by default" principle. The type signature lies — it claims `object` when it should declare the real types and let tests deal with compatibility through structural typing or proper fakes.

**Recommendation:** Change `_detect_drift` signature to use the concrete types (`Window`, `NormalizedApp`, etc.) and document how tests should construct compatible objects.

### 1.2 Problem #2: Structurally Dishonest Plan Model — RESOLVED ✓

The discriminated union step model is fully implemented in `planning/models.py`:
- 13 concrete step types, each with a `kind: Literal[...]` discriminator
- `SpawnWindowStep` carries `command`, `cwd`, `env`, `shell`
- `WaitForWindowStep` carries `match: MatchRule` and `timeout_s`
- `MoveWindowToWorkspaceStep` carries `window_id` and `target_workspace`
- `PlanStep` is a proper `Annotated[..., Discriminator("kind")]` union

The compiler in `planning/compiler.py` correctly propagates all data from the normalized app into the typed steps. Invalid states are unrepresentable.

### 1.3 Problem #3: Locally Greedy Matching — RESOLVED ✓

`resolve/matcher.py` implements the global assignment algorithm:
1. Evaluates all (app, window) pairs
2. Collects triples sorted by confidence descending
3. Greedy assigns ensuring no window is claimed by two apps

The 1:1 invariant is maintained. The `test_matcher.py::test_assign_windows_unique` test explicitly verifies this.

---

## 2. Layer-by-Layer Review

### 2.1 Foundation (`_base.py`, `errors.py`, `config.py`)

**Grade: A**

Clean, minimal, correct.

- `NiripModel` correctly sets `extra="forbid"`, `frozen=True`, `use_enum_values=True`
- Error hierarchy is slim — operational failures are `StepResult` outcomes, not exceptions
- `SpecValidationError` carries structured `errors` and `warnings` lists
- `CycleError` carries the cycle path
- `NiripConfig` inherits `NiripModel` (gains frozen/forbid automatically)

**No issues found.**

---

### 2.2 Spec Layer (`spec/`)

**Grade: A-**

**Strengths:**
- `MatchRule` correctly uses `validation_alias="any"` with `populate_by_name=True`
- `SessionOptions.mode` is `Literal["reconcile", "clean"]` (not bare `str`)
- All models inherit `NiripModel`
- Validator checks are comprehensive: unique names, dependency cycles, regex validity, weak matchers, inter-app conflicts, spawn commands

**Issues:**

1. **`MatchRule` missing `use_enum_values`**: The `MatchRule` overrides `model_config` to add `populate_by_name=True` but doesn't include `use_enum_values=True`. This is inherited from `NiripModel` but the override replaces the entire config dict per Pydantic semantics — it needs explicit inclusion or should use `ConfigDict` merging:

```python
class MatchRule(NiripModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        # Missing: use_enum_values=True — though MatchRule has no enums, this is inconsistent
    )
```

Actually, upon closer inspection, Pydantic v2 merges `ConfigDict` from parent classes. The child config augments the parent. So this is fine — `use_enum_values` is inherited. **Not a bug.**

2. **`_check_depends_on_refs` silently continues after finding dangling refs**: When a dependency references an unknown app, the error is recorded but the cycle detection DFS still runs over a graph that may contain invalid nodes (entries with keys like `"ws/dep"` that were never added to `graph`). This works because `graph.get(node, [])` returns `[]` for unknown nodes, but it's fragile.

3. **No cross-workspace `depends_on` validation**: The validator only checks `depends_on` references within the same workspace. The concept document says "verify `depends_on` targets exist within the same workspace" — this is enforced. But the error message could be clearer about *why* cross-workspace deps are invalid (if that's the intent).

---

### 2.3 Resolve Layer (`resolve/`)

**Grade: A-**

**Strengths:**
- `NormalizedSession` correctly maintains an `app_index` for fast lookup
- `assign_windows` is clean and correct
- `evaluate_rule` handles all criteria types, AND/OR/NOT composition, and confidence scoring
- `_detect_drift` correctly handles the missing-workspace case (the key bug fix from the concept)
- `MatchDecision.is_ambiguous` uses `>0.6` threshold as specified

**Issues:**

1. **`_detect_drift` type annotations use `object`** (discussed above). The function should be typed with concrete types.

2. **No `windows_by_workspace` optimization in resolver**: The resolver iterates all windows globally via `assign_windows(normalized.apps, snapshot.windows.values())`. For large compositor states, this is O(apps × windows). The `Snapshot.windows_by_workspace` index is available but unused. For the typical use case (< 50 windows) this is fine, but worth noting.

3. **`MatchDecision.is_ambiguous` threshold hardcoded**: The `> 0.6` threshold is baked into the model. It's not configurable. For a 0.1.x release this is fine, but it means two candidates with confidence 0.6 and 0.6 are NOT ambiguous, while 0.61 and 0.61 ARE. This edge case could surprise users.

4. **`evaluate_rule` returns `(False, 0.0, reasons)` when `not scores and not failed`**: If a `MatchRule` has only a `not_rule` that is satisfied (the negation passes), the `scores` list will be empty (since `not_rule` doesn't append to scores — it only sets `failed`). This means a match rule consisting solely of `not: {app_id: "x"}` will always return `(False, 0.0, ...)` even when the negation is correctly satisfied.

    **This is a bug.** A `MatchRule(not_rule=MatchRule(app_id="x"))` should match any window whose `app_id` is NOT "x", but the current code will never match because `scores` stays empty. The fix: when only `not_rule` is present and it didn't fail, the rule should be considered matched with some confidence (e.g., 0.5 for negation-only rules).

5. **PID field access uses `getattr(window, "pid", None)`**: This is defensive but inconsistent with the rest of the matcher which accesses `window.app_id` and `window.title` directly. If `Window` doesn't have a `pid` field, this will silently never match on PID. The concept document notes "verify the exact field names" — this should be resolved definitively.

---

### 2.4 Planning Layer (`planning/`)

**Grade: A**

**Strengths:**
- Discriminated union is correctly implemented with Pydantic's `Discriminator`
- `compile_plan` correctly propagates all SpawnSpec fields into `SpawnWindowStep`
- `WaitForWindowStep` carries the full `MatchRule` and timeout
- `_parse_size` handles both proportion and `px:N` format
- `topological_sort` uses Kahn's algorithm with cycle detection
- `compile_diff` produces a clear human-readable summary
- Focus steps (window and workspace) are correctly emitted at the end

**Minor issues:**

1. **`_parse_size` doesn't validate the `px:` suffix**: `int(value[3:])` will raise `ValueError` on `"px:abc"`. This should be caught and converted to a `PlanningError` or validated at spec time.

2. **`Plan.requires_spawn` uses string comparison instead of isinstance**:
```python
def requires_spawn(self) -> bool:
    return any(s.kind == "spawn_window" for s in self.steps)
```
This works because `kind` is a literal, but `isinstance(s, SpawnWindowStep)` would be more idiomatic given the discriminated union. However, this is a style preference and both are correct.

3. **No `depends_on` wiring for inter-app dependencies**: The compiler emits `depends_on=[ensure_id]` for steps that need the workspace to exist first, and `depends_on=[spawn_id]` for wait steps. But `AppSpec.depends_on` (inter-app dependencies like "wait for app B before starting app A") is **not wired**. The `NormalizedApp.depends_on` field is propagated through normalization but never consumed by the compiler.

    **This is a gap.** The concept document says "Apps with `depends_on` references produce steps that depend on the referenced app's completion steps." This is not implemented. The topological sort infrastructure is in place, but the compiler doesn't create cross-app dependency edges.

---

### 2.5 Execution Layer (`execution/`)

**Grade: B+**

**Strengths:**
- `SessionPorts` is a clean dataclass grouping state + client
- `execute_plan` correctly initializes `SessionRuntime`, iterates steps, respects `stop_on_error`
- `handlers.py` has a complete match statement covering all 13 step types
- `predicates.py` correctly implements skip-checks for workspace/floating/tiling/fullscreen/maximized
- The `_request` helper handles both sync and async client responses
- The `_wait` helper handles both possible `wait_until` signatures (with and without `config`)

**Issues:**

1. **`handlers.py` catches exceptions too broadly**: The outer try/except catches `WaitTimeoutError` and then `Exception`. If a programming error occurs (e.g., `TypeError` from misusing an action builder), it will be silently swallowed as a `FAILED` step result instead of propagating. This makes debugging difficult.

    **Recommendation:** Catch only expected exceptions (`WaitTimeoutError`, `ConnectionError`, `OSError`) and let unexpected ones propagate.

2. **`SpawnWindowStep` handler returns `window_id=proc.pid`**:
```python
return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="spawned", window_id=proc.pid)
```
This overloads `window_id` (which should be a compositor window ID) with a process PID. These are different namespaces. The `StepResult.window_id` field semantics are ambiguous.

3. **`WaitForWindowStep` handler doesn't record the matched window ID**: Unlike the concept document's example (which stores `matched_window_id` in runtime state), the current implementation just returns a generic "window appeared" message without identifying *which* window was matched. This means subsequent steps that need the window ID of a newly spawned app (e.g., move it to a workspace) can't find it.

    **This is a significant gap.** After spawn+wait, the system has no way to wire the newly-appeared window's ID into subsequent placement steps. The Plan compiler assigns `window_id` from the resolution (which is `None` for MISSING apps), so SetFloating/Move steps for newly spawned apps will have `wid=None` and be skipped.

    Wait — looking more carefully at the compiler:
    ```python
    if ar.needs_spawn and napp.spawn:
        # ... spawn + wait steps ...
    wid = ar.match_decision.assigned_window_id  # This is None for MISSING apps!
    if ar.needs_move and wid is not None:  # This will be False for newly spawned apps
        # ... never reached for spawned apps
    ```

    **This confirms the gap.** For MISSING apps that need to be spawned, `wid` is `None`, so no placement/move steps are emitted. The system can spawn windows but cannot place them afterward. This is a known limitation that will need a "re-resolve after spawn" mechanism or a two-pass compilation approach.

4. **`SetFullscreenStep`/`SetMaximizedStep` handlers use toggle semantics**: The actions `fullscreen_window` and `maximize_window_to_edges` are toggles. The handler sends them unconditionally, but the predicate skips if already in the desired state. The problem: if the predicate is stale (snapshot hasn't updated), the handler might toggle *out* of fullscreen. The concept document acknowledges this is a toggle but doesn't address the race.

5. **`SetColumnWidthStep` handler focuses the window first**:
```python
await _request(ports.client, actions.focus_window(step.window_id))
change = ...
await _request(ports.client, actions.set_column_width(change))
```
This is correct (niri's `set_column_width` operates on the focused column), but it introduces a side effect — it changes compositor focus. If multiple column width steps run, the user's focus will jump around. The concept document doesn't address this; it's an inherent limitation of niri's IPC model.

6. **No verification after action execution**: The concept says each handler should "wait for verification — use `wait_until()` to observe the expected state change." The current handlers fire actions but don't verify. They return COMPLETED immediately after sending the request. This means the execution can race ahead of the compositor's state.

7. **`_wait` helper signature workaround**:
```python
async def _wait(state: Any, predicate: Any, timeout: float) -> Any:
    try:
        return await wait_until(state, predicate, timeout=timeout)
    except TypeError:
        return await wait_until(state, predicate, config=None, timeout=timeout)
```
This try/except for API compatibility is fragile. If `wait_until` raises `TypeError` for a legitimate reason (e.g., predicate returns non-bool), it will be caught and the alternative call attempted, which may produce confusing errors.

---

### 2.6 Capture Layer (`capture/`)

**Grade: A**

Clean, simple, correct. Uses `niri_state.api.selectors` as specified. `infer_app_name` and `infer_match_rule` are reasonable heuristics. The `CapturedSession` model with `app_count` and `workspace_count` computed fields is a nice touch.

**No issues found.**

---

### 2.7 Facade Layer (`facade/`)

**Grade: A-**

**Strengths:**
- `AsyncNirip` correctly owns `NiriState` + `NiriClient`
- `open()` classmethod handles connection setup
- Context manager protocol is correctly implemented
- `SyncNirip` wraps with `asyncio.run()` as specified

**Issues:**

1. **`SyncNirip.open()` uses `asyncio.run()` for state initialization**: This means each sync method call (`diff`, `plan`, `apply`) also calls `asyncio.run()`, creating a new event loop each time. If `NiriState` maintains internal async state (subscriptions, connections), these won't persist across calls. This is a known limitation of the sync wrapper pattern but could cause subtle bugs if `NiriState.open()` establishes a persistent connection that dies between event loops.

2. **`AsyncNirip.health` is a property, not a method**:
```python
@property
def health(self) -> HealthState:
    return self._state.health()
```
This calls `self._state.health()` (a method) behind a property. The concept document shows it as a property too, so this is intentional. But it's slightly odd — properties usually don't call methods that might have side effects or fail.

3. **No `doctor()` method**: The concept document specifies `async def doctor(self, spec: SessionSpec | None = None) -> DoctorReport` but it's not implemented. This is likely intentional for a 0.1.x release.

---

### 2.8 CLI Layer (`cli/`)

**Grade: B+**

**Strengths:**
- Clean argparse structure
- Deferred imports in `main()` (doesn't import heavy modules until needed)
- Commands properly use `AsyncNirip.open()` context manager
- Warnings displayed to stderr

**Issues:**

1. **`cmd_apply` uses blocking `input()` inside an async function**: This blocks the event loop. For a CLI this is fine, but it's technically incorrect async code. Should use `asyncio`-compatible input or restructure.

2. **No `--dry-run` flag for `apply`**: The `--yes` flag skips confirmation, but there's no way to see the plan without being prompted to apply.

3. **Output format is raw YAML dump**: `yaml.dump(result.model_dump())` produces verbose, unformatted output with Pydantic's full model serialization (including computed fields, nested models, etc.). This will be hard to read for users. The concept mentions `format_diff()` and `format_result()` helpers that don't exist.

4. **Missing commands from concept**: `doctor`, `inspect`, `watch`, `status` commands are not implemented.

---

## 3. Test Suite Review

### 3.1 Coverage Assessment

**Grade: C+**

The test suite has 17 files covering:
- Foundation: `test_base.py` (2 tests), `test_errors.py` (3 tests), `test_config.py` (2 tests)
- Spec: `test_spec_models.py` (3 tests), `test_spec_loader.py` (2 tests), `test_spec_validators.py` (2 tests), `test_spec_defaults.py` (1 test)
- Resolve: `test_normalizer.py` (1 test), `test_matcher.py` (2 tests), `test_resolver_drift.py` (1 test)
- Planning: `test_planning_models.py` (2 tests), `test_ordering.py` (2 tests), `test_compiler.py` (1 test)
- Execution: `test_executor.py` (1 test)
- Capture: `test_capturer.py` (1 test)
- Integration: `test_integration.py` (1 test), `test_matcher_resolver_planning.py` (1 test)

**Total: ~25 test functions.** This is thin for a project with 34 source files.

### 3.2 Critical Missing Tests

1. **No `test_resolver.py`** — the resolver (core of the system) has only one drift-specific test. No tests for:
   - MATCHED status with no drift
   - OPTIONAL_MISSING classification
   - AMBIGUOUS status propagation
   - workspace existence checks
   - output correctness checks
   - `launch_missing` option interaction

2. **Global assignment invariant needs more tests**:
   - Three apps competing for two windows
   - Confidence tie-breaking behavior
   - App with no matching windows returns `assigned_window_id=None`

3. **Compiler data propagation tests are minimal**: Only one test verifies spawn+wait. Missing:
   - Move steps emitted for DRIFTED apps
   - SetFloating/SetTiling for placement drift
   - SetColumnWidth/SetWindowHeight parsing
   - FocusWindow/FocusWorkspace emission
   - `depends_on` ordering (workspace ensure → app spawn)

4. **Executor tests are trivial**: Only one test runs a single FocusWorkspace step with dummy ports. Missing:
   - `stop_on_error` behavior
   - Timeout handling
   - Skip predicate behavior
   - Multiple step execution ordering
   - Runtime state tracking (spawn_pid, matched_window_id)

5. **No validation edge case tests**:
   - Nested `any_of` / `not_rule` regex validation
   - Very long dependency chains
   - Duplicate app names across different workspaces (should be allowed)

### 3.3 Test Infrastructure

The `conftest.py` defines `FakeWindow`, `FakeWorkspace`, `FakeSnapshot`, and `RecordingClient`. However:

- Tests in `test_matcher.py` define their own minimal `W` and `A` classes instead of using `conftest.FakeWindow`
- Tests in `test_compiler.py`, `test_resolver_drift.py`, and `test_integration.py` use `SimpleNamespace` instead of conftest fakes
- The `RecordingClient` in conftest is never used by any test

**This indicates the conftest was written to spec but the tests were written independently.** The fakes should be consolidated.

---

## 4. Architectural Issues

### 4.1 The Post-Spawn Placement Gap

**Severity: High (design limitation)**

When an app is MISSING and needs to be spawned, the compiler emits `SpawnWindowStep` + `WaitForWindowStep`. But subsequent placement steps (move, floating, fullscreen, column width) require a `window_id` which is only available after the window appears.

The current compiler sets `wid = ar.match_decision.assigned_window_id` which is `None` for MISSING apps. All placement conditionals check `if wid is not None`, so they're all skipped.

**Impact:** Newly spawned windows will appear wherever niri places them by default. They won't be moved to the correct workspace, set floating, or sized. Only pre-existing windows get full placement.

**Fix options:**
1. **Two-phase execution:** After spawn+wait, re-resolve to get the new window ID, then emit placement steps dynamically.
2. **Runtime step injection:** The executor watches for the wait step to complete, extracts the window ID, and dynamically creates follow-up steps.
3. **Deferred references:** Steps use a symbolic `"spawned:{app_name}"` reference that the executor resolves at runtime.

### 4.2 `SyncNirip` Event Loop Lifecycle

**Severity: Medium**

Each `SyncNirip` method creates a new event loop via `asyncio.run()`. If `NiriState` uses a persistent WebSocket/subscription internally, the connection may be dropped between calls.

The concept document doesn't address this — it's an inherent limitation of the sync wrapper pattern. The fix would be to maintain a single event loop (via `asyncio.Runner` in Python 3.12+) or document that `SyncNirip` is for one-shot operations only.

### 4.3 No `SessionOptions` Enforcement in Planning

**Severity: Medium**

`SessionOptions` has fields like `match_existing`, `launch_missing`, `move_unmatched`, and `mode`. The AGENTS.md explicitly warns: "SessionOptions fields must be wired and enforced or removed as dead code."

Current enforcement:
- `launch_missing` → used in resolver to set `action_required`
- `stop_on_error` → used in executor
- `mode` → **not enforced** (reconcile vs clean)
- `match_existing` → **not enforced**
- `move_unmatched` → **not enforced**

The `clean` mode (which would presumably close unmatched windows) and `move_unmatched` (move orphan windows somewhere) are defined in the schema but have no implementation path.

---

## 5. Code Quality

### 5.1 Style and Consistency

- Consistent use of `from __future__ import annotations`
- Clean imports, no circular dependencies
- Appropriate use of `Field(default_factory=...)` for mutable defaults
- Good separation of concerns — pure layers have no I/O
- Pydantic `computed_field` used appropriately for derived properties

### 5.2 Type Safety

- Strong typing throughout with proper `str | None`, `list[T]`, union types
- `_detect_drift` using `object` types is the only significant type weakness
- `handlers.py` uses `Any` for the `_request` and `_wait` helpers — acceptable given the API compatibility dance

### 5.3 Error Handling

- Spec errors are caught at load time (correct)
- Execution errors are structured `StepResult` outcomes (correct)
- The broad exception catch in `handlers.py` is concerning but not dangerous for a CLI tool
- CLI properly sends errors to stderr

### 5.4 Module Boundaries

The dependency graph matches the concept:
```
_base ← spec ← resolve ← planning ← execution ← facade ← cli
                                              ↑
                                           capture
```

No circular imports. Pure layers don't import asyncio. The boundary discipline from AGENTS.md is respected.

---

## 6. Gaps vs. Refined Concept

| Concept Requirement | Status | Notes |
|---|---|---|
| NiripModel base with extra="forbid" | ✓ Complete | |
| Discriminated union plan steps | ✓ Complete | All 13 types |
| Global window assignment | ✓ Complete | Greedy algorithm |
| ValidatedSpec bundles spec + warnings | ✓ Complete | |
| Subprocess spawn for PID tracking | ✓ Complete | |
| SessionPorts dataclass | ✓ Complete | |
| Drift detection for missing workspaces | ✓ Complete | |
| Operational failures as StepResult | ✓ Complete | |
| No execution/actions.py wrapper | ✓ Complete | Direct niri-pypc usage |
| Inter-app depends_on wiring | ✗ Missing | Compiler doesn't wire |
| Post-spawn placement | ✗ Missing | Design gap |
| Verification after action execution | ✗ Missing | Fire-and-forget |
| Doctor command | ✗ Missing | Not implemented |
| Inspect/watch/status commands | ✗ Missing | Not implemented |
| SessionOptions mode/match_existing/move_unmatched | ✗ Missing | Dead code |

---

## 7. Recommendations

### Immediate (before next release)

1. **Fix the `not_rule`-only match bug** in `evaluate_rule`. A rule with only a `not_rule` should be matchable.

2. **Add a TODO/warning comment** about the post-spawn placement gap. Users will expect spawned windows to be placed correctly.

3. **Expand executor tests** — at minimum, test `stop_on_error`, timeout, and skip predicates.

4. **Type `_detect_drift` properly** — use concrete types, not `object`.

### Short-term (next milestone)

5. **Implement post-spawn placement** — choose option 1 (re-resolve after spawn) or option 3 (deferred references).

6. **Wire `AppSpec.depends_on`** into the compiler's dependency graph.

7. **Add verification after actions** — at least for move and workspace creation where the snapshot can confirm success.

8. **Remove or implement dead `SessionOptions` fields** — `mode="clean"`, `match_existing`, `move_unmatched`.

### Medium-term

9. **Structured CLI output** — replace `yaml.dump(model_dump())` with purpose-built formatters.

10. **Add `doctor` command** — check connection health, validate spec, report ambiguities.

11. **Consider `asyncio.Runner`** for `SyncNirip` to maintain connection state across calls.

---

## 8. Test Suite Expansion Priority

In priority order:

1. **Resolver tests** — MATCHED/DRIFTED/MISSING/AMBIGUOUS/OPTIONAL_MISSING classification
2. **Compiler data propagation** — every step type with correct field values
3. **Executor sequencing** — stop_on_error, skip predicates, timeout handling
4. **Global assignment edge cases** — N apps M windows with various confidence scores
5. **Validator edge cases** — deep nesting, cross-workspace refs, regex failures
6. **Integration tests** — full pipeline with realistic snapshots (golden file tests)

---

## 9. Final Notes

This is a well-executed rewrite. The architecture is sound, the layer boundaries are clean, and the core pipeline (spec → normalize → resolve → plan → diff) works correctly. The main gaps are in the execution layer (post-spawn placement, verification) and in test coverage.

The codebase reads as if written by someone who understood the refined concept deeply and implemented it faithfully, with pragmatic compromises where the concept left open questions (like `_detect_drift`'s typing) or where implementation complexity was deferred (post-spawn placement, inter-app deps).

For a 0.1.x release focused on the reconciliation pipeline, this is solid work.
