# Refactoring Guide: nirip Post-Review

**Source**: `FINAL_REVIEW.md` from project 012 (commit `b31b18f`)
**Scope**: H3, M1-M7, L1-L8, plus 4 architectural refactoring suggestions

---

## Table of Contents

1. [H3: `apply_session()` Missing `config` Parameter](#h3-apply_session-missing-config-parameter)
2. [M1: Duplicate `_STATE_CHECKS` Definition](#m1-duplicate-_state_checks-definition)
3. [M2: `use_enum_values=True` Footgun](#m2-use_enum_values-footgun)
4. [M3: Missing Timeout on Spawned Process Lifecycle](#m3-missing-timeout-on-spawned-process-lifecycle)
5. [M4: `_detect_drift()` Inconsistent Maximized Handling](#m4-_detect_drift-inconsistent-maximized-handling)
6. [M5: Redundant State Steps for Newly-Spawned Windows](#m5-redundant-state-steps-for-newly-spawned-windows)
7. [M6: `_parse_size()` Exported via Test Import](#m6-_parse_size-exported-via-test-import)
8. [M7: No Validation of `ResizeWindowStep` Invariant](#m7-no-validation-of-resizewindowstep-invariant)
9. [L1: `FakeSnapshot` Doesn't Enforce Protocol](#l1-fakesnapshot-doesnt-enforce-protocol)
10. [L2: `compile_diff()` Doesn't Report `OPTIONAL_MISSING`](#l2-compile_diff-doesnt-report-optional_missing)
11. [L3: Redundant `workspace_name`/`target_workspace` on `MoveWindowToWorkspaceStep`](#l3-redundant-workspace_nametarget_workspace)
12. [L4: `evaluate_rule()` Regex Compilation on Every Call](#l4-evaluate_rule-regex-compilation-on-every-call)
13. [L5: `AsyncNirip.open()` Double-Ceremony Pattern](#l5-asyncniripopen-double-ceremony-pattern)
14. [L6: `model_copy()` Allocations in `apply_defaults()`](#l6-model_copy-allocations-in-apply_defaults)
15. [L7: CLI `main()` Catches All Exceptions](#l7-cli-main-catches-all-exceptions)
16. [L8: Missing `__all__` in Subpackage `__init__.py` Files](#l8-missing-__all__-in-subpackage-__init__py-files)
17. [R1: Extract `WindowAssigner` Protocol](#r1-extract-windowassigner-protocol)
18. [R2: Step Builder Pattern for `compile_plan()`](#r2-step-builder-pattern-for-compile_plan)
19. [R3: Structured Logging in Executor](#r3-structured-logging-in-executor)
20. [R4: Deferred Defaults in `apply_defaults()`](#r4-deferred-defaults-in-apply_defaults)

---

## H3: `apply_session()` Missing `config` Parameter

**File**: `src/nirip/__init__.py:38-43`
**Severity**: High
**Risk**: Low — additive change, backwards-compatible via default argument

### Problem

`apply_session()` hardcodes `AsyncNirip.open()` with no config, while `plan_session()` and `diff_session()` both accept `config: NiripConfig | None = None`. Users needing custom timeouts or socket paths cannot use `apply_session()`.

### Current Code

```python
def apply_session(spec: SessionSpec) -> ApplyResult:
    async def _run() -> ApplyResult:
        async with await AsyncNirip.open() as nirip:
            return await nirip.apply(spec)
    return asyncio.run(_run())
```

### Target Code

```python
def apply_session(spec: SessionSpec, config: NiripConfig | None = None) -> ApplyResult:
    async def _run() -> ApplyResult:
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.apply(spec)
    return asyncio.run(_run())
```

### Steps

1. Edit `src/nirip/__init__.py:38` — add `config: NiripConfig | None = None` parameter
2. Edit `src/nirip/__init__.py:40` — pass `config` to `AsyncNirip.open(config)`
3. Verify existing tests still pass (no tests call `apply_session()` directly, so this is purely additive)

### Validation

- `rg 'apply_session' tests/` — confirm no tests need updating
- Type-check passes with `mypy` or `pyright`

---

## M1: Duplicate `_STATE_CHECKS` Definition

**Files**: `src/nirip/execution/handlers.py:50-55` and `src/nirip/execution/predicates.py:15-20`
**Severity**: Medium
**Risk**: Low — extracting shared constant

### Problem

The same `_STATE_CHECKS` lambda dictionary is defined independently in both modules. If one is updated and the other isn't, behavior silently diverges.

### Current State

Both files define identical dictionaries:

```python
_STATE_CHECKS = {
    WindowProperty.FLOATING: lambda w: w.is_floating,
    WindowProperty.TILING: lambda w: not w.is_floating,
    WindowProperty.FULLSCREEN: lambda w: getattr(w, "is_fullscreen", False),
    WindowProperty.MAXIMIZED: lambda w: getattr(w, "is_maximized", False),
}
```

### Target

Extract to a shared location. Best candidate: `src/nirip/planning/models.py` alongside the `WindowProperty` enum, or a new `src/nirip/execution/_checks.py`.

Since `_STATE_CHECKS` depends on `WindowProperty` (defined in `planning/models.py`) and is consumed by `execution/`, placing it in `execution/` avoids a cross-layer dependency from planning→execution. A small private module is cleanest.

### Steps

1. **Create** `src/nirip/execution/_checks.py`:

```python
"""Shared window-property check predicates."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nirip.planning.models import WindowProperty

STATE_CHECKS: dict[WindowProperty, Callable[[Any], bool]] = {
    WindowProperty.FLOATING: lambda w: w.is_floating,
    WindowProperty.TILING: lambda w: not w.is_floating,
    WindowProperty.FULLSCREEN: lambda w: getattr(w, "is_fullscreen", False),
    WindowProperty.MAXIMIZED: lambda w: getattr(w, "is_maximized", False),
}
```

2. **Edit** `src/nirip/execution/handlers.py`:
   - Remove `_STATE_CHECKS` definition (lines 50-55)
   - Add import: `from nirip.execution._checks import STATE_CHECKS`
   - Replace `_STATE_CHECKS[step.property]` with `STATE_CHECKS[step.property]` on lines 153, 158

3. **Edit** `src/nirip/execution/predicates.py`:
   - Remove `_STATE_CHECKS` definition (lines 15-20)
   - Add import: `from nirip.execution._checks import STATE_CHECKS`
   - Replace `_STATE_CHECKS[step.property]` with `STATE_CHECKS[step.property]` on line 41

### Validation

- All existing tests pass unchanged
- `rg '_STATE_CHECKS' src/` returns zero hits (only `STATE_CHECKS` remains)

---

## M2: `use_enum_values=True` Footgun

**File**: `src/nirip/_base.py:17`
**Severity**: Medium
**Risk**: Medium — touches the base model config, affects all models

### Problem

`use_enum_values=True` in `NiripModel` means enum fields store their `.value` (string/int) after instantiation, not the enum instance. This forces explicit re-wrapping (`MatchTier(c.tier)`) every time a tier is accessed from a model:

- `src/nirip/resolve/matcher.py:101` — `MatchTier(c.tier)` in triples construction
- `src/nirip/resolve/matcher.py:123` — `MatchTier(c.tier)` in decision building
- `src/nirip/resolve/models.py:42` — `MatchTier(c.tier)` in `is_ambiguous` computed field

### Current Code (`_base.py`)

```python
model_config = ConfigDict(
    extra="forbid",
    frozen=True,
    use_enum_values=True,
)
```

### Target Code

```python
model_config = ConfigDict(
    extra="forbid",
    frozen=True,
)
```

Remove `use_enum_values=True` entirely. Pydantic v2 handles enum serialization correctly by default — enums serialize to their values in JSON output but remain enum instances in Python.

### Steps

1. **Edit** `src/nirip/_base.py:15-19` — remove `use_enum_values=True` from `ConfigDict`

2. **Edit** `src/nirip/resolve/matcher.py` — remove all `MatchTier()` re-wrapping:
   - Line 101: `triples.append((app_idx, c.window_id, MatchTier(c.tier)))` → `triples.append((app_idx, c.window_id, c.tier))`
   - Line 123: `tier = next(MatchTier(c.tier) for c in candidates if c.window_id == wid)` → `tier = next(c.tier for c in candidates if c.window_id == wid)`

3. **Edit** `src/nirip/resolve/models.py:42` — remove `MatchTier()` re-wrapping:
   - `tiers = [MatchTier(c.tier) for c in self.candidates]` → `tiers = [c.tier for c in self.candidates]`

4. **Run full test suite** — any test that compares `.tier` values against strings (e.g., `assert decision.tier == "exact"`) will now need to compare against `MatchTier.EXACT` instead.

5. **Search for other enum comparisons** that may break:
   ```
   rg '\.status ==' tests/
   rg '\.tier ==' tests/
   rg '\.kind ==' tests/
   rg '\.outcome ==' tests/
   ```
   Update any string-based comparisons to use enum members.

### Risk Mitigation

- This is a behavioral change for serialization consumers. Run `model_dump()` / `model_dump_json()` checks on key models to confirm JSON output still uses string values (Pydantic v2 does this by default).
- If any external consumer relies on `resolution.workspace_resolutions[0].app_resolutions[0].status` being a raw string, they'll now get a `ResolutionStatus` instance. Since `StrEnum` inherits from `str`, equality with string literals still works (`ResolutionStatus.MATCHED == "matched"` is `True`).

### Validation

- Full test suite passes
- `model_dump_json()` still produces string values for enums (verify with a quick script)
- No remaining `MatchTier(c.tier)` or similar casts in source

---

## M3: Missing Timeout on Spawned Process Lifecycle

**File**: `src/nirip/execution/handlers.py:91-102`
**Severity**: Medium
**Risk**: Low — additive behavior, no API change

### Problem

`SpawnWindowStep` creates a subprocess but doesn't track the `Process` object beyond recording the PID. If the process crashes immediately, `WaitForWindowStep` will wait the full `timeout_s` before timing out, with no indication that the process already exited.

### Current Code

```python
case SpawnWindowStep():
    # ... creates proc ...
    if step.app_name and step.app_name in runtime.apps:
        app_state = runtime.apps[step.app_name]
        app_state.spawned = True
        app_state.spawn_pid = proc.pid
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="spawned", spawn_pid=proc.pid)
```

### Target

1. Store the `asyncio.subprocess.Process` object in `AppRuntimeState`
2. In the `WaitForWindowStep` handler, race `process.wait()` against the window predicate
3. Fail fast with a clear message if the process exits before the window appears

### Steps

1. **Edit** `src/nirip/execution/runtime.py` — add process field to `AppRuntimeState`:

```python
from asyncio.subprocess import Process as AsyncProcess

class AppRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, arbitrary_types_allowed=True)

    app_name: str
    workspace_name: str
    matched_window_id: int | None = None
    spawned: bool = False
    spawn_pid: int | None = None
    spawn_process: AsyncProcess | None = None  # NEW
    completed: bool = False
    error: str | None = None
```

2. **Edit** `src/nirip/execution/handlers.py` — store process in `SpawnWindowStep` handler:

```python
case SpawnWindowStep():
    # ... existing subprocess creation ...
    if step.app_name and step.app_name in runtime.apps:
        app_state = runtime.apps[step.app_name]
        app_state.spawned = True
        app_state.spawn_pid = proc.pid
        app_state.spawn_process = proc  # NEW
    return StepResult(...)
```

3. **Edit** `src/nirip/execution/handlers.py` — add process-exit racing in `WaitForWindowStep` handler:

```python
case WaitForWindowStep():
    matched_wid: int | None = None

    def predicate(snap: Any) -> bool:
        nonlocal matched_wid
        for w in snap.windows.values():
            matched, _, _ = evaluate_rule(step.match, w)
            if matched:
                matched_wid = w.id
                return True
        return False

    # Race process exit against window appearance
    proc: AsyncProcess | None = None
    if step.app_name and step.app_name in runtime.apps:
        proc = runtime.apps[step.app_name].spawn_process

    if proc is not None:
        wait_task = asyncio.create_task(_wait(ports.state, predicate, step.timeout_s))
        exit_task = asyncio.create_task(proc.wait())
        done, pending = await asyncio.wait(
            {wait_task, exit_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()

        if exit_task in done and wait_task not in done:
            rc = exit_task.result()
            return StepResult(
                step=step,
                outcome=StepOutcome.FAILED,
                message=f"process exited with code {rc} before window appeared",
            )
        # If wait_task completed (even if exit_task also did), window was found
        if wait_task in done:
            wait_task.result()  # re-raise if it errored
    else:
        await _wait(ports.state, predicate, step.timeout_s)

    if step.app_name and step.app_name in runtime.apps:
        runtime.apps[step.app_name].matched_window_id = matched_wid
    return StepResult(
        step=step,
        outcome=StepOutcome.COMPLETED,
        message=f"window appeared (id={matched_wid})",
        window_id=matched_wid,
    )
```

### Validation

- Existing `WaitForWindowStep` tests still pass (when no process is stored, falls through to original path)
- Add a test that mocks a process that exits immediately and verify `FAILED` outcome

---

## M4: `_detect_drift()` Inconsistent Maximized Handling

**File**: `src/nirip/resolve/resolver.py:91-129`
**Severity**: Medium
**Risk**: Low — unifying existing logic

### Problem

`_PROPERTY_CHECKS` handles `is_floating` and `is_fullscreen` via a loop, but `is_maximized` is handled separately with an explicit `hasattr` check. This asymmetry is confusing:
- If `is_maximized` needs `hasattr`, then `is_fullscreen` might too
- If `is_fullscreen` doesn't need it, the `is_maximized` `hasattr` is dead logic

### Current Code

```python
_PROPERTY_CHECKS: list[tuple[DriftKind, str, str]] = [
    (DriftKind.WRONG_FLOATING, "is_floating", "floating"),
    (DriftKind.WRONG_FULLSCREEN, "is_fullscreen", "fullscreen"),
]

def _detect_drift(...) -> list[DriftItem]:
    # ... workspace drift check ...

    for kind, win_attr, place_attr in _PROPERTY_CHECKS:
        current_val: Any = getattr(window, win_attr, False)
        desired_val: Any = getattr(app_spec.placement, place_attr)
        if current_val != desired_val:
            drift.append(DriftItem(kind=kind, current=str(current_val), desired=str(desired_val)))

    if hasattr(window, "is_maximized"):
        if window.is_maximized != app_spec.placement.maximized:
            drift.append(...)
```

### Target Code

Unify all three properties into `_PROPERTY_CHECKS`. Use `getattr(window, attr, False)` uniformly — this already handles the case where the attribute doesn't exist, making the separate `hasattr` check redundant.

```python
_PROPERTY_CHECKS: list[tuple[DriftKind, str, str]] = [
    (DriftKind.WRONG_FLOATING, "is_floating", "floating"),
    (DriftKind.WRONG_FULLSCREEN, "is_fullscreen", "fullscreen"),
    (DriftKind.WRONG_MAXIMIZED, "is_maximized", "maximized"),
]
```

### Steps

1. **Edit** `src/nirip/resolve/resolver.py:91-94` — add maximized to `_PROPERTY_CHECKS`:
   ```python
   _PROPERTY_CHECKS: list[tuple[DriftKind, str, str]] = [
       (DriftKind.WRONG_FLOATING, "is_floating", "floating"),
       (DriftKind.WRONG_FULLSCREEN, "is_fullscreen", "fullscreen"),
       (DriftKind.WRONG_MAXIMIZED, "is_maximized", "maximized"),
   ]
   ```

2. **Edit** `src/nirip/resolve/resolver.py:121-129` — remove the separate `is_maximized` block entirely.

### Validation

- Existing drift detection tests pass unchanged (the behavior is identical since `getattr(window, "is_maximized", False)` is equivalent to the `hasattr` guard)

---

## M5: Redundant State Steps for Newly-Spawned Windows

**File**: `src/nirip/planning/compiler.py:130-173`
**Severity**: Medium
**Risk**: Low — reduces no-op steps from plan output

### Problem

When a window is `MISSING` (will be spawned), the compiler unconditionally emits `SetWindowStateStep` for floating/tiling, fullscreen, and maximized — even when the defaults match (tiling=True, fullscreen=False, maximized=False). The `is_already_satisfied` predicate skips them at runtime, but it adds noise to `nirip plan` output.

### Current Code

```python
if ar.status == ResolutionStatus.MISSING or any(d.kind == DriftKind.WRONG_FULLSCREEN ...):
    steps.append(SetWindowStateStep(..., property=WindowProperty.FULLSCREEN, value=ar.spec.placement.fullscreen))
```

For MISSING apps, this always emits the step even when `fullscreen=False` (the default).

### Target

Only emit state steps for newly-spawned windows when the desired state differs from defaults.

### Steps

1. **Edit** `src/nirip/planning/compiler.py` — wrap MISSING-status state steps in default checks:

For the floating/tiling block (lines 131-146):
```python
needs_float_or_tile_correction = any(
    d.kind == DriftKind.WRONG_FLOATING for d in ar.drift
)
if not needs_float_or_tile_correction and ar.status == ResolutionStatus.MISSING:
    # Only emit for newly-spawned if non-default placement
    needs_float_or_tile_correction = ar.spec.placement.floating  # default is False (tiling)
if needs_float_or_tile_correction:
    # ... existing step creation ...
```

For fullscreen (lines 148-160):
```python
needs_fullscreen = any(d.kind == DriftKind.WRONG_FULLSCREEN for d in ar.drift)
if not needs_fullscreen and ar.status == ResolutionStatus.MISSING:
    needs_fullscreen = ar.spec.placement.fullscreen  # only if non-default
if needs_fullscreen:
    # ... existing step creation ...
```

For maximized (lines 162-174):
```python
needs_maximized = any(d.kind == DriftKind.WRONG_MAXIMIZED for d in ar.drift)
if not needs_maximized and ar.status == ResolutionStatus.MISSING:
    needs_maximized = ar.spec.placement.maximized  # only if non-default
if needs_maximized:
    # ... existing step creation ...
```

### Validation

- `nirip plan` output for a basic spec with default placements should produce fewer steps
- Existing tests that check step counts may need updating
- Add a test: compile_plan with MISSING app, default placement → no SetWindowStateStep emitted
- Add a test: compile_plan with MISSING app, `floating: true` → SetWindowStateStep for FLOATING emitted

---

## M6: `_parse_size()` Exported via Test Import

**File**: `tests/test_compiler.py:7`
**Severity**: Medium
**Risk**: Low — rename or test indirectly

### Problem

Tests import `_parse_size` (a private function) directly from `compiler.py`. This couples tests to implementation and prevents refactoring.

### Options

**Option A (preferred)**: Make it public — `parse_size` — since it's a pure utility with well-defined behavior.

**Option B**: Test it indirectly through `compile_plan()` with specs that use size values.

### Steps (Option A)

1. **Edit** `src/nirip/planning/compiler.py:265` — rename `_parse_size` to `parse_size`
2. **Edit** `src/nirip/planning/compiler.py` — update the two internal call sites (lines 177, 193) from `_parse_size` to `parse_size`
3. **Edit** `tests/test_compiler.py:7` — update import from `_parse_size` to `parse_size`
4. **Optionally** add `parse_size` to `src/nirip/planning/__init__.py` exports

### Validation

- `rg '_parse_size' src/ tests/` returns zero hits
- All tests pass

---

## M7: No Validation of `ResizeWindowStep` Invariant

**File**: `src/nirip/planning/models.py:72-77`
**Severity**: Medium
**Risk**: Low — adding a validator to a frozen model

### Problem

`ResizeWindowStep` has `proportion: float | None` and `pixels: int | None`. Exactly one should be set, but there's no validation. A step with both `None` would silently pass to the handler where `actions.size_set_fixed(0)` would be called — setting a 0-pixel width.

### Current Code

```python
class ResizeWindowStep(StepBase):
    kind: Literal["resize_window"] = "resize_window"
    window_id: int | None = None
    axis: ResizeAxis
    proportion: float | None = None
    pixels: int | None = None
```

### Target Code

```python
from pydantic import model_validator

class ResizeWindowStep(StepBase):
    kind: Literal["resize_window"] = "resize_window"
    window_id: int | None = None
    axis: ResizeAxis
    proportion: float | None = None
    pixels: int | None = None

    @model_validator(mode="after")
    def _exactly_one_size(self) -> ResizeWindowStep:
        has_prop = self.proportion is not None
        has_px = self.pixels is not None
        if has_prop == has_px:
            raise ValueError("exactly one of 'proportion' or 'pixels' must be set")
        return self
```

### Steps

1. **Edit** `src/nirip/planning/models.py` — add `model_validator` to imports (already imported for other models)
2. **Edit** `src/nirip/planning/models.py:72-77` — add the `_exactly_one_size` validator
3. **Check** `compiler.py` — verify `_parse_size()` always returns exactly one of the pair (it does: returns `(float, None)` or `(None, int)`)
4. **Check** tests — any test constructing `ResizeWindowStep` with both `None` will fail and needs fixing

### Validation

- Construct `ResizeWindowStep(axis=ResizeAxis.WIDTH)` → raises `ValueError`
- Construct `ResizeWindowStep(axis=ResizeAxis.WIDTH, proportion=0.5, pixels=100)` → raises `ValueError`
- Existing tests pass

---

## L1: `FakeSnapshot` Doesn't Enforce Protocol

**File**: `tests/conftest.py`
**Severity**: Low
**Risk**: Low — test-only change

### Problem

Test fakes (`FakeWindow`, `FakeWorkspace`, `FakeSnapshot`) are plain dataclasses that happen to match attribute names. If the real types add a required attribute, fakes silently pass — hiding real breakage.

### Target

Add `typing.runtime_checkable` protocol assertions.

### Steps

1. **Edit** `tests/conftest.py` — add runtime assertions after class definitions:

```python
from typing import Protocol, runtime_checkable
from niri_state import Snapshot

# After FakeSnapshot definition:
# Structural compatibility check — fails at import time if protocol diverges
def _assert_structural_compat() -> None:
    """Verify fakes match the real types structurally."""
    snap = FakeSnapshot()
    # These attribute accesses will raise AttributeError at import time
    # if FakeSnapshot falls behind the real Snapshot interface
    _ = snap.windows
    _ = snap.workspaces
    _ = snap.outputs

_assert_structural_compat()
```

Alternatively, if `niri_state.Snapshot` is a `Protocol` or has clear required attributes, use `isinstance` with `runtime_checkable`:

```python
# If Snapshot is runtime_checkable:
assert isinstance(FakeSnapshot(), Snapshot), "FakeSnapshot does not satisfy Snapshot protocol"
```

### Validation

- Tests still import cleanly
- If `Snapshot` adds a new required attribute, tests fail at import time with a clear error

---

## L2: `compile_diff()` Doesn't Report `OPTIONAL_MISSING`

**File**: `src/nirip/planning/compiler.py:281-307`
**Severity**: Low
**Risk**: Low — additive output change

### Problem

Apps with `ResolutionStatus.OPTIONAL_MISSING` fall through all branches in `compile_diff()` and are silently omitted from the diff. Users get no feedback about optional apps that could be started.

### Target

Add an `optional_missing` field to `SessionDiff` and populate it.

### Steps

1. **Edit** `src/nirip/planning/models.py` — add field to `SessionDiff`:

```python
class SessionDiff(NiripModel):
    session_name: str
    already_matched: list[str] = Field(default_factory=list)
    will_spawn: list[str] = Field(default_factory=list)
    will_move: list[str] = Field(default_factory=list)
    drifted: list[str] = Field(default_factory=list)
    optional_missing: list[str] = Field(default_factory=list)  # NEW
    workspace_changes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
```

2. **Edit** `src/nirip/planning/compiler.py:294-306` — add the OPTIONAL_MISSING case:

```python
for ar in wr.app_resolutions:
    label = f"{wr.name}/{ar.app_name}"
    if ar.status == ResolutionStatus.MATCHED:
        diff.already_matched.append(label)
    elif ar.status == ResolutionStatus.OPTIONAL_MISSING:
        diff.optional_missing.append(label)
    elif ar.status == ResolutionStatus.MISSING:
        diff.will_spawn.append(label)
    # ... rest unchanged ...
```

3. **Edit** `src/nirip/cli/formatting.py` — add optional_missing to `format_diff()`:

```python
if diff.optional_missing:
    lines.append(f"Optional (not running): {len(diff.optional_missing)}")
    for app in diff.optional_missing:
        lines.append(f"  ? {app}")
```

### Validation

- Create a test spec with an optional app that's not running, run `compile_diff()`, verify `optional_missing` contains it

---

## L3: Redundant `workspace_name`/`target_workspace`

**File**: `src/nirip/planning/models.py:47-50`, `src/nirip/planning/compiler.py:120,125`
**Severity**: Low
**Risk**: Low — but touches handler code

### Problem

`MoveWindowToWorkspaceStep` has both `workspace_name` (from `StepBase`, used for dependency tracking) and `target_workspace` (the actual move target). In compiler.py, they're always set to the same value, making one redundant.

### Options

**Option A**: Drop `target_workspace`, use `workspace_name` as the move target in handlers.
**Option B**: Keep both, document the distinction (if workspace_name might differ in future).

### Steps (Option A — recommended)

1. **Edit** `src/nirip/planning/models.py:47-50` — remove `target_workspace` field:

```python
class MoveWindowToWorkspaceStep(StepBase):
    kind: Literal["move_window_to_workspace"] = "move_window_to_workspace"
    window_id: int | None = None
    # target workspace is workspace_name from StepBase
```

2. **Edit** `src/nirip/planning/compiler.py:118-129` — remove `target_workspace=wr.name` from constructor call

3. **Edit** `src/nirip/execution/handlers.py:124-147` — replace `step.target_workspace` with `step.workspace_name`:

```python
case MoveWindowToWorkspaceStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    wid_int = wid
    target_workspace = step.workspace_name  # was step.target_workspace
    workspace_ref = actions.workspace_by_name(step.workspace_name or "")  # was step.target_workspace
    # ... rest uses target_workspace local var, unchanged ...
```

4. **Edit** `src/nirip/execution/predicates.py:27-34` — replace `step.target_workspace` with `step.workspace_name`

5. **Search** for any other references: `rg 'target_workspace' src/ tests/`

### Validation

- All tests pass
- `rg 'target_workspace' src/` returns zero hits

---

## L4: `evaluate_rule()` Regex Compilation on Every Call

**File**: `src/nirip/resolve/matcher.py:29,47`
**Severity**: Low
**Risk**: Low — performance optimization

### Problem

`re.search(rule.app_id_regex, ...)` and `re.search(rule.title_regex, ...)` compile regex patterns on every invocation. Python's internal `re` cache (512 patterns) makes this fine for typical use, but pre-compilation is cleaner.

### Options

**Option A (minimal)**: Add `@functools.lru_cache` on a helper or use `re.compile()` in the MatchRule model validator.

**Option B (clean)**: Add compiled regex as a private cached property on `MatchRule`.

### Steps (Option A — MatchRule validator)

Since `MatchRule` is frozen, we can compile at construction time. However, `MatchRule` is in `spec/models.py` and we don't want `re.Pattern` stored on a Pydantic model (serialization issues). Instead, use a module-level cache.

1. **Edit** `src/nirip/resolve/matcher.py` — add a compile cache:

```python
import functools

@functools.lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)
```

2. **Edit** the `evaluate_rule` function — replace `re.search(pattern, text)` with `_compile(pattern).search(text)`:
   - Line 29: `_compile(rule.app_id_regex).search(window.app_id)`
   - Line 45: `_compile(rule.title_regex).search(window.title)`

### Validation

- All matcher tests pass
- Performance improvement measurable only at scale (>50 apps × >50 windows)

---

## L5: `AsyncNirip.open()` Double-Ceremony Pattern

**File**: `src/nirip/facade/async_nirip.py:29-32`
**Severity**: Low
**Risk**: Medium — API change

### Problem

`async with await AsyncNirip.open() as nirip:` requires both `await` and `async with`, which is unusual. Most async context manager patterns use one or the other.

### Target

Make `open()` return an async context manager directly so usage becomes:
```python
async with AsyncNirip.open() as nirip:
    ...
```

### Steps

1. **Edit** `src/nirip/facade/async_nirip.py` — convert `open()` to return an async context manager:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

class AsyncNirip:
    # ... existing __init__, properties, methods ...

    @classmethod
    @asynccontextmanager
    async def open(cls, config: NiripConfig | None = None) -> AsyncIterator[AsyncNirip]:
        state = await NiriState.open()
        client = NiriClient.create()
        instance = cls(state=state, client=client, config=config)
        try:
            yield instance
        finally:
            await instance.close()
```

2. **Edit** `src/nirip/__init__.py` — update all sync convenience functions to remove the `await`:

```python
def apply_session(spec: SessionSpec, config: NiripConfig | None = None) -> ApplyResult:
    async def _run() -> ApplyResult:
        async with AsyncNirip.open(config) as nirip:  # no await
            return await nirip.apply(spec)
    return asyncio.run(_run())
```

Same for `plan_session()` and `diff_session()`.

3. **Edit** `src/nirip/cli/commands.py` — update any `await AsyncNirip.open()` calls

4. **Search**: `rg 'await AsyncNirip.open' src/ tests/` — update all call sites

### Validation

- All tests pass
- Verify `async with AsyncNirip.open() as nirip:` works (no `await`)
- Verify cleanup still runs on exception

---

## L6: `model_copy()` Allocations in `apply_defaults()`

**File**: `src/nirip/spec/defaults.py:12-19`
**Severity**: Low
**Risk**: Low — no change recommended for current scale

### Problem

`apply_defaults()` creates O(workspaces x apps) frozen model copies. This is fine at current scale (~20 apps max).

### Recommendation

**No action needed now.** Document the scaling concern with a brief comment.

### Steps

1. **Edit** `src/nirip/spec/defaults.py` — add a comment:

```python
def apply_defaults(spec: SessionSpec) -> SessionSpec:
    """Return new SessionSpec with defaults applied to all apps.

    Note: Creates O(workspaces * apps) frozen copies. Fine at current scale
    but would need rethinking for multi-session orchestration.
    """
```

---

## L7: CLI `main()` Catches All Exceptions

**File**: `src/nirip/cli/main.py:54`
**Severity**: Low
**Risk**: Low — additive flag

### Problem

`except Exception as e:` swallows tracebacks for unexpected errors, making debugging difficult.

### Target

Add a `--verbose` / `--traceback` flag that re-raises or prints the full traceback.

### Steps

1. **Edit** `src/nirip/cli/main.py` — add `--verbose` flag to the parser:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nirip", description="Niri session manager")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show full traceback on error")
    # ... subparsers unchanged ...
```

2. **Edit** `src/nirip/cli/main.py:42-56` — use verbose flag:

```python
try:
    # ... existing command dispatch ...
except Exception as e:
    if args.verbose:
        import traceback
        traceback.print_exc(file=sys.stderr)
    else:
        print(f"error: {e}", file=sys.stderr)
    return 1
```

### Validation

- `nirip --verbose apply bad_file.yaml` shows full traceback
- `nirip apply bad_file.yaml` shows concise error (existing behavior)

---

## L8: Missing `__all__` in Subpackage `__init__.py` Files

**File**: All subpackage `__init__.py` files
**Severity**: Low

### Status: ALREADY RESOLVED

All subpackage `__init__.py` files already define `__all__`:

- `spec/__init__.py` — has `__all__`
- `resolve/__init__.py` — has `__all__`
- `planning/__init__.py` — has `__all__`
- `execution/__init__.py` — has `__all__`
- `capture/__init__.py` — has `__all__`
- `cli/__init__.py` — has `__all__`
- `facade/__init__.py` — has `__all__`

**No action needed.** This was likely fixed during or after the review.

---

## R1: Extract `WindowAssigner` Protocol

**File**: `src/nirip/resolve/matcher.py:85-141`
**Severity**: Architectural improvement
**Risk**: Medium — introduces new abstraction layer

### Problem

The greedy assignment algorithm in `assign_windows()` is hardcoded. The review noted (H2) that this greedy approach isn't optimal — it can produce suboptimal 1:1 assignments when apps compete for windows. Making the assigner pluggable enables swapping in an optimal algorithm later.

### Design

```
resolve/
├── matcher.py          # evaluate_rule() stays here
├── models.py           # existing models + WindowAssigner protocol
├── assigner.py         # NEW: assignment implementations
└── resolver.py         # uses WindowAssigner via dependency injection
```

### Steps

1. **Edit** `src/nirip/resolve/models.py` — add the protocol:

```python
from typing import Protocol

class WindowAssigner(Protocol):
    """Strategy for 1:1 app-to-window assignment."""

    def assign(
        self,
        apps: list[tuple[str, AppSpec]],
        candidates: list[list[MatchCandidate]],
    ) -> dict[int, int]:
        """Return mapping of app_index -> window_id."""
        ...
```

2. **Create** `src/nirip/resolve/assigner.py`:

```python
"""Window assignment strategies."""

from __future__ import annotations

from nirip.resolve.models import MatchCandidate, MatchTier


class GreedyAssigner:
    """Greedy assignment: highest-tier-first, first-come-first-served.

    Fast but not guaranteed optimal for competing assignments.
    """

    def assign(
        self,
        apps: list[tuple[str, object]],
        candidates: list[list[MatchCandidate]],
    ) -> dict[int, int]:
        triples: list[tuple[int, int, MatchTier]] = []
        for app_idx, app_candidates in enumerate(candidates):
            for c in app_candidates:
                triples.append((app_idx, c.window_id, c.tier))
        triples.sort(key=lambda t: t[2], reverse=True)

        assigned_app: set[int] = set()
        assigned_window: set[int] = set()
        result: dict[int, int] = {}

        for app_idx, window_id, _tier in triples:
            if app_idx in assigned_app or window_id in assigned_window:
                continue
            result[app_idx] = window_id
            assigned_app.add(app_idx)
            assigned_window.add(window_id)

        return result
```

3. **Edit** `src/nirip/resolve/matcher.py` — refactor `assign_windows()` to accept an assigner:

```python
from nirip.resolve.assigner import GreedyAssigner
from nirip.resolve.models import WindowAssigner

_DEFAULT_ASSIGNER = GreedyAssigner()

def assign_windows(
    apps: list[tuple[str, AppSpec]],
    windows: Iterable[Window],
    assigner: WindowAssigner = _DEFAULT_ASSIGNER,
) -> list[MatchDecision]:
    window_list = list(windows)

    all_candidates: list[list[MatchCandidate]] = []
    for _ws_name, app_spec in apps:
        candidates = []
        for w in window_list:
            matched, tier, reasons = evaluate_rule(app_spec.match, w)
            if matched:
                candidates.append(MatchCandidate(window_id=w.id, tier=tier, reasons=reasons))
        all_candidates.append(candidates)

    app_to_window = assigner.assign(apps, all_candidates)

    # ... build decisions from app_to_window (same as current lines 115-141) ...
```

4. **Edit** `src/nirip/resolve/__init__.py` — export the protocol and default assigner:

```python
__all__ = ["resolve", "Resolution", "GreedyAssigner", "WindowAssigner"]
```

### Future: Optimal Assigner

When needed, add a `HungarianAssigner` that uses `scipy.optimize.linear_sum_assignment` or a pure-Python implementation for optimal bipartite matching. It would implement the same `WindowAssigner` protocol and could be passed via config.

### Validation

- All existing tests pass unchanged (default assigner is `GreedyAssigner`, same behavior)
- Add a test for the protocol: `GreedyAssigner().assign(...)` with the edge case from H2

---

## R2: Step Builder Pattern for `compile_plan()`

**File**: `src/nirip/planning/compiler.py:48-262`
**Severity**: Architectural improvement
**Risk**: Medium — significant refactor of the longest function

### Problem

`compile_plan()` is 215 lines with interleaved step creation and dependency wiring. A builder pattern would separate concerns and make each step type independently testable.

### Design

```python
class PlanBuilder:
    """Builds plan steps with automatic ID generation and dependency tracking."""

    def __init__(self) -> None:
        self._steps: list[PlanStep] = []
        self._counter = 0
        self._app_first: dict[str, str] = {}
        self._app_last: dict[str, str] = {}

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def _track(self, step: PlanStep) -> None:
        self._steps.append(step)
        if step.app_name and step.workspace_name:
            key = f"{step.workspace_name}/{step.app_name}"
            if key not in self._app_first:
                self._app_first[key] = step.id
            self._app_last[key] = step.id

    def ensure_workspace(self, wr: WorkspaceResolution) -> str | None:
        """Emit workspace creation/move step. Returns step ID or None."""
        if not wr.exists:
            sid = self._next_id("create-ws")
            self._track(CreateWorkspaceStep(
                id=sid,
                description=f"create workspace '{wr.name}'",
                workspace_name=wr.name,
                target_output=wr.desired_output,
            ))
            return sid
        elif not wr.output_correct and wr.desired_output:
            sid = self._next_id("move-ws")
            self._track(MoveWorkspaceToOutputStep(
                id=sid,
                description=f"move workspace '{wr.name}' to {wr.desired_output}",
                workspace_name=wr.name,
                target_output=wr.desired_output,
            ))
            return sid
        return None

    def spawn_app(self, ar: AppResolution, ws_name: str, base_deps: list[str]) -> list[str]:
        """Emit spawn + wait steps. Returns deps for subsequent placement steps."""
        spawn_id = self._next_id("spawn")
        wait_id = self._next_id("wait")
        self._track(SpawnWindowStep(
            id=spawn_id,
            description=f"spawn {ar.app_name}",
            app_name=ar.app_name,
            workspace_name=ws_name,
            command=ar.spec.spawn.command,
            cwd=ar.spec.spawn.cwd,
            env=ar.spec.spawn.env,
            shell=ar.spec.spawn.shell,
            depends_on=base_deps,
        ))
        self._track(WaitForWindowStep(
            id=wait_id,
            description=f"wait for {ar.app_name}",
            app_name=ar.app_name,
            workspace_name=ws_name,
            match=ar.spec.match,
            timeout_s=ar.startup_timeout_s,
            depends_on=[spawn_id],
        ))
        return [wait_id]

    def place_window(self, ar: AppResolution, wr: WorkspaceResolution, deps: list[str]) -> None:
        """Emit move, state, resize, and focus steps as needed."""
        wid = ar.match_decision.assigned_window_id

        if ar.needs_move or ar.status == ResolutionStatus.MISSING:
            self._track(MoveWindowToWorkspaceStep(
                id=self._next_id("move"),
                description=f"move {ar.app_name} to '{wr.name}'",
                app_name=ar.app_name,
                workspace_name=wr.name,
                window_id=wid,
                target_workspace=wr.name,
                depends_on=deps,
            ))

        # State steps (floating/tiling, fullscreen, maximized)
        self._emit_state_steps(ar, wr.name, wid, deps)
        # Resize steps
        self._emit_resize_steps(ar, wr.name, wid, deps)
        # Focus
        if ar.spec.placement.focus:
            self._track(FocusWindowStep(
                id=self._next_id("focus"),
                window_id=wid,
                description=f"focus {ar.app_name}",
                app_name=ar.app_name,
                workspace_name=wr.name,
                depends_on=deps,
            ))

    def focus_workspace(self, wr: WorkspaceResolution) -> None:
        """Emit workspace focus step."""
        self._track(FocusWorkspaceStep(
            id=self._next_id("focus-ws"),
            description=f"focus workspace '{wr.name}'",
            workspace_name=wr.name,
        ))

    def wire_app_dependencies(self, resolution: Resolution) -> None:
        """Add cross-app dependency edges from spec.depends_on."""
        deps_to_add: dict[str, list[str]] = {}
        for wr in resolution.workspace_resolutions:
            for ar in wr.app_resolutions:
                if not ar.spec.depends_on:
                    continue
                first_key = f"{wr.name}/{ar.app_name}"
                first_id = self._app_first.get(first_key)
                if first_id is None:
                    continue
                for dep_name in ar.spec.depends_on:
                    dep_key = f"{wr.name}/{dep_name}"
                    dep_last = self._app_last.get(dep_key)
                    if dep_last:
                        deps_to_add.setdefault(first_id, []).append(dep_last)

        if deps_to_add:
            self._steps = [
                s.model_copy(update={"depends_on": s.depends_on + deps_to_add[s.id]})
                if s.id in deps_to_add else s
                for s in self._steps
            ]

    def build(self) -> list[PlanStep]:
        """Return topologically sorted steps."""
        return topological_sort(self._steps)

    # Private helpers for _emit_state_steps, _emit_resize_steps ...
```

### Refactored `compile_plan()`

```python
def compile_plan(resolution: Resolution, options: SessionOptions) -> Plan:
    builder = PlanBuilder()

    for wr in resolution.workspace_resolutions:
        ensure_id = builder.ensure_workspace(wr)
        base_deps = [ensure_id] if ensure_id else []

        for ar in wr.app_resolutions:
            if not _should_act(ar, options):
                continue

            placement_deps = list(base_deps)
            if ar.status == ResolutionStatus.MISSING and ar.spec.spawn:
                placement_deps = builder.spawn_app(ar, wr.name, base_deps)

            builder.place_window(ar, wr, placement_deps)

    for wr in resolution.workspace_resolutions:
        if wr.focus:
            builder.focus_workspace(wr)

    builder.wire_app_dependencies(resolution)

    return Plan(
        session_name=resolution.session_name,
        steps=builder.build(),
        resolution=resolution,
    )
```

### Steps

1. **Create** `src/nirip/planning/builder.py` — implement `PlanBuilder` class
2. **Edit** `src/nirip/planning/compiler.py` — replace inline step construction with builder calls
3. **Edit** `src/nirip/planning/__init__.py` — optionally export `PlanBuilder`
4. **Move** `_parse_size` (now `parse_size` from M6) into the builder or keep in compiler

### Validation

- All existing compiler tests pass unchanged (behavior is identical)
- The builder methods can be individually unit-tested
- `compile_plan()` is now ~25 lines instead of ~215

---

## R3: Structured Logging in Executor

**File**: `src/nirip/execution/executor.py`
**Severity**: Architectural improvement
**Risk**: Low — callback-based, opt-in

### Problem

Execution produces `StepResult` objects but no live observability. When a plan takes 30+ seconds, there's no feedback until it completes.

### Design

Use a callback/hook pattern that's opt-in — no change to the return type.

```python
from collections.abc import Callable
from typing import Protocol

class ExecutionHook(Protocol):
    """Observer for plan execution events."""

    def on_step_start(self, step: PlanStep) -> None: ...
    def on_step_complete(self, step: PlanStep, result: StepResult) -> None: ...
    def on_plan_complete(self, result: ApplyResult) -> None: ...
```

### Steps

1. **Create** `src/nirip/execution/hooks.py`:

```python
"""Execution lifecycle hooks."""

from __future__ import annotations

from typing import Protocol

from nirip.execution.models import ApplyResult, StepResult
from nirip.planning.models import PlanStep


class ExecutionHook(Protocol):
    def on_step_start(self, step: PlanStep) -> None: ...
    def on_step_complete(self, step: PlanStep, result: StepResult) -> None: ...
    def on_plan_complete(self, result: ApplyResult) -> None: ...


class NullHook:
    """Default no-op hook."""

    def on_step_start(self, step: PlanStep) -> None:
        pass

    def on_step_complete(self, step: PlanStep, result: StepResult) -> None:
        pass

    def on_plan_complete(self, result: ApplyResult) -> None:
        pass


class LoggingHook:
    """Prints step progress to stderr."""

    def on_step_start(self, step: PlanStep) -> None:
        import sys
        print(f"  -> {step.description}...", file=sys.stderr, flush=True)

    def on_step_complete(self, step: PlanStep, result: StepResult) -> None:
        import sys
        print(f"     {result.outcome} ({result.duration_s:.1f}s)", file=sys.stderr, flush=True)

    def on_plan_complete(self, result: ApplyResult) -> None:
        import sys
        status = "OK" if result.success else "FAILED"
        print(f"  Plan {status} in {result.total_duration_s:.1f}s", file=sys.stderr, flush=True)
```

2. **Edit** `src/nirip/execution/executor.py` — accept and call hooks:

```python
from nirip.execution.hooks import ExecutionHook, NullHook

async def execute_plan(
    plan: Plan,
    ports: SessionPorts,
    options: SessionOptions,
    hook: ExecutionHook | None = None,
) -> ApplyResult:
    _hook = hook or NullHook()
    # ... existing setup ...

    for step in plan.steps:
        _hook.on_step_start(step)
        t_step = time.monotonic()
        try:
            result = await execute_step(step, ports, runtime)
        except WaitTimeoutError:
            # ... existing handling ...
        # ...
        _hook.on_step_complete(step, result)
        results.append(result)
        # ...

    apply_result = ApplyResult(...)
    _hook.on_plan_complete(apply_result)
    return apply_result
```

3. **Edit** `src/nirip/facade/async_nirip.py` — thread hook through to `apply()`:

```python
async def apply(self, spec: SessionSpec, hook: ExecutionHook | None = None) -> ApplyResult:
    # ...
    return await execute_plan(plan, ports, spec.options, hook=hook)
```

4. **Edit** CLI apply command to use `LoggingHook` when not `--quiet`

### Validation

- Existing tests pass (hook defaults to `NullHook`, no behavior change)
- Manual test: `nirip apply session.yaml` shows step-by-step progress on stderr

---

## R4: Deferred Defaults in `apply_defaults()`

**File**: `src/nirip/spec/defaults.py`
**Severity**: Architectural improvement
**Risk**: Low — no change recommended for current scale

### Problem

`apply_defaults()` bakes `default_timeout` into every `AppSpec` at load time. You can't change the timeout and re-apply without reloading the spec. This blocks potential "live config reload" use cases.

### Current Approach

```python
def apply_defaults(spec: SessionSpec) -> SessionSpec:
    default_timeout = spec.options.default_startup_timeout_s
    # ... copies each app with the timeout baked in ...
```

### Recommendation

**No action needed for 0.2.0.** The current approach is correct for the single-shot reconciliation model. If nirip ever supports persistent daemon mode or live config reload, the fix would be:

1. Remove `apply_defaults()` entirely
2. In the resolver, read `spec.options.default_startup_timeout_s` at resolution time:
   ```python
   timeout = app_spec.startup_timeout_s or spec.options.default_startup_timeout_s
   ```
   (This is actually what `resolver.py:45` already does!)

3. Since `resolver.py` already handles this correctly, `apply_defaults()` may be dead code or only needed for external consumers who access `AppSpec.startup_timeout_s` directly. Verify:
   ```
   rg 'apply_defaults' src/
   rg 'startup_timeout_s' src/
   ```

### Steps (deferred)

1. Verify whether `apply_defaults()` is called anywhere
2. If it's only called from `load_spec_from_*`, and the resolver handles defaults independently, consider removing `apply_defaults()` entirely
3. If external consumers depend on baked-in timeouts, add a comment documenting why it exists

---

## Implementation Order

Recommended order, balancing risk and dependency:

### Phase 1: Quick wins (no behavioral change)
1. **H3** — add config param to `apply_session()` (2 lines)
2. **L8** — already done, verify
3. **M6** — rename `_parse_size` to `parse_size`
4. **M4** — unify `_detect_drift()` property checks
5. **L3** — remove redundant `target_workspace`

### Phase 2: Validation and correctness
6. **M7** — add `ResizeWindowStep` validator
7. **M1** — deduplicate `_STATE_CHECKS`
8. **L7** — add `--verbose` flag to CLI

### Phase 3: Behavioral improvements
9. **M5** — skip default-value state steps for spawned windows
10. **L2** — report `OPTIONAL_MISSING` in diff
11. **M3** — process lifecycle tracking in spawn/wait

### Phase 4: Architecture (can be done independently)
12. **M2** — remove `use_enum_values=True`
13. **L4** — regex compilation cache
14. **L5** — `AsyncNirip.open()` async context manager pattern
15. **L1** — protocol enforcement for test fakes

### Phase 5: Major refactors
16. **R1** — extract `WindowAssigner` protocol
17. **R2** — step builder pattern
18. **R3** — structured logging hooks
19. **R4** — evaluate deferred defaults (may be no-op)
20. **L6** — document allocation concern (no code change)
