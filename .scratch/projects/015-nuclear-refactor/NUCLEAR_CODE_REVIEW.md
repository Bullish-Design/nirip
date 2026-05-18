# Nuclear Refactor: Code Review

**Reviewer:** Claude
**Branch:** `nuclear_refactor`
**Date:** 2026-05-18
**Scope:** Full codebase review of v2 (8 source files, 1,618 LOC; 8 test files, 360 LOC)

---

## Executive Summary

The refactor achieved its goals: 41 files / 2,316 LOC collapsed to 8 files / 1,618 LOC with a clean linear dependency graph. The architecture is dramatically simpler. Every file is self-contained, the import graph is acyclic, and the pipeline concept (load → resolve → plan → execute) reads clearly from the module structure alone.

That said, this review holds the code to the stated ambition: *"the best, most conceptually simplest, cleanest, most elegant codebase and architecture possible."* What follows is a thorough critique — the issues are ordered from most to least impactful.

---

## Severity Legend

| Tag | Meaning |
|-----|---------|
| **BUG** | Incorrect behavior, will produce wrong results or crash |
| **DESIGN** | Architectural issue affecting clarity, coupling, or extensibility |
| **SIMPLIFY** | Opportunity to reduce complexity with no behavior change |
| **CONSISTENCY** | Inconsistency within the codebase's own conventions |
| **CORRECTNESS** | Subtle logical issue that may not manifest today but will bite later |
| **NAMING** | Name that misleads, obscures intent, or violates convention |
| **TESTING** | Missing or weak test coverage for real behavior |

---

## 1. `spec.py` (295 LOC)

### 1.1 [DESIGN] `ValidationError` shadows a Python builtin (**COMPLETE**)

```python
class ValidationError(NiripError):
```

`ValidationError` is a name already heavily used — Python's `ValueError`, Pydantic's `ValidationError`, and now this. Any consumer who also uses Pydantic will hit confusing name collisions. The public API re-exports this from `__init__.py`, making it worse.

**Suggestion:** `SpecValidationError` is explicit and un-ambiguous. It's one word longer and infinitely less confusing. The v1 name `SpecValidationError` was actually better here.

### 1.2 [CONSISTENCY] `_FROZEN` defined in 4 files (**COMPLETE**)

`_FROZEN = ConfigDict(extra="forbid", frozen=True)` appears in `spec.py`, `resolve.py`, `plan.py`, and `execute.py`. This is the exact thing the guide said would *replace* `NiripModel`, but now it's copy-pasted 4 times. If you ever want to add `use_enum_values=True` or change the policy, you change it in 4 places.

**Suggestion:** Define `_FROZEN` once in `spec.py` and import it. Or if that feels wrong because it's an implementation detail, accept the repetition but acknowledge it's a trade-off. At minimum, the 4 copies should be *identical* — and they are, which is good.

### 1.3 [CORRECTNESS] `_check_weak_matchers` only checks `title_regex`, not `title`

```python
def _check_weak_matchers(spec, warnings):
    for ws in spec.workspaces:
        for app in ws.apps:
            m = app.match
            if m.title_regex and not any([m.app_id, m.app_id_regex, m.title, m.pid]):
                warnings.append(...)
```

A `title`-only matcher (no `app_id`, no regex, no pid) is arguably *weaker* than `title_regex` — titles change constantly. A user with `match: {title: "Firefox"}` gets no warning, but `match: {title_regex: "Firefox"}` does. The asymmetry seems unintentional.

### 1.4 [SIMPLIFY] `_check_inter_app_conflicts` signature tuple includes `None`

```python
key = (m.app_id or "", m.app_id_regex or "", m.title or "", m.title_regex or "", m.pid)
```

The check `key != ("", "", "", "", None)` means an entirely empty match rule (which is already rejected by the model validator) would silently pass. This is fine in practice but the logic is awkward — the `None`-vs-`""` mixed sentinel is a minor smell.

### 1.5 [DESIGN] `load_from_dict` catches `Exception` broadly (**COMPLETE**)

```python
except Exception as e:  # pydantic validation shape is user-facing text
    raise NiripError(f"spec parse error in {source}: {e}") from e
```

Catching `Exception` is too broad. This swallows `KeyboardInterrupt`-adjacent issues (via chained exceptions), programming bugs, etc. Pydantic raises `pydantic.ValidationError` (its own) for model issues.

**Suggestion:** `except pydantic.ValidationError as e:` — targeted and honest.

### 1.6 [SIMPLIFY] Validation functions take mutable lists as out-params

Every `_check_*` function mutates external `errors` and `warnings` lists. This is a C-style pattern. A more Pythonic approach: each returns its own list, and the caller concatenates. But this is a *style* preference — the current approach works fine and avoids allocation. Acknowledge it as a deliberate choice.

---

## 2. `resolve.py` (298 LOC)

### 2.1 [BUG] `evaluate_rule` returns `WEAK` for empty-but-valid composite rules (**COMPLETE**)

```python
if best_tier == MatchTier.NONE:
    best_tier = MatchTier.WEAK
return True, best_tier
```

If a rule has only `not_rule` set (e.g., "match anything that isn't Chrome"), and the window passes (it's not Chrome), then `failed` is `False` and `best_tier` is still `NONE` (because `not_rule` doesn't *raise* the tier). The fallback upgrades it to `WEAK`. This is correct behavior — but the *intent* is subtle and should have a comment explaining why `NONE` gets promoted. A reader will think this is a bug.

### 2.2 [DESIGN] `_assign` is O(A × W) with an O(A × W log(A × W)) sort

The assignment algorithm builds all (app, window, tier) triples, sorts them, then greedily assigns. This is fine for desktop-scale data (tens of apps, hundreds of windows). But it's worth noting: for N apps and M windows, it's O(NM log NM). The v1 `GreedyAssigner` was the same, so no regression.

### 2.3 [NAMING] `_assign` returns `list[tuple[int | None, bool]]` — opaque (**COMPLETE**)

The return type is a positional tuple whose fields are only documented in the docstring. This is the only function in the codebase that returns a structurally-significant tuple that isn't a model. Consider a `NamedTuple`:

```python
class _Assignment(NamedTuple):
    window_id: int | None
    is_ambiguous: bool
```

This costs nothing and makes every access site self-documenting.

### 2.4 [CORRECTNESS] `resolve()` accesses `snapshot.windows[window_id]` without guard

```python
if window_id is not None:
    window = snapshot.windows[window_id]
```

If `_assign` returns a `window_id` that the snapshot no longer contains (theoretically impossible if the snapshot is immutable, but the type system doesn't guarantee it), this raises `KeyError` with no context. A `.get()` with an appropriate error would be more defensive.

### 2.5 [CONSISTENCY] `ws_by_name` type annotation says `Workspace` but it's `Any` at runtime

```python
def _detect_drift(
    window: Window,
    app_spec: AppSpec,
    ws_name: str,
    ws_by_name: dict[str, Workspace],
) -> list[DriftItem]:
```

In tests, `FakeWorkspace` is passed. The type annotation `Workspace` is from `niri_pypc.types.generated.models` but the function uses duck typing (`.id`, `.output`). This is fine for duck-typing, but the import of `Workspace` at module level is then only used for this annotation. Could use a `Protocol` or just annotate as `Any`.

### 2.6 [SIMPLIFY] `_PROPERTY_CHECKS` table in resolve vs `_STATE_DRIFT_MAP` table in plan

Two different lookup tables for the same conceptual mapping (drift kind → window property). `_PROPERTY_CHECKS` maps `(DriftKind, win_attr, place_attr)`. `_STATE_DRIFT_MAP` maps `(DriftKind, place_attr, true_prop, false_prop)`. They encode the same domain knowledge in different shapes. This is a subtle duplication of the "floating/fullscreen/maximized" mapping.

---

## 3. `plan.py` (340 LOC)

### 3.1 [DESIGN] `PlanStep` is a god-object with sparse fields (**COMPLETE**)

The guide was explicit about this trade-off: 9 step subclasses → 1 `PlanStep` with sparse optional fields. This is simpler in structure but sacrifices type safety — nothing prevents constructing a `RESIZE` step with a `match` field, or a `WAIT_FOR_WINDOW` step with a `proportion` field. The frozen Pydantic model with `extra="forbid"` prevents *extra* fields, but not *irrelevant* ones.

This is the single biggest design trade-off in the refactor. It's defensible — the old discriminated union was heavy. But it means the executor must trust the plan builder, and bugs in plan construction silently produce nonsensical steps.

**Suggestion:** If you want to keep the single class, add a `model_validator(mode="after")` that checks field consistency per `kind`. E.g., `RESIZE` requires `axis`, `SPAWN_WINDOW` requires `command`. This reclaims the type safety without the subclass explosion.

### 3.2 [DESIGN] `emit` closure has untyped `**kwargs`

```python
def emit(kind: StepKind, description: str, **kwargs) -> str:
```

Every call to `emit()` passes keyword arguments that become `PlanStep` fields. Typos in field names will only be caught at Pydantic validation time (which will raise, since `extra="forbid"`), not at the call site. This is a trade-off of the closure pattern vs the builder pattern.

### 3.3 [CORRECTNESS] `_placement_steps` emits `MOVE_WINDOW` for `MISSING` apps with no `window_id`

```python
def _placement_steps(ar: AppResolution, ws_name: str, deps: list[str], emit) -> None:
    if ar.needs_move or ar.status == ResolutionStatus.MISSING:
        emit(
            StepKind.MOVE_WINDOW,
            ...,
            window_id=ar.window_id,  # None for MISSING apps
            ...
        )
```

For `MISSING` apps, `ar.window_id` is `None`. The executor handles this by falling back to `_resolve_wid`, which checks the `apps` dict for a `matched_window_id` set during `WAIT_FOR_WINDOW`. So it works — but only because of the implicit contract that `WAIT_FOR_WINDOW` has already run and populated `apps[name].matched_window_id`. This dependency chain is invisible in the type system.

### 3.4 [SIMPLIFY] `_wire_dependencies` mutates `steps` list in-place via `steps[:]` (**COMPLETE**)

```python
steps[:] = [
    s.model_copy(update={"depends_on": s.depends_on + deps_to_add[s.id]}) if s.id in deps_to_add else s
    for s in steps
]
```

This is a full-list replacement disguised as in-place mutation. It's clever but non-obvious. The `build_plan` caller passes `steps` as a local, so the `steps[:]` slice-assignment is functionally equivalent to reassignment — except it also works if someone held a reference to the list. Since nobody does, a simple return value would be clearer:

```python
def _wire_dependencies(...) -> list[PlanStep]:
    ...
    return [s.model_copy(...) if ... else s for s in steps]
```

### 3.5 [CONSISTENCY] `_topological_sort` uses `sorted()` for determinism

```python
queue: deque[str] = deque(sorted([sid for sid, degree in indegree.items() if degree == 0]))
```

Good — deterministic ordering. But `sorted(edges[sid])` sorts by string, which means `"create_workspace-2"` sorts before `"spawn_window-1"`. The order is deterministic but not semantically meaningful. This is fine — just noting it's lexicographic, not priority-based.

---

## 4. `execute.py` (346 LOC)

### 4.1 [BUG] Shell spawn uses `/bin/sh -lc` — login shell assumption (**COMPLETE**)

```python
proc = await asyncio.create_subprocess_exec("/bin/sh", "-lc", step.command, cwd=step.cwd, env=env)
```

The `-l` flag creates a *login shell*, which sources `.profile`/`.bash_profile`. This is unusual for subprocess spawning — most tools use `-c` alone. The login shell behavior means environment setup runs twice (once from the parent, once from the login shell), which can cause issues with `PATH` duplication, slow startup, or unexpected `.profile` side effects.

**Suggestion:** Drop `-l` unless there's a specific reason (e.g., users need their full login environment for app spawning). If so, document it.

### 4.2 [BUG] `_execute_step` WAIT_FOR_WINDOW: `proc.wait()` races with cancel (**COMPLETE**)

```python
done, pending = await asyncio.wait({wait_task, exit_task}, return_when=asyncio.FIRST_COMPLETED)
for task in pending:
    task.cancel()
if exit_task in done and wait_task not in done:
    rc = exit_task.result()
    ...
if wait_task in done:
    await wait_task  # re-raises exceptions
```

If both tasks complete between the `await asyncio.wait()` return and the pending-cancel loop, `pending` is empty and both are in `done`. The code then checks `exit_task in done and wait_task not in done` — which is `False` — and falls through to `if wait_task in done: await wait_task`. This is correct but fragile. The `await wait_task` line re-raises any exception from the wait, which is the right behavior.

However: if `exit_task` completes with a non-zero return code *and* `wait_task` also completed successfully (window appeared just before process exited), we still report success. This seems correct — the window appeared, which is what we wanted.

**Minor:** The cancelled tasks in `pending` should be awaited to suppress `asyncio` warnings:
```python
for task in pending:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

### 4.3 [DESIGN] `_NullHook` could be simpler

The `_NullHook` class exists solely because `hook: ExecutionHook | None` needs a fallback. An alternative: make `hook` non-optional with a default factory, or use a conditional call pattern. The current approach is fine — it's the standard Null Object pattern.

### 4.4 [CORRECTNESS] `SET_STATE` handler swallows `WaitTimeoutError` (**COMPLETE**)

```python
case StepKind.SET_STATE:
    ...
    try:
        await _wait(...)
    except WaitTimeoutError:
        pass
    return StepResult(..., outcome=StepOutcome.COMPLETED, ...)
```

If the state change doesn't take effect within 1.5s, the step still reports `COMPLETED`. This is a deliberate choice (the IPC request succeeded, we just can't confirm it). But it means a silent failure mode — the window state may not actually be what was requested.

**Suggestion:** Return `StepOutcome.COMPLETED` with a message like `"set (unconfirmed)"` so the user knows the verification timed out.

### 4.5 [SIMPLIFY] `_WAIT_CONFIG = NiriStateConfig()` is a module-level default (**COMPLETE**)

This creates a default config at import time. If `NiriStateConfig` ever needs initialization parameters, or if the default changes between versions, this could bite. It's fine today but a `# frozen default` comment would help.

### 4.6 [NAMING] `SessionPorts` is a jargon name (**COMPLETE**)

"Ports" in the hexagonal architecture sense isn't obvious to most readers. `SessionClients`, `NiriConnection`, or even `SessionIO` would be more immediately understandable. Minor but contributes to conceptual load.

### 4.7 [CORRECTNESS] `execute_plan` builds `apps` dict from step names, not from resolution (**COMPLETE**)

```python
apps: dict[str, _AppState] = {}
for step in plan.steps:
    if step.app_name and step.app_name not in apps:
        apps[step.app_name] = _AppState()
```

If two apps in different workspaces share the same `app_name`, they'll collide in this dict. The spec validation doesn't prevent this — it only checks uniqueness *within* a workspace. This could cause one app's `matched_window_id` to be overwritten by another's.

**This is a real bug.** The key should be `f"{step.workspace_name}/{step.app_name}"`.

### 4.8 [CONSISTENCY] `os` imported but `os.environ` used only once

```python
env = os.environ.copy()
env.update(step.env)
```

Fine — just noting the import is minimal usage.

---

## 5. `capture.py` (37 LOC)

### 5.1 [DESIGN] Cleanest file in the codebase

Nothing to critique. 37 lines, clear purpose, no unnecessary abstraction. This is the reference standard the other files should aspire to.

### 5.2 [NAMING] `_infer_name` truncates titles to 30 chars but doesn't sanitize (**COMPLETE**)

```python
return window.title.lower().replace(" ", "-")[:30]
```

If the title contains characters that are invalid in YAML keys or app names (e.g., `/`, `:`, `\n`), the generated spec could be unparseable. This is a capture *template* so it's expected to be hand-edited, but a sanitizer would be more robust.

---

## 6. `cli.py` (250 LOC)

### 6.1 [DESIGN] `format_resolution` hardcodes `"wrong_workspace"` string (**COMPLETE**)

```python
if any(d.kind.value != "wrong_workspace" for d in ar.drift):
```

Should use the enum: `d.kind != DriftKind.WRONG_WORKSPACE`. The string literal bypasses the type system and will silently break if the enum value ever changes.

**Fix:** Import `DriftKind` and compare to the enum member.

### 6.2 [DESIGN] CLI commands duplicate the NiriState lifecycle (**COMPLETE**)

```python
# cmd_apply:
state = await NiriState.open()
client = NiriClient.create()
try: ...
finally:
    await state.close()
    await client.close()

# cmd_diff:
state = await NiriState.open()
try: ...
finally:
    await state.close()

# cmd_plan:
state = await NiriState.open()
try: ...
finally:
    await state.close()

# cmd_capture:
state = await NiriState.open()
try: ...
finally:
    await state.close()
```

Four commands, four identical lifecycle patterns. The v1 `AsyncNirip` facade was deleted specifically to avoid this indirection — but the result is 4x boilerplate. A context manager or helper would be justified here:

```python
@asynccontextmanager
async def _open_state():
    state = await NiriState.open()
    try:
        yield state
    finally:
        await state.close()
```

This is ~5 lines that eliminate ~20 lines of repetition. The v1 `AsyncNirip` was over-abstracted (it wrapped *both* state and client with config); a simple context manager is the right middle ground.

### 6.3 [CONSISTENCY] `LoggingHook.on_step_complete` uses `del step` (**COMPLETE**)

```python
def on_step_complete(self, step, result) -> None:
    del step
    print(f"     {result.outcome} ({result.duration_s:.1f}s)", ...)
```

The `del step` is a lint-suppression idiom (unused parameter). But the guide said to delete this pattern ("No need for the `del step` lines — just `pass`"). It should either use `_step` as the parameter name, or just ignore the warning. The `del` idiom is unusual in this codebase.

### 6.4 [SIMPLIFY] `cmd_apply` calls `build_plan` twice (confirmation path)

```python
if not yes and resolution.has_drift:
    print(format_resolution(resolution), file=sys.stderr)
    answer = await asyncio.to_thread(input, "Apply? [y/N] ")
    if answer.lower() != "y":
        return "Aborted."

plan = build_plan(resolution, spec.options)  # always builds, even after confirmation
```

If the user confirms, `build_plan` runs once. If `dry_run`, it runs once. There's no double-build. Actually, this is fine on re-reading — the confirmation path shows the *resolution*, not the plan. No issue here. *(Self-correction.)*

### 6.5 [DESIGN] `cmd_capture` imports `yaml` for dumping — consider model's built-in (**COMPLETE**)

```python
text = yaml.dump(spec.model_dump(), default_flow_style=False)
```

This works but produces Python-dict-style YAML (with `null` for None, ordered by dict insertion). Pydantic's `model_dump(mode="json")` would be more predictable for serialization. Minor.

---

## 7. `__init__.py` (49 LOC)

### 7.1 [DESIGN] `apply_session` uses `asyncio.run()` which fails inside existing event loops (**COMPLETE**)

```python
return asyncio.run(_run())
```

If a user calls `apply_session()` from within an already-running async context (e.g., Jupyter, an async web framework, a test with `pytest-asyncio`), this will raise `RuntimeError: This event loop is already running`. The v1 code had the same issue.

**Suggestion:** Detect the loop:
```python
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    return asyncio.run(_run())
else:
    raise RuntimeError("apply_session() cannot be called from async context; use the pipeline directly")
```

### 7.2 [SIMPLIFY] `__all__` is well-curated

Good: exactly the right symbols. No over-export, no under-export. The public API is: 2 errors, 3 domain types, 4 pipeline functions, 1 convenience function. Clean.

---

## 8. `__main__.py` (3 LOC)

Perfect. No notes.

---

## 9. Cross-Cutting Concerns

### 9.1 [TESTING] Test coverage is thin — 360 LOC tests for 1,618 LOC source (**COMPLETE**)

The v1 had 988 LOC of tests for 2,316 LOC source (43% ratio). v2 has 360 LOC for 1,618 LOC (22%). This is a significant regression. Key gaps:

- **No tests for `_placement_steps`** — the most complex function in `plan.py`
- **No tests for `_wire_dependencies`** — inter-app dependency wiring
- **No tests for `_detect_drift`** — the property-check loop
- **No tests for `format_resolution` with drift/move/spawn** — only tests the converged case
- **No tests for `format_result`** at all
- **No tests for `build_parser` or `main()`** — CLI argument parsing
- **No tests for `_assign` ambiguity detection** — only tested indirectly via `resolve`
- **No tests for `evaluate_rule` with composite rules** (`any_of`, `not_rule`)
- **No tests for `_check_depends_on_refs` cycle detection**
- **`test_execute.py` tests only pure functions** — `_resolve_wid`, `_is_satisfied`, counters. The actual `execute_plan` and `_execute_step` are untested.

### 9.2 [CONSISTENCY] Type annotations are inconsistent on `window` parameters (**COMPLETE**)

- `capture.py:_infer_name(window)` — untyped
- `capture.py:_infer_match(window)` — untyped
- `resolve.py:_detect_drift(window: Window, ...)` — typed as `Window`
- `execute.py:_STATE_CHECKS` lambdas — `lambda w: w.is_floating` — untyped

The codebase uses duck typing for windows in practice (tests use `FakeWindow`). Either consistently annotate with the concrete type and accept that tests use `# type: ignore`, or define a `WindowLike` protocol. The current mix is neither.

### 9.3 [DESIGN] `_FROZEN` repeated with `extra="forbid"` on every model (**COMPLETE**)

Every Pydantic model in the codebase uses `extra="forbid"`. This is excellent defensive practice. But it means that if a user passes unexpected YAML keys (common when iterating on a spec), they get a Pydantic error rather than a helpful nirip error. The `load_from_dict` catch handles this, so it's fine for the loading path. Direct model construction will give raw Pydantic errors.

### 9.4 [DESIGN] No `__version__` in the package (**COMPLETE**)

`pyproject.toml` has `version = "1.0.0"` but there's no `__version__` attribute on the package. This is fine for modern Python (use `importlib.metadata.version("nirip")`), but worth noting if users expect `nirip.__version__`.

---

## 10. Architecture Assessment

### What's Excellent

1. **Linear dependency graph.** `spec → resolve → plan → execute → cli`. No cycles. Any operation traces through at most 2 files. This is genuinely hard to achieve in a refactor and it's done cleanly here.

2. **Pipeline as architecture.** The four-step pipeline (load → resolve → plan → execute) is the conceptual backbone, and the file structure *is* the pipeline. You can understand the entire system by reading the filenames left to right.

3. **Flat Resolution model.** Eliminating the nested `WorkspaceResolution` → `AppResolution` hierarchy in favor of a flat list with `apps_in(ws_name)` is the right call. It simplifies every consumer.

4. **`emit()` closure.** Replacing `PlanBuilder` with a closure is clever and appropriate. The counter, tracking dicts, and step list are cleanly scoped. No unnecessary class state.

5. **Enums everywhere.** `StepKind`, `MatchTier`, `DriftKind`, `ResolutionStatus`, `StepOutcome`, `WindowProperty`, `ResizeAxis` — the domain vocabulary is explicit and exhaustive.

6. **`capture.py` as gold standard.** 37 lines, zero dependencies on internal abstractions, does exactly one thing. Every file should aspire to this clarity-to-purpose ratio.

### What Needs Work

1. **Test coverage is the biggest gap.** The source code quality is high but the tests are skeletal. The v1 → v2 test migration is incomplete. Many critical paths (drift detection, placement steps, dependency wiring, execution handlers, CLI formatting) have zero test coverage.

2. **The `PlanStep` god-object.** Collapsing 9 types into 1 saved a lot of boilerplate but created an untyped bag of optional fields. A single `model_validator` per `kind` would recover most of the lost type safety.

3. **The app-name collision bug in `execute_plan`.** Apps from different workspaces with the same name will share `_AppState` entries. This needs a fix.

4. **CLI lifecycle duplication.** Four commands repeat the same open/try/finally pattern. A 5-line context manager eliminates the repetition without the over-abstraction of v1's `AsyncNirip`.

---

## 11. Prioritized Action Items

### Must Fix (Bugs)

| # | File | Issue | Effort |
|---|------|-------|--------|
| 1 | `execute.py:305-308` | App-name key collision across workspaces | Small — key on `ws/app` |
| 2 | `cli.py:49` | Hardcoded `"wrong_workspace"` string bypasses enum | Trivial |

### Should Fix (Design)

| # | File | Issue | Effort |
|---|------|-------|--------|
| 3 | `spec.py:17` | `ValidationError` name collision with Pydantic | Small rename |
| 4 | `plan.py:40` | `PlanStep` has no per-kind field validation | Medium — add `model_validator` |
| 5 | `execute.py:179` | Shell spawn uses `-l` (login shell) | Trivial — remove flag |
| 6 | `spec.py:287` | `except Exception` in `load_from_dict` is too broad | Trivial |
| 7 | Tests | Bring coverage from 22% ratio back toward 40%+ | Large |

### Nice to Have (Polish)

| # | File | Issue | Effort |
|---|------|-------|--------|
| 8 | `cli.py` | Extract NiriState lifecycle context manager | Small |
| 9 | `resolve.py:163` | `_assign` return type → NamedTuple | Small |
| 10 | `cli.py:111` | Remove `del step` idiom | Trivial |
| 11 | `execute.py:256-258` | SET_STATE swallowed timeout → "unconfirmed" message | Trivial |
| 12 | `execute.py:206-207` | Await cancelled tasks to suppress asyncio warnings | Small |
| 13 | `__init__.py:49` | Document `apply_session` event-loop limitation | Trivial |

---

## 12. Line Count Assessment

| File | Target | Actual | Delta |
|------|--------|--------|-------|
| `spec.py` | ~300 | 295 | -5 |
| `resolve.py` | ~300 | 298 | -2 |
| `plan.py` | ~350 | 340 | -10 |
| `execute.py` | ~300 | 346 | +46 |
| `capture.py` | ~70 | 37 | -33 |
| `cli.py` | ~180 | 250 | +70 |
| `__init__.py` | ~60 | 49 | -11 |
| **Total** | **~1,560** | **1,618** | **+58** |

The `cli.py` overshoot (+70) is from the lifecycle boilerplate and fuller `format_resolution`. The `capture.py` undershoot (-33) is from dropping the notes/stats features. The `execute.py` overshoot (+46) is from the inline step handlers being more verbose than expected. All reasonable.

---

## 13. Final Verdict

**The refactor is a clear win.** The codebase went from 41 files of indirection to 8 files of direct, linear pipeline code. The architecture is dramatically more legible. The biggest concern is the test coverage regression — the source code is ready for 1.0, but the test suite is not.

Fix the two bugs (app-name collision, hardcoded string), restore test coverage to v1 levels, and this is a genuinely excellent small codebase.
