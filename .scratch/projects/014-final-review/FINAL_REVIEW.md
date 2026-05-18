# NIRIP Final Code Review

**Version:** 0.2.0
**Date:** 2026-05-18
**Scope:** Full codebase review — architecture, correctness, safety, testing, and maintainability
**LOC:** ~2,316 source | ~988 test

---

## Executive Summary

NIRIP is a well-architected declarative workspace orchestrator. The code is clean, well-organized, and follows principled design. The separation between pure logic (spec, resolve, planning) and effectful code (execution, facade) is consistently maintained. The codebase is small enough to reason about holistically, yet structured with enough modularity for growth.

**Overall Grade: B+**

Strong architecture and code quality, held back by coverage gaps in the execution layer, a few correctness edge cases, and some areas where error handling could be more robust.

---

## Architecture Review

### Strengths

1. **Clean layered design.** The `spec → resolve → planning → execution` pipeline is well-separated. Each layer has a clear contract and minimal coupling to adjacent layers.

2. **Purity boundary enforced.** Spec, resolve, and planning are entirely pure — no async, no I/O, no side effects. This makes them trivially testable and easy to reason about.

3. **Frozen Pydantic models.** Using `frozen=True` + `extra="forbid"` across all data models prevents a class of mutation bugs and enforces strict schemas.

4. **Protocol-based extension.** `WindowAssigner` and `ExecutionHook` are protocol classes, allowing alternative implementations without inheritance.

5. **Discriminated union for plan steps.** Using `Annotated[..., Discriminator("kind")]` gives exhaustive pattern matching and clean serialization.

### Concerns

1. **Facade does too little.** `AsyncNirip` is a thin wrapper that adds almost no value beyond resource management. The `diff` and `plan` methods are simple one-liners that could be standalone functions. The facade exists mainly for the `open()` context manager, which is fine — but calling `diff()` and `plan()` async when they do zero async work is misleading.

2. **No retry/backoff strategy.** The execution layer has a single timeout per step but no retry logic. For compositor actions that can transiently fail (e.g., race conditions during workspace creation), there's no path to retry.

3. **Linear execution only.** The executor processes steps sequentially even when the dependency graph would allow parallelism. For plans with many independent apps, this means unnecessarily slow execution.

---

## Correctness Analysis

### Critical Issues

#### 1. `MatchRule._validate_not_empty` has a subtle bug with `app_id=""`
**File:** `spec/models.py:29-41`

```python
has_leaf = any([
    self.app_id,       # empty string "" is falsy!
    self.app_id_regex,
    self.title,
    self.title_regex,
    self.pid is not None,
])
```

If a user provides `app_id: ""`, the model validator treats this as "no criterion" and will raise `"MatchRule must have at least one criterion"`. However, Pydantic will happily parse `{"app_id": ""}` into the model before this validator runs. The real issue: this means `MatchRule(app_id="")` is invalid, but the validator error message doesn't indicate *which* field failed. The user set `app_id` expecting it to work.

**Recommendation:** Explicitly handle the empty-string case in the validator with a clear error message.

#### 2. Ambiguous window assigned but status overridden
**File:** `resolve/resolver.py:58-59`

```python
if decision.is_ambiguous:
    status = ResolutionStatus.AMBIGUOUS
```

This overrides a previous status of DRIFTED or MATCHED. If a window *is* assigned (decision.assigned_window_id is not None) but the match is also ambiguous, the drift detection ran and populated `drift`, but the status says AMBIGUOUS. Downstream, `_should_act` returns False for AMBIGUOUS — meaning drifted windows with ambiguous matches are silently left in their current state. This is defensible behavior, but the drift data attached to the `AppResolution` becomes misleading (drift is present, but no action taken because status is AMBIGUOUS).

#### 3. `WaitForWindowStep` handler — race condition in process exit detection
**File:** `execution/handlers.py:113-127`

```python
done, pending = await asyncio.wait({wait_task, exit_task}, return_when=asyncio.FIRST_COMPLETED)
for task in pending:
    task.cancel()
if exit_task in done and wait_task not in done:
    rc = exit_task.result()
    return StepResult(...)
if wait_task in done:
    await wait_task  # This re-raises if it errored
```

If *both* tasks complete simultaneously (process exits and window appears in the same event loop tick), both will be in `done`. The code checks `exit_task in done and wait_task not in done` first, so it won't trigger the error path. But the subsequent `await wait_task` is redundant since `wait_task` is already done — it's just retrieving the result. This isn't a bug, but the logic is fragile and would benefit from explicit handling of the both-complete case.

#### 4. `_detect_drift` workspace ID comparison
**File:** `resolve/resolver.py:107`

```python
if target_ws is None or window.workspace_id != target_ws.id:
```

If the workspace doesn't exist yet (`target_ws is None`), the window is flagged as WRONG_WORKSPACE drift. But if the workspace doesn't exist, the window *can't* be in it — this drift detection is irrelevant. The plan will create the workspace first anyway. This isn't incorrect per se, but it means drift reporting for windows in not-yet-created workspaces is noisy.

### Moderate Issues

#### 5. `compile_diff` doesn't report workspace focus changes
**File:** `planning/compiler.py:81-109`

The diff reports workspace creation and output changes, but does not report when a workspace `focus: true` setting will change the active workspace. Users running `nirip diff` won't see focus changes coming.

#### 6. `SetWindowStateStep` handler swallows timeout
**File:** `execution/handlers.py:178-179`

```python
except WaitTimeoutError:
    pass
```

After setting a window state, if the confirmation event never arrives, the step is still reported as COMPLETED. This means `ApplyResult.success` can be True even when a state change didn't actually take effect. The 1.5s timeout is short, making false-success likely on slow systems.

#### 7. Module-level `_DEFAULT_ASSIGNER` singleton
**File:** `resolve/matcher.py:15`

```python
_DEFAULT_ASSIGNER = GreedyAssigner()
```

Since `GreedyAssigner` has no mutable state, this is fine currently. But it's a latent problem if the assigner ever gains configuration or state.

#### 8. `_compile` LRU cache is unbounded-lifetime
**File:** `resolve/matcher.py:18-20`

```python
@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
```

The cache lives for the process lifetime. In a long-running daemon scenario (if nirip were ever used as a service), patterns from old specs would never be evicted until 256 unique patterns displace them. This is fine for CLI usage but worth noting.

---

## Safety & Security

### Process Spawning

**File:** `execution/handlers.py:85-90`

```python
env = os.environ.copy()
env.update(step.env)
if isinstance(step.command, str):
    proc = await asyncio.create_subprocess_exec("/bin/sh", "-lc", step.command, cwd=step.cwd, env=env)
else:
    proc = await asyncio.create_subprocess_exec(*step.command, cwd=step.cwd, env=env)
```

**Observations:**
- String commands are passed to `/bin/sh -lc`, which is shell execution. The `-l` flag loads the user's login profile. This is intentional (per the `shell: bool` field in SpawnSpec), but it's worth noting that arbitrary shell injection is possible via the YAML spec. Since the user writes their own specs, this is acceptable — but if specs were ever loaded from untrusted sources, this would be critical.
- The entire parent environment is inherited via `os.environ.copy()`. If the nirip process has sensitive env vars, spawned children inherit them. Consider documenting this behavior.
- No `stdin` handling — spawned processes inherit stdin from the nirip process. For a CLI tool this is fine, but could be surprising.

### Input Validation

The spec validation layer is solid:
- Regex patterns are compiled to check validity
- Cycle detection for `depends_on`
- Spawn commands are checked for emptiness
- Field-level Pydantic validation catches type errors

**Gap:** No validation on `cwd` in `SpawnSpec`. A nonexistent or inaccessible directory will cause a runtime `FileNotFoundError` during execution rather than a validation error at load time.

---

## Testing Review

### Coverage Summary

| Module | Coverage | Assessment |
|--------|----------|-----------|
| spec/ | 89-100% | Good |
| resolve/ | 71-100% | Adequate |
| planning/ | 80-97% | Good |
| execution/ | 44-100% | **Weak** |
| cli/ | 0-49% | **Weak** |
| facade/ | 54% | Moderate |

### Test Quality

**Strengths:**
- Test fakes in `conftest.py` are well-designed — structural compatibility is verified at import time
- Tests use `SimpleNamespace` for lightweight mocking, keeping tests fast
- Integration test validates the full pipeline from spec → resolution → plan → diff
- Good coverage of edge cases in validation (cycles, conflicts, weak matchers)

**Weaknesses:**

1. **Execution handlers are barely tested.** At 47% coverage, the most complex and risk-prone module has minimal test coverage. Every handler branch (spawn, wait, move, resize, focus, state) should have unit tests with mocked ports.

2. **No async tests.** The test suite contains zero `pytest-asyncio` tests. The entire execution layer, facade, and CLI commands are untested at the integration level.

3. **CLI completely untested.** 0% coverage on `commands.py`, 13% on `main.py`. The argparse setup isn't verified, command dispatch isn't tested, and output formatting has only partial coverage.

4. **No error path tests in execution.** The `WaitTimeoutError` catch, `ConnectionError`/`OSError` catch, process early-exit detection, and window-ID-not-available paths are all uncovered.

5. **Missing property-based testing.** The matcher logic (rule evaluation, candidate ranking, assignment) would benefit from hypothesis-based fuzzing to find edge cases in the matching algorithm.

---

## Code Quality & Style

### Positive Patterns

- Consistent use of `from __future__ import annotations` across all files
- Type annotations on all function signatures
- No bare `except` clauses (exception: the broad `except Exception` in loader.py is justified)
- Clean imports organized by stdlib → third-party → local
- Descriptive step IDs with meaningful prefixes
- Good use of computed_field for derived properties

### Style Issues

1. **Inconsistent `del` usage for unused parameters.** `NullHook` uses `del step` while other places use `_` prefixes. The `del` pattern is unusual in Python; `_` prefix is idiomatic.

2. **`GreedyAssigner.assign` uses `del apps`** (assigner.py:17). This is confusing — it reads like a bug. A comment isn't sufficient; rename the parameter to `_apps` or use `*` separator.

3. **Magic timeouts scattered.** `3.0`, `5.0`, `1.5` appear as literal timeout values in handlers.py. These should either come from config or be named constants.

4. **`_PROPERTY_CHECKS` data-driven drift detection** (resolver.py:91-95) is elegant but fragile — if the Window model adds new properties, this list won't be updated. Consider a registry pattern or at minimum a comment documenting which properties are covered.

5. **`SessionDiff` uses mutable `list` fields on a frozen model.** This works because Pydantic creates copies during construction, but `compile_diff` directly appends to `diff.workspace_changes` etc. (compiler.py:87-88). Wait — since the model is frozen, these appends should fail... Let me check. Actually, `SessionDiff` inherits from `NiripModel` which is `frozen=True`. The `compile_diff` function does `diff.workspace_changes.append(...)` which mutates the *list object* (not the model field), which Pydantic's frozen mode allows. This is technically valid but semantically breaks the immutability contract.

### Naming

- `SessionPorts` is well-named for the ports-and-adapters pattern
- `PlanBuilder` with `_track` + `_next_id` is clear internal API
- `compile_plan` vs `compile_diff` — clear distinction
- Minor: `_should_act` could be `_needs_action` for clarity

---

## Design Observations

### The Assignment Algorithm

The `GreedyAssigner` is simple: sort all (app, window, tier) triples by tier descending, then assign first-come-first-served. This is O(n*m*log(n*m)) where n=apps, m=windows.

**Limitation:** This greedy approach doesn't guarantee globally optimal assignment. Consider:
- App A matches Window 1 (EXACT) and Window 2 (STRONG)
- App B matches Window 1 (STRONG) only

Greedy assigns Window 1 → App A (EXACT), leaving App B unmatched. The optimal assignment is Window 1 → App B, Window 2 → App A. For a small tool this is unlikely to matter, but it's a known limitation of greedy vs. Hungarian algorithm.

### The Type System

The codebase uses Pydantic models extensively but doesn't leverage `NewType` or branded types for IDs. Window IDs, workspace IDs, and step IDs are all plain `int` or `str`. A `WindowId = NewType("WindowId", int)` would prevent accidental mixing.

### Error Recovery

The executor has `stop_on_error` but no rollback mechanism. If a plan partially executes (e.g., workspace created, 2 of 5 apps spawned, then failure), there's no way to undo. The user is left with a partially-applied state. For a workspace manager this is acceptable — you can just re-run — but worth documenting.

---

## Dependency Analysis

### External Dependencies

| Dependency | Version | Risk |
|-----------|---------|------|
| pydantic ≥2.12.5 | Stable | Low — mature library |
| niri-pypc ≥0.5.0 | In-house | Medium — git tag dependency, not PyPI |
| niri-state ≥0.2.5 | In-house | Medium — git tag dependency, not PyPI |
| pyyaml ≥6.0 | Stable | Low |

**Risk:** Both `niri-pypc` and `niri-state` are sourced from git tags. If these repos are force-pushed or tags are moved, builds become non-reproducible. Consider pinning to commit hashes or publishing to a private index.

### Import Hygiene

No circular imports detected. The dependency direction is strictly enforced:
```
errors ← spec ← resolve ← planning ← execution ← facade ← cli
```

Each module only imports from layers below it.

---

## Specific Recommendations

### High Priority

1. **Add async integration tests for execution handlers.** Mock `NiriClient` and `NiriState` to test the handler dispatch, timeout behavior, and error paths without requiring a live compositor.

2. **Fix the mutable-list-on-frozen-model pattern in `compile_diff`.** Either:
   - Build lists first, then construct `SessionDiff` in one shot (preferred)
   - Or make `SessionDiff` non-frozen with a `freeze()` method

3. **Validate `SpawnSpec.cwd` at load time** — check it's a syntactically valid path (not that it exists, since it may not exist at spec-write time, but at least not empty/malformed).

4. **Extract magic timeouts** in `handlers.py` into named constants or pull from `NiripConfig`.

### Medium Priority

5. **Add CLI tests** — at minimum test argparse construction and command dispatch with mocked async functions.

6. **Document the `SetWindowStateStep` timeout swallow** — either change behavior to report COMPLETED_UNCONFIRMED or add an explicit comment explaining why timeout is acceptable.

7. **Consider `asyncio.TaskGroup`** for independent steps that don't depend on each other. This would speed up plans with many independent spawn/place operations.

8. **Add `--check` mode to CLI** — exit 0 if converged, exit 1 if drift detected. Useful for CI/scripting.

### Low Priority

9. **Replace `SimpleNamespace` in integration tests** with `conftest.FakeWindow`/`FakeSnapshot` for consistency.

10. **Add a `__repr__` to key models** (Resolution, Plan) for better debugging in REPL.

11. **Consider replacing `GreedyAssigner` with a maximum-weight bipartite matching** (scipy.optimize.linear_sum_assignment or equivalent). Would handle the suboptimal assignment case described above.

12. **Type-narrow window IDs** with NewType for compile-time safety.

---

## File-by-File Risk Assessment

| File | Risk | Reason |
|------|------|--------|
| `execution/handlers.py` | **High** | Most complex, lowest test coverage, direct I/O |
| `planning/builder.py` | **Medium** | Complex step generation logic, dependency wiring |
| `resolve/matcher.py` | **Medium** | Rule evaluation with many branches |
| `resolve/resolver.py` | Low | Clean but has the ambiguous-override subtlety |
| `spec/validators.py` | Low | Well-tested, clear logic |
| `planning/compiler.py` | Low | Thin orchestration layer |
| `cli/commands.py` | Low | Simple async wrappers (but untested) |
| Everything else | Very Low | Small, well-understood modules |

---

## Summary of Findings

| Category | Count | Severity |
|----------|-------|----------|
| Critical correctness issues | 1 | The empty-string MatchRule validator |
| Moderate correctness issues | 3 | Ambiguous override, timeout swallow, drift noise |
| Safety concerns | 2 | Shell injection surface (accepted), env inheritance |
| Testing gaps | 5 | Execution, CLI, async, error paths, property-based |
| Code quality nits | 5 | del pattern, magic numbers, naming, frozen-list mutation |
| Architecture suggestions | 3 | Parallel execution, retry logic, rollback |

---

## Conclusion

NIRIP is a well-engineered library that demonstrates thoughtful architecture. The purity boundary, frozen models, and layered design are genuinely good practice. The main areas for improvement are:

1. **Testing the execution layer** — this is where bugs will hide and where they'll cause real damage (spawning wrong processes, moving wrong windows).
2. **The frozen-model mutation antipattern** in `compile_diff` — this will surprise future contributors.
3. **Hardcoded timeouts** — these should be configurable for different system speeds.

The codebase is in good shape for v0.2.0 and is well-positioned for incremental improvement.
