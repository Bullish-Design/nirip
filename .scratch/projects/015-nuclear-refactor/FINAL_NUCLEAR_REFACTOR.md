# Final Nuclear Refactor — Implementation Guide

This document provides step-by-step instructions to resolve every issue from the Updated Nuclear Code Review. Each section maps 1:1 to a review item and includes the exact file, lines, and code changes required.

---

## Issue 1.3 — `_check_weak_matchers` only checks `title_regex`, not `title`

**File:** `src/nirip/spec.py` lines 239–244
**Category:** CORRECTNESS
**Risk:** Low — additive warning, no behavior change

### Problem

A `title`-only matcher (`match: {title: "Firefox"}`) is arguably *weaker* than a `title_regex` matcher because plain titles are fragile and change constantly. Yet only `title_regex`-only matchers get a warning. The asymmetry is unintentional.

### Implementation

Replace the `_check_weak_matchers` function:

```python
def _check_weak_matchers(spec: SessionSpec, warnings: list[str]) -> None:
    for ws in spec.workspaces:
        for app in ws.apps:
            m = app.match
            has_strong = any([m.app_id, m.app_id_regex, m.pid])
            if (m.title or m.title_regex) and not has_strong:
                kind = "title-only" if m.title and not m.title_regex else "title_regex-only"
                warnings.append(
                    f"weak matcher in {ws.name}/{app.name}: {kind} rules can be unstable"
                )
```

**Logic change:**
- Extract `has_strong = any([m.app_id, m.app_id_regex, m.pid])` — the anchors that make a matcher robust.
- Warn if either `title` or `title_regex` is set and none of the strong anchors are present.
- Include which kind of weak matcher it is in the warning message.

### Tests to add/update

- `test_validate_session_weak_title_only_matcher` — spec with `match: {title: "Firefox"}` and no `app_id`/`pid` should produce a "title-only" warning.
- Existing `title_regex`-only test should still pass (warning message changes from `"title_regex-only rules can be unstable"` to same).

---

## Issue 1.4 — `_check_inter_app_conflicts` mixed `None`/`""` sentinel

**File:** `src/nirip/spec.py` lines 247–257
**Category:** SIMPLIFY
**Risk:** Low — cosmetic logic cleanup

### Problem

The signature tuple uses `m.pid` directly (which is `int | None`), while all other fields coalesce to `""`. The empty-match guard `key != ("", "", "", "", None)` mixes sentinels.

### Implementation

Normalize `pid` to a consistent sentinel:

```python
def _check_inter_app_conflicts(spec: SessionSpec, warnings: list[str]) -> None:
    _EMPTY = ("", "", "", "", "")
    signatures: dict[tuple[str, str, str, str, str], list[str]] = {}
    for ws in spec.workspaces:
        for app in ws.apps:
            m = app.match
            key = (
                m.app_id or "",
                m.app_id_regex or "",
                m.title or "",
                m.title_regex or "",
                str(m.pid) if m.pid is not None else "",
            )
            signatures.setdefault(key, []).append(f"{ws.name}/{app.name}")

    for key, owners in signatures.items():
        if len(owners) > 1 and key != _EMPTY:
            warnings.append(f"potential matcher conflict: {', '.join(owners)}")
```

**Changes:**
- Convert `pid` to `str(m.pid)` when present, `""` when `None`.
- All tuple elements are now `str`, and the empty guard is a uniform `("", "", "", "", "")`.
- Extract `_EMPTY` constant for clarity.

### Tests

- Existing conflict-detection tests should pass unchanged (behavior is identical).

---

## Issue 2.5 — `ws_by_name` type annotation says `Workspace` but uses duck typing

**File:** `src/nirip/resolve.py` lines 1–11, 280–284
**Category:** CONSISTENCY
**Risk:** Low — type-only change

### Problem

`_detect_drift` annotates `ws_by_name: dict[str, Workspace]` but only accesses `.id` and `.output` (via the caller). Tests pass `FakeWorkspace`. The `Workspace` import is only used for this annotation.

### Implementation

Define a `Protocol` and use it instead of the concrete `Workspace` type:

```python
# At top of resolve.py, add to imports:
from typing import Any, NamedTuple, Protocol, runtime_checkable

# After imports, before MatchTier:
@runtime_checkable
class WorkspaceLike(Protocol):
    """Minimal workspace interface used by drift detection."""

    @property
    def id(self) -> int: ...

    @property
    def name(self) -> str | None: ...

    @property
    def output(self) -> str | None: ...
```

Then update the function signature and the `resolve()` function:

```python
def _detect_drift(
    window: Window,
    app_spec: AppSpec,
    ws_name: str,
    ws_by_name: dict[str, WorkspaceLike],
) -> list[DriftItem]:
    ...
```

And in `resolve()`:

```python
def resolve(spec: SessionSpec, snapshot: Snapshot) -> Resolution:
    ws_by_name: dict[str, WorkspaceLike] = {
        ws.name: ws for ws in snapshot.workspaces.values() if ws.name is not None
    }
    ...
```

**Cleanup:** Remove the `Workspace` import from `niri_pypc.types.generated.models` if it is no longer used elsewhere in the file. (Check: `Window` is still needed.)

```python
from niri_pypc.types.generated.models import Window  # remove Workspace
```

### Tests

- Existing tests with `FakeWorkspace` will now properly satisfy the `WorkspaceLike` protocol — no test changes needed.
- Optionally add a static assertion: `assert isinstance(FakeWorkspace(...), WorkspaceLike)` in test setup.

---

## Issue 2.6 — Duplicate drift mapping tables (`_PROPERTY_CHECKS` vs `_STATE_DRIFT_MAP`)

**File:** `src/nirip/resolve.py` lines 273–277 and `src/nirip/plan.py` lines 96–100
**Category:** SIMPLIFY
**Risk:** Medium — cross-module refactor touching resolve + plan

### Problem

Two lookup tables encode the same domain knowledge (floating/fullscreen/maximized ↔ drift kind) in different shapes:

| Module | Table | Shape |
|---|---|---|
| `resolve.py` | `_PROPERTY_CHECKS` | `(DriftKind, win_attr, placement_attr)` |
| `plan.py` | `_STATE_DRIFT_MAP` | `(DriftKind, placement_attr, true_prop, false_prop)` |

### Implementation

**Step 1:** Create a shared mapping in a new or existing shared location. Since `resolve.py` is already imported by `plan.py`, place the canonical table in `resolve.py`:

```python
# In resolve.py, replace _PROPERTY_CHECKS with:

class StatePropMapping(NamedTuple):
    """Canonical mapping between drift kinds and window/placement properties."""
    drift_kind: DriftKind
    window_attr: str        # attribute on Window (e.g., "is_floating")
    placement_attr: str     # attribute on PlacementSpec (e.g., "floating")


STATE_PROPERTY_MAP: list[StatePropMapping] = [
    StatePropMapping(DriftKind.WRONG_FLOATING, "is_floating", "floating"),
    StatePropMapping(DriftKind.WRONG_FULLSCREEN, "is_fullscreen", "fullscreen"),
    StatePropMapping(DriftKind.WRONG_MAXIMIZED, "is_maximized", "maximized"),
]
```

**Step 2:** Update `_detect_drift` in `resolve.py` to use the new table:

```python
def _detect_drift(...) -> list[DriftItem]:
    drift: list[DriftItem] = []
    # ... workspace drift check unchanged ...

    for prop in STATE_PROPERTY_MAP:
        current_val: Any = getattr(window, prop.window_attr, False)
        desired_val: Any = getattr(app_spec.placement, prop.placement_attr)
        if current_val != desired_val:
            drift.append(DriftItem(kind=prop.drift_kind, current=str(current_val), desired=str(desired_val)))

    return drift
```

**Step 3:** Update `plan.py` to derive its mapping from the shared table. Add a module-level constant that computes the plan-specific shape:

```python
# In plan.py, replace _STATE_DRIFT_MAP with:
from nirip.resolve import STATE_PROPERTY_MAP

# Map from placement_attr to (true_prop, false_prop)
_PROP_TO_WINDOW_PROPERTY: dict[str, tuple[WindowProperty, WindowProperty | None]] = {
    "floating": (WindowProperty.FLOATING, WindowProperty.TILING),
    "fullscreen": (WindowProperty.FULLSCREEN, None),
    "maximized": (WindowProperty.MAXIMIZED, None),
}

_STATE_DRIFT_MAP: list[tuple[DriftKind, str, WindowProperty, WindowProperty | None]] = [
    (prop.drift_kind, prop.placement_attr, *_PROP_TO_WINDOW_PROPERTY[prop.placement_attr])
    for prop in STATE_PROPERTY_MAP
]
```

This ensures the drift-kind-to-placement-attr mapping is defined once (in `resolve.py`) and the plan-specific WindowProperty mapping is derived from it.

### Tests

- All existing tests should pass unchanged.
- Consider adding a test that asserts `_STATE_DRIFT_MAP` and `STATE_PROPERTY_MAP` have the same length and cover the same `DriftKind` values.

---

## Issue 3.2 — `emit` closure has untyped `**kwargs`

**File:** `src/nirip/plan.py` lines 320–331
**Category:** DESIGN
**Risk:** Low — type safety improvement

### Problem

The `emit()` closure passes `**kwargs` directly to `PlanStep(...)`. Typos in field names silently pass through to Pydantic, which only catches them at validation time (raising `ValidationError` because `extra="forbid"`). This is fine in production but unhelpful during development.

### Implementation

Replace the untyped `**kwargs` with a `TypedDict` parameter or, more practically, create step-builder functions that type-check at the call site. However, the simplest fix that preserves the closure pattern is to use a dataclass-like builder:

**Option A (Recommended — minimal change):** Keep the `emit` closure but add an explicit `_StepParams` TypedDict:

```python
from typing import TypedDict, Unpack

class _StepParams(TypedDict, total=False):
    app_name: str | None
    workspace_name: str | None
    window_id: int | None
    command: list[str] | str | None
    cwd: str | None
    env: dict[str, str]
    shell: bool
    match: MatchRule | None
    timeout_s: float | None
    target_output: str | None
    property: WindowProperty | None
    value: bool
    axis: ResizeAxis | None
    proportion: float | None
    pixels: int | None
    depends_on: list[str]


def emit(kind: StepKind, description: str, **kwargs: Unpack[_StepParams]) -> str:
    nonlocal counter
    counter += 1
    sid = f"{kind.value}-{counter}"
    step = PlanStep(id=sid, kind=kind, description=description, **kwargs)
    steps.append(step)
    key = f"{step.workspace_name}/{step.app_name}" if step.app_name and step.workspace_name else None
    if key:
        if key not in app_first:
            app_first[key] = sid
        app_last[key] = sid
    return sid
```

**Note:** `Unpack[TypedDict]` for `**kwargs` is supported in Python 3.12+ (PEP 692). Since the project targets Python 3.13+, this is safe.

Also type the `emit` parameter in helper functions:

```python
from collections.abc import Callable

# Type alias for emit
type EmitFn = Callable[..., str]  # or use Protocol for stricter typing
```

For the helper function signatures (`_workspace_steps`, `_spawn_steps`, `_placement_steps`), annotate the `emit` parameter:

```python
def _workspace_steps(ws: WorkspaceState, emit: Callable[..., str]) -> list[str]:
    ...

def _spawn_steps(ar: AppResolution, ws_name: str, base_deps: list[str], emit: Callable[..., str]) -> list[str]:
    ...

def _placement_steps(ar: AppResolution, ws_name: str, deps: list[str], emit: Callable[..., str]) -> None:
    ...
```

### Tests

- No behavioral change — existing tests pass unchanged.
- Type checkers (ty/pyright) will now catch typos in `emit()` keyword arguments.

---

## Issue 3.3 — `_placement_steps` emits `MOVE_WINDOW` for `MISSING` apps with `window_id=None`

**File:** `src/nirip/plan.py` lines 168–177 and `src/nirip/execute.py` lines 237–252
**Category:** CORRECTNESS
**Risk:** Low — documenting implicit contract

### Problem

For `MISSING` apps, `ar.window_id` is `None`. The plan emits `MOVE_WINDOW` with `window_id=None`. This works only because `_resolve_wid` in the executor falls back to `apps[key].matched_window_id`, which was set by a prior `WAIT_FOR_WINDOW` step. The dependency chain is invisible.

### Implementation

**Approach:** Make the implicit contract explicit. The `window_id=None` in the plan step is *intentional* — it signals "resolve at execution time". Document this and add a runtime assertion.

**Step 1:** Add a comment in `_placement_steps`:

```python
def _placement_steps(ar: AppResolution, ws_name: str, deps: list[str], emit: Callable[..., str]) -> None:
    if ar.needs_move or ar.status == ResolutionStatus.MISSING:
        # window_id may be None for MISSING apps — the executor resolves it
        # via matched_window_id set by a prior WAIT_FOR_WINDOW step in deps.
        emit(
            StepKind.MOVE_WINDOW,
            f"move {ar.app_name} to '{ws_name}'",
            app_name=ar.app_name,
            workspace_name=ws_name,
            window_id=ar.window_id,
            depends_on=deps,
        )
    ...
```

**Step 2:** Add a guard in `build_plan` after step generation to validate that every `MOVE_WINDOW`/`SET_STATE`/`RESIZE`/`FOCUS_WINDOW` step with `window_id=None` has a `WAIT_FOR_WINDOW` step in its transitive dependency chain:

```python
# At end of build_plan, before returning:
_validate_window_id_contracts(steps)
```

```python
def _validate_window_id_contracts(steps: list[PlanStep]) -> None:
    """Assert that steps needing a window_id either have one or depend on WAIT_FOR_WINDOW."""
    needs_wid = {StepKind.MOVE_WINDOW, StepKind.SET_STATE, StepKind.RESIZE, StepKind.FOCUS_WINDOW}
    wait_steps = {s.id for s in steps if s.kind == StepKind.WAIT_FOR_WINDOW}

    if not wait_steps:
        return

    # Build transitive dependency map
    dep_map = {s.id: set(s.depends_on) for s in steps}

    def has_wait_ancestor(sid: str, visited: set[str] | None = None) -> bool:
        if visited is None:
            visited = set()
        if sid in visited:
            return False
        visited.add(sid)
        if sid in wait_steps:
            return True
        return any(has_wait_ancestor(dep, visited) for dep in dep_map.get(sid, []))

    for step in steps:
        if step.kind in needs_wid and step.window_id is None:
            if not has_wait_ancestor(step.id):
                raise NiripError(
                    f"step {step.id} ({step.kind}) has no window_id and no "
                    f"WAIT_FOR_WINDOW in its dependency chain"
                )
```

### Tests

- Add a test that a `MISSING` app with spawn produces a plan where `MOVE_WINDOW` (with `window_id=None`) transitively depends on `WAIT_FOR_WINDOW`.
- Add a negative test that constructing a plan with a null `window_id` and no `WAIT_FOR_WINDOW` ancestor raises `NiripError`.

---

## Issue 4.3 — `_NullHook` could be simpler

**File:** `src/nirip/execute.py` lines 71–87, 316
**Category:** DESIGN
**Risk:** Low — API simplification

### Problem

`_NullHook` exists as a separate class just to avoid `None` checks. The Null Object pattern is valid but verbose for a 3-method protocol.

### Implementation

**Option A (Recommended):** Make `hook` non-optional with a default factory. This eliminates `_NullHook` entirely:

```python
# Remove _NullHook class entirely.

# Change execute_plan signature:
async def execute_plan(
    plan: Plan,
    ports: SessionRuntime,
    options: SessionOptions,
    hook: ExecutionHook | None = None,
) -> ApplyResult:
    t0 = time.monotonic()

    apps: dict[str, _AppState] = {}
    for step in plan.steps:
        if step.app_name and step.workspace_name:
            key = f"{step.workspace_name}/{step.app_name}"
            if key not in apps:
                apps[key] = _AppState()

    results: list[StepResult] = []
    for step in plan.steps:
        if hook:
            hook.on_step_start(step)
        t_step = time.monotonic()
        try:
            result = await _execute_step(step, ports, apps)
        except WaitTimeoutError:
            result = StepResult(
                step=step,
                outcome=StepOutcome.TIMED_OUT,
                message="timed out waiting for condition",
                duration_s=time.monotonic() - t_step,
            )
        except (ConnectionError, OSError) as e:
            result = StepResult(
                step=step,
                outcome=StepOutcome.FAILED,
                message=f"transport error: {e}",
                duration_s=time.monotonic() - t_step,
            )

        if result.duration_s == 0.0:
            result = result.model_copy(update={"duration_s": time.monotonic() - t_step})

        if hook:
            hook.on_step_complete(step, result)
        results.append(result)
        if result.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT) and options.stop_on_error:
            break

    apply_result = ApplyResult(
        session_name=plan.session_name,
        success=all(r.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED) for r in results),
        steps=results,
        total_duration_s=time.monotonic() - t0,
    )
    if hook:
        hook.on_plan_complete(apply_result)
    return apply_result
```

This replaces `exec_hook = hook or _NullHook()` with 3 simple `if hook:` guards. The `_NullHook` class and its instantiation are deleted.

### Tests

- No behavioral change — existing tests pass unchanged.
- Tests that pass `hook=None` (the default) continue to work.

---

## Execution Order

Implement changes in this order to minimize merge conflicts and allow incremental testing:

| Step | Issue | File(s) | Depends On |
|------|-------|---------|------------|
| 1 | 1.3 | `spec.py` | — |
| 2 | 1.4 | `spec.py` | — |
| 3 | 4.3 | `execute.py` | — |
| 4 | 2.5 | `resolve.py` | — |
| 5 | 2.6 | `resolve.py`, `plan.py` | Step 4 |
| 6 | 3.2 | `plan.py` | Step 5 |
| 7 | 3.3 | `plan.py` | Step 6 |

Steps 1–4 are independent and can be done in parallel.
Steps 5–7 are sequential within `plan.py`/`resolve.py`.
Steps 3.5 and 4.8 require no code changes.

---

## Validation Checklist

After all changes:

- [ ] `devenv shell -- pytest` — all tests pass
- [ ] `devenv shell -- ruff check src/` — no lint errors
- [ ] `devenv shell -- ty check src/nirip/` — no type errors
- [ ] Verify `_check_weak_matchers` now warns on `title`-only matchers
- [ ] Verify `_check_inter_app_conflicts` uses uniform string sentinels
- [ ] Verify `Workspace` import removed from `resolve.py`, replaced by `WorkspaceLike` protocol
- [ ] Verify `_PROPERTY_CHECKS` renamed to `STATE_PROPERTY_MAP` and shared with `plan.py`
- [ ] Verify `emit()` has typed `**kwargs` via `Unpack[_StepParams]`
- [ ] Verify `_validate_window_id_contracts` catches missing WAIT_FOR_WINDOW ancestors
- [ ] Verify `_NullHook` class is deleted, replaced by `if hook:` guards
