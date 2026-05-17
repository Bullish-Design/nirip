# Nirip Refactor Implementation Guide

A precise, step-by-step guide to refactor the nirip codebase. Each task specifies exactly what to change, where, and how to validate. Follow in order — later phases depend on earlier ones.

---

## 0. Principles

1. **Delete before implementing.** Dead code is worse than missing features.
2. **Simplest correct fix.** No new abstractions unless they eliminate a class of bugs.
3. **Tests prove the fix.** Every task has a "Validate" section. The task is not done until validation passes.
4. **One concern per commit.** Each numbered task (A1, B1, etc.) is one commit.

---

## 1. Success Criteria

When the refactor is complete:

```bash
ruff check src/nirip/ tests/
ty check src/nirip/
python -m pytest tests/ -x
```

All pass. Additionally:
- No `object` type annotations in function signatures (except where the upstream type is genuinely `object`).
- No bare `Exception` catches outside `execution/executor.py`.
- No dead/unimplemented `SessionOptions` fields.
- Spawned apps receive full placement steps.
- `depends_on` affects execution ordering.

---

## 2. Phase Overview

```
Phase A: Remove dead code and hacks (3 tasks)
Phase B: Fix correctness bugs (4 tasks)
Phase C: Core architecture changes (2 tasks)
Phase D: Executor hardening (4 tasks)
Phase E: CLI and facade cleanup (3 tasks)
```

---

## Phase A: Remove Dead Code

Goal: Shrink the codebase before changing it. Every deletion makes subsequent work simpler.

---

### A1. Remove unused `SessionOptions` fields

**Why:** `mode`, `match_existing`, and `move_unmatched` are defined in the schema but never enforced anywhere. AGENTS.md says "enforce or remove." Since their semantics are undefined, we remove.

**File: `src/nirip/spec/models.py`**

Change `SessionOptions` from:
```python
class SessionOptions(NiripModel):
    mode: Literal["reconcile", "clean"] = "reconcile"
    match_existing: bool = True
    launch_missing: bool = True
    stop_on_error: bool = True
    move_unmatched: bool = False
    default_startup_timeout_s: float = 20.0
```

To:
```python
class SessionOptions(NiripModel):
    launch_missing: bool = True
    stop_on_error: bool = True
    default_startup_timeout_s: float = 20.0
```

Remove the `Literal` import if no longer used.

**Cascade — search and fix all references:**

1. `src/nirip/spec/validators.py` — if any validator checks these fields, remove those checks.
2. `tests/` — grep for `mode=`, `match_existing=`, `move_unmatched=` in test fixtures. Remove or simplify.
3. `src/nirip/resolve/resolver.py` — verify `normalized.options.launch_missing` still works (it does — we kept that field).

**Validate:**
```bash
ruff check src/nirip/ tests/
ty check src/nirip/
python -m pytest tests/ -x
```

---

### A2. Remove `_wait` compatibility hack

**Why:** The current code catches `TypeError` to try an alternate `wait_until` signature. This masks legitimate TypeErrors from predicates (e.g., predicate returns non-bool).

**Root cause:** `wait_until` in niri-state (`niri_state/api/waiters.py`) has `config: NiriStateConfig` as a **required** keyword-only parameter with no default. The hack tried calling without it (TypeError), then with `config=None` (would crash on `config.wait_health_policy`). Neither path was correct.

**The actual fix** is to construct a `NiriStateConfig()` (which uses the sensible default `LIVE_ONLY` health policy) and pass it explicitly.

**File: `src/nirip/execution/handlers.py`**

Replace:
```python
async def _wait(state: Any, predicate: Any, timeout: float) -> Any:
    try:
        return await wait_until(state, predicate, timeout=timeout)
    except TypeError:
        return await wait_until(state, predicate, config=None, timeout=timeout)
```

With:
```python
from collections.abc import Callable
from niri_state import NiriState, Snapshot
from niri_state.api.config import NiriStateConfig

_WAIT_CONFIG = NiriStateConfig()  # default: wait_health_policy=LIVE_ONLY


async def _wait(state: NiriState, predicate: Callable[[Snapshot], bool], timeout: float) -> Snapshot:
    """Wait for predicate to become true against live state."""
    return await wait_until(state, predicate, config=_WAIT_CONFIG, timeout=timeout)
```

Remove the `Any` import if no longer used elsewhere (it may still be needed for `_request`).

**Upstream improvement (niri-state, separate PR):** Make `config` optional in `wait_until` so callers don't need to construct a config for default behavior:

```python
# In niri_state/api/waiters.py — change signature:
async def wait_until(
    state: WaitableState,
    predicate: Callable[[Snapshot], bool],
    *,
    config: NiriStateConfig | None = None,  # was: config: NiriStateConfig (required)
    timeout: float | None = None,
) -> Snapshot:
    if config is None:
        config = NiriStateConfig()
    ...
```

This is backward-compatible (existing callers passing `config=` still work). Do this in niri-state first, then nirip can simplify further by dropping `_WAIT_CONFIG`. But the nirip fix above works regardless of whether the upstream change lands.

**Validate:**
```bash
python -m pytest tests/test_executor.py -x
```

---

### A3. Clean up conftest fakes

**Why:** `conftest.py` defines `RecordingClient` that no test uses. Meanwhile, tests use ad-hoc `SimpleNamespace` objects instead of the shared fakes.

**File: `tests/conftest.py`**

- Remove `RecordingClient` (grep confirms no test imports it).
- Keep `FakeWindow`, `FakeWorkspace`, `FakeSnapshot` — these will be used in new tests.
- Ensure `FakeWindow` has all fields that `evaluate_rule` and `_detect_drift` access: `id`, `app_id`, `title`, `pid`, `workspace_id`, `is_floating`, `is_fullscreen`. Add `is_maximized` if the upstream `Window` type has it.

**Validate:**
```bash
python -m pytest tests/ -x
```

---

## Phase B: Correctness Bugs

Goal: Fix all bugs identified in the code review without changing architecture.

---

### B1. Fix negation-only `MatchRule` bug

**Problem:** In `src/nirip/resolve/matcher.py`, `evaluate_rule()` lines 78-83:
```python
if failed:
    return False, 0.0, reasons
if not scores:
    return False, 0.0, reasons
```

A rule like `MatchRule(not_rule=MatchRule(app_id="firefox"))` has no positive criteria. When the negation succeeds, `failed=False` and `scores=[]`, so the function returns `(False, 0.0, ...)`. This means negation-only rules never match.

**File: `src/nirip/resolve/matcher.py`**

Replace lines 78-83:
```python
    if failed:
        return False, 0.0, reasons
    if not scores:
        return False, 0.0, reasons

    confidence = min(scores) if len(scores) > 1 else scores[0]
    return True, confidence, reasons
```

With:
```python
    if failed:
        return False, 0.0, reasons
    if not scores:
        # Rule succeeded through negation or composite-only criteria.
        # No positive criterion contributed a confidence score.
        # Use baseline 0.4 (below any positive match) to reflect lower specificity.
        return True, 0.4, reasons

    confidence = min(scores) if len(scores) > 1 else scores[0]
    return True, confidence, reasons
```

**Why 0.4:** A negation-only rule says what something ISN'T, not what it IS. It's inherently less specific than `app_id` (1.0), `app_id_regex` (0.9), `title` (0.8), `title_regex` (0.7), or even combined rules. 0.4 ensures these rules work but lose ties against positive matches.

**Tests to add — File: `tests/test_matcher.py`**

```python
def test_negation_only_rule_matches_non_target():
    """A rule with only not_rule matches windows that DON'T satisfy the inner rule."""
    from nirip.resolve.matcher import evaluate_rule
    from nirip.spec.models import MatchRule

    rule = MatchRule(not_rule=MatchRule(app_id="firefox"))
    # Window that is NOT firefox
    window = FakeWindow(id=1, app_id="alacritty", title="Terminal")
    matched, confidence, reasons = evaluate_rule(rule, window)
    assert matched is True
    assert confidence == 0.4
    assert any("not_rule satisfied" in r for r in reasons)


def test_negation_only_rule_rejects_target():
    """A rule with only not_rule rejects windows that DO satisfy the inner rule."""
    from nirip.resolve.matcher import evaluate_rule
    from nirip.spec.models import MatchRule

    rule = MatchRule(not_rule=MatchRule(app_id="firefox"))
    window = FakeWindow(id=2, app_id="firefox", title="Firefox")
    matched, confidence, reasons = evaluate_rule(rule, window)
    assert matched is False
    assert confidence == 0.0


def test_negation_combined_with_positive():
    """A rule combining app_id + not_rule uses the positive score, not 0.4."""
    from nirip.resolve.matcher import evaluate_rule
    from nirip.spec.models import MatchRule

    rule = MatchRule(app_id="alacritty", not_rule=MatchRule(title="restricted"))
    window = FakeWindow(id=3, app_id="alacritty", title="Terminal")
    matched, confidence, reasons = evaluate_rule(rule, window)
    assert matched is True
    assert confidence == 1.0  # app_id exact match, not the 0.4 baseline
```

**Validate:**
```bash
python -m pytest tests/test_matcher.py -x -v
```

---

### B2. Type `_detect_drift` with concrete types

**Problem:** `src/nirip/resolve/resolver.py` line 92:
```python
def _detect_drift(window: object, napp: object, ws_name: str, ws_by_name: dict[str, object]) -> list[DriftItem]:
```

Uses `object` and `getattr` everywhere. This hides type errors and contradicts "concrete by default."

**File: `src/nirip/resolve/resolver.py`**

First, determine the correct workspace type. Check what `snapshot.workspaces.values()` returns:
```bash
grep -r "class Workspace" in niri_state and niri_pypc packages
```

It's likely `niri_state.models.Workspace` or similar. The workspace needs `.id`, `.name`, `.output` fields.

Add imports at the top:
```python
from niri_pypc.types.generated.models import Window
from nirip.resolve.models import NormalizedApp
```

For the workspace type, use whatever `snapshot.workspaces` contains. If it's the same `Workspace` from niri_state, import that. If you can't determine it, use a Protocol as last resort (but prefer the concrete type).

Replace `_detect_drift`:
```python
# Table of property drift checks: (drift_kind, window_attribute, placement_attribute)
_PROPERTY_CHECKS: list[tuple[DriftKind, str, str]] = [
    (DriftKind.WRONG_FLOATING, "is_floating", "floating"),
    (DriftKind.WRONG_FULLSCREEN, "is_fullscreen", "fullscreen"),
]


def _detect_drift(
    window: Window,
    napp: NormalizedApp,
    ws_name: str,
    ws_by_name: dict[str, Any],  # Use concrete workspace type if importable
) -> list[DriftItem]:
    """Detect drift between a window's current state and its desired placement."""
    drift: list[DriftItem] = []

    # Workspace drift
    target_ws = ws_by_name.get(ws_name)
    if target_ws is None or window.workspace_id != target_ws.id:
        drift.append(DriftItem(
            kind=DriftKind.WRONG_WORKSPACE,
            current=str(window.workspace_id),
            desired=ws_name,
        ))

    # Property drift (table-driven to reduce boilerplate)
    for kind, win_attr, place_attr in _PROPERTY_CHECKS:
        current_val = getattr(window, win_attr, False)
        desired_val = getattr(napp.placement, place_attr)
        if current_val != desired_val:
            drift.append(DriftItem(kind=kind, current=str(current_val), desired=str(desired_val)))

    # Maximized — guarded because field may not exist on all Window versions
    if hasattr(window, "is_maximized") and window.is_maximized != napp.placement.maximized:
        drift.append(DriftItem(
            kind=DriftKind.WRONG_MAXIMIZED,
            current=str(window.is_maximized),
            desired=str(napp.placement.maximized),
        ))

    return drift
```

**Important:** If the `Window` type from `niri_pypc` DOES have `is_maximized` as a guaranteed field (check the generated model), remove the `hasattr` guard and add it to `_PROPERTY_CHECKS`.

**Update the call site** (line 42 in same file):
```python
drift = _detect_drift(window, napp, nws.name, ws_by_name)
```

This already passes `window` (from `snapshot.windows[...]`) and `napp` (from `normalized.app_index[...]`) — the types already match, we're just being honest about it now.

**Tests — update `tests/test_resolver_drift.py`:**

Replace any `SimpleNamespace` usage with properly-typed fakes from conftest (or minimal dataclass fakes that match the `Window` structure). Ensure the test creates objects with `.workspace_id`, `.is_floating`, `.is_fullscreen`, `.is_maximized` attributes.

**Validate:**
```bash
ty check src/nirip/resolve/
python -m pytest tests/test_resolver_drift.py -x
```

---

### B3. Harden `_parse_size`

**Problem:** `src/nirip/planning/compiler.py` line 211: `int(value[3:])` raises raw `ValueError` on input like `"px:abc"`.

**File: `src/nirip/planning/compiler.py`**

Replace:
```python
def _parse_size(value: float | str) -> tuple[float | None, int | None]:
    """Parse column_width / window_height from spec format."""
    if isinstance(value, (int, float)):
        return (float(value), None)
    if isinstance(value, str) and value.startswith("px:"):
        return (None, int(value[3:]))
    return (float(value), None)
```

With:
```python
def _parse_size(value: float | str) -> tuple[float | None, int | None]:
    """Parse size value: float proportion (0.0-1.0+) or 'px:<integer>' for fixed pixels."""
    if isinstance(value, (int, float)):
        return (float(value), None)
    if isinstance(value, str):
        if value.startswith("px:"):
            try:
                return (None, int(value[3:]))
            except ValueError:
                from nirip.errors import PlanningError
                raise PlanningError(f"invalid pixel size: {value!r} — expected 'px:<integer>'")
        try:
            return (float(value), None)
        except ValueError:
            from nirip.errors import PlanningError
            raise PlanningError(f"invalid size value: {value!r}")
    from nirip.errors import PlanningError
    raise PlanningError(f"unexpected size type: {type(value).__name__}")
```

**Tests — add to `tests/test_compiler.py`:**

```python
import pytest
from nirip.errors import PlanningError
from nirip.planning.compiler import _parse_size


def test_parse_size_float():
    assert _parse_size(0.5) == (0.5, None)


def test_parse_size_int():
    assert _parse_size(800) == (800.0, None)


def test_parse_size_px_valid():
    assert _parse_size("px:1200") == (None, 1200)


def test_parse_size_px_invalid():
    with pytest.raises(PlanningError, match="invalid pixel size"):
        _parse_size("px:abc")


def test_parse_size_string_proportion():
    assert _parse_size("0.75") == (0.75, None)


def test_parse_size_garbage_string():
    with pytest.raises(PlanningError, match="invalid size value"):
        _parse_size("garbage")
```

**Validate:**
```bash
python -m pytest tests/test_compiler.py -x -v
```

---

### B4. Strengthen dependency validation

**Problem:** `src/nirip/spec/validators.py` `_check_depends_on_refs` (lines 59-93) builds a graph that includes dangling node references. The DFS traverses `graph.get(node, [])` for nodes that were never defined, which works by accident but is fragile and produces confusing error messages.

**File: `src/nirip/spec/validators.py`**

Replace `_check_depends_on_refs`:
```python
def _check_depends_on_refs(spec: SessionSpec, errors: list[str]) -> None:
    """Validate depends_on references and check for cycles."""
    # Phase 1: Report invalid references
    ws_apps: dict[str, set[str]] = {ws.name: {a.name for a in ws.apps} for ws in spec.workspaces}
    has_dangling = False

    for ws in spec.workspaces:
        for app in ws.apps:
            for dep in app.depends_on:
                if dep not in ws_apps[ws.name]:
                    errors.append(
                        f"{ws.name}/{app.name} depends on '{dep}' which does not exist "
                        f"in workspace '{ws.name}' (cross-workspace dependencies are not supported)"
                    )
                    has_dangling = True

    # Phase 2: Cycle detection — only run if all references are valid
    # (DFS over an incomplete graph produces meaningless results)
    if has_dangling:
        return

    # Build graph from valid edges only
    graph: dict[str, list[str]] = {}
    for ws in spec.workspaces:
        for app in ws.apps:
            key = f"{ws.name}/{app.name}"
            graph[key] = [f"{ws.name}/{dep}" for dep in app.depends_on]

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        if node in visiting:
            i = path.index(node)
            cycle = path[i:] + [node]
            errors.append(f"dependency cycle: {' -> '.join(cycle)}")
            return
        if node in visited:
            return
        visiting.add(node)
        path.append(node)
        for nxt in graph.get(node, []):
            dfs(nxt, path)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        dfs(node, [])
```

**Tests — add to `tests/test_spec_validators.py`:**

```python
def test_depends_on_unknown_app_error_message():
    """Dangling depends_on produces clear error about workspace scope."""
    from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec
    from nirip.spec.validators import validate_session

    spec = SessionSpec(
        name="test",
        workspaces=[WorkspaceSpec(
            name="dev",
            apps=[
                AppSpec(name="editor", match=MatchRule(app_id="code"), depends_on=["nonexistent"]),
            ],
        )],
    )
    result = validate_session(spec)
    assert not result.valid
    assert any("does not exist in workspace 'dev'" in e for e in result.errors)
    assert any("cross-workspace dependencies are not supported" in e for e in result.errors)


def test_depends_on_cycle_detected():
    """Circular deps produce cycle error."""
    from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec
    from nirip.spec.validators import validate_session

    spec = SessionSpec(
        name="test",
        workspaces=[WorkspaceSpec(
            name="dev",
            apps=[
                AppSpec(name="a", match=MatchRule(app_id="a"), depends_on=["b"]),
                AppSpec(name="b", match=MatchRule(app_id="b"), depends_on=["a"]),
            ],
        )],
    )
    result = validate_session(spec)
    assert not result.valid
    assert any("dependency cycle" in e for e in result.errors)


def test_dangling_dep_skips_dfs():
    """When a dep is dangling, no spurious cycle errors are reported."""
    from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec
    from nirip.spec.validators import validate_session

    spec = SessionSpec(
        name="test",
        workspaces=[WorkspaceSpec(
            name="dev",
            apps=[
                AppSpec(name="a", match=MatchRule(app_id="a"), depends_on=["ghost"]),
                AppSpec(name="b", match=MatchRule(app_id="b"), depends_on=["a"]),
            ],
        )],
    )
    result = validate_session(spec)
    assert not result.valid
    # Should have the dangling ref error
    assert any("ghost" in e for e in result.errors)
    # Should NOT have a spurious cycle error
    assert not any("cycle" in e for e in result.errors)
```

**Validate:**
```bash
python -m pytest tests/test_spec_validators.py -x -v
```

---

## Phase C: Core Architecture Changes

Goal: Fix the two structural gaps — post-spawn placement and inter-app dependency wiring.

---

### C1. Enable post-spawn placement

**Problem:** When an app is MISSING and gets spawned, the compiler emits `SpawnWindowStep` + `WaitForWindowStep` but skips ALL placement steps because `wid = ar.match_decision.assigned_window_id` is `None` for MISSING apps.

This means spawned windows:
- Are NOT moved to the correct workspace
- Are NOT set floating/tiling/fullscreen
- Are NOT sized
- Are NOT focused

**Design:** Make `window_id` optional on placement step types. The compiler emits placement steps for spawned apps with `window_id=None` and `depends_on=[wait_step_id]`. The executor resolves the ID from `runtime.apps[app_name].matched_window_id` at dispatch time.

This leverages existing infrastructure:
- Steps already have `app_name`
- `SessionRuntime` already has `apps[name].matched_window_id`
- Topological sort already respects `depends_on`

No new types needed.

---

**Step 1: Make `window_id` optional on placement steps**

**File: `src/nirip/planning/models.py`**

Change every step type that has `window_id: int` to `window_id: int | None = None`:

```python
class MoveWindowToWorkspaceStep(StepBase):
    kind: Literal["move_window_to_workspace"] = "move_window_to_workspace"
    window_id: int | None = None
    target_workspace: str

class SetFloatingStep(StepBase):
    kind: Literal["set_floating"] = "set_floating"
    window_id: int | None = None

class SetTilingStep(StepBase):
    kind: Literal["set_tiling"] = "set_tiling"
    window_id: int | None = None

class SetFullscreenStep(StepBase):
    kind: Literal["set_fullscreen"] = "set_fullscreen"
    window_id: int | None = None
    fullscreen: bool

class SetMaximizedStep(StepBase):
    kind: Literal["set_maximized"] = "set_maximized"
    window_id: int | None = None
    maximized: bool

class SetColumnWidthStep(StepBase):
    kind: Literal["set_column_width"] = "set_column_width"
    window_id: int | None = None
    proportion: float | None = None
    pixels: int | None = None

class SetWindowHeightStep(StepBase):
    kind: Literal["set_window_height"] = "set_window_height"
    window_id: int | None = None
    proportion: float | None = None
    pixels: int | None = None

class FocusWindowStep(StepBase):
    kind: Literal["focus_window"] = "focus_window"
    window_id: int | None = None
```

---

**Step 2: Update compiler to emit placement steps for spawned apps**

**File: `src/nirip/planning/compiler.py`**

Restructure the per-app loop in `compile_plan`. The key change: emit placement steps regardless of whether `wid` is known. For spawned apps, those steps get `window_id=None` and `depends_on` pointing to the wait step.

Replace the per-app section (approximately lines 60-198) with:

```python
    for wr in resolution.workspace_resolutions:
        ensure_id: str | None = None

        if not wr.exists:
            ensure_id = next_id("ensure-ws")
            steps.append(EnsureWorkspaceStep(
                id=ensure_id,
                description=f"create workspace '{wr.name}'",
                workspace_name=wr.name,
                target_output=wr.desired_output,
            ))
        elif not wr.output_correct and wr.desired_output:
            steps.append(MoveWorkspaceToOutputStep(
                id=next_id("move-ws"),
                description=f"move workspace '{wr.name}' to {wr.desired_output}",
                workspace_name=wr.name,
                target_output=wr.desired_output,
            ))

        for ar in wr.app_resolutions:
            if not ar.action_required:
                continue

            napp = normalized.app_index[f"{wr.name}/{ar.app_name}"]
            base_deps = [ensure_id] if ensure_id else []

            # For spawned apps: emit spawn + wait, placement depends on wait
            # For existing apps: placement depends on workspace ensure (if any)
            placement_deps = list(base_deps)
            wid = ar.match_decision.assigned_window_id  # None for MISSING

            if ar.needs_spawn and napp.spawn:
                spawn_id = next_id("spawn")
                wait_id = next_id("wait")
                steps.append(SpawnWindowStep(
                    id=spawn_id,
                    description=f"spawn {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    command=napp.spawn.command,
                    cwd=napp.spawn.cwd,
                    env=napp.spawn.env,
                    shell=napp.spawn.shell,
                    depends_on=base_deps,
                ))
                steps.append(WaitForWindowStep(
                    id=wait_id,
                    description=f"wait for {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    match=napp.match,
                    timeout_s=napp.startup_timeout_s,
                    depends_on=[spawn_id],
                ))
                placement_deps = [wait_id]

            # Move to workspace (spawned apps land on default workspace; drifted apps are misplaced)
            if ar.needs_move or ar.needs_spawn:
                steps.append(MoveWindowToWorkspaceStep(
                    id=next_id("move"),
                    description=f"move {ar.app_name} to '{wr.name}'",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    window_id=wid,
                    target_workspace=wr.name,
                    depends_on=placement_deps,
                ))

            # Floating/tiling placement
            _emit_float_tiling(steps, next_id, ar, napp, wr.name, wid, placement_deps)

            # Fullscreen
            if ar.needs_spawn or any(d.kind == DriftKind.WRONG_FULLSCREEN for d in ar.drift):
                if napp.placement.fullscreen:
                    steps.append(SetFullscreenStep(
                        id=next_id("fs"),
                        window_id=wid,
                        fullscreen=True,
                        description=f"set {ar.app_name} fullscreen",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        depends_on=placement_deps,
                    ))

            # Maximized
            if ar.needs_spawn or any(d.kind == DriftKind.WRONG_MAXIMIZED for d in ar.drift):
                if napp.placement.maximized:
                    steps.append(SetMaximizedStep(
                        id=next_id("max"),
                        window_id=wid,
                        maximized=True,
                        description=f"set {ar.app_name} maximized",
                        app_name=ar.app_name,
                        workspace_name=wr.name,
                        depends_on=placement_deps,
                    ))

            # Column width
            if napp.placement.column_width is not None:
                prop, px = _parse_size(napp.placement.column_width)
                steps.append(SetColumnWidthStep(
                    id=next_id("cw"),
                    window_id=wid,
                    proportion=prop,
                    pixels=px,
                    description=f"set column width for {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    depends_on=placement_deps,
                ))

            # Window height
            if napp.placement.window_height is not None:
                prop, px = _parse_size(napp.placement.window_height)
                steps.append(SetWindowHeightStep(
                    id=next_id("wh"),
                    window_id=wid,
                    proportion=prop,
                    pixels=px,
                    description=f"set window height for {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    depends_on=placement_deps,
                ))

            # Focus window
            if napp.placement.focus:
                steps.append(FocusWindowStep(
                    id=next_id("focus"),
                    window_id=wid,
                    description=f"focus {ar.app_name}",
                    app_name=ar.app_name,
                    workspace_name=wr.name,
                    depends_on=placement_deps,
                ))


def _emit_float_tiling(
    steps: list[PlanStep],
    next_id: Callable[[str], str],
    ar: AppResolution,
    napp: NormalizedApp,
    ws_name: str,
    wid: int | None,
    deps: list[str],
) -> None:
    """Emit SetFloating or SetTiling if needed."""
    needs_it = ar.needs_spawn or any(d.kind == DriftKind.WRONG_FLOATING for d in ar.drift)
    if not needs_it:
        return
    if napp.placement.floating:
        steps.append(SetFloatingStep(
            id=next_id("float"),
            window_id=wid,
            description=f"set {ar.app_name} floating",
            app_name=ar.app_name,
            workspace_name=ws_name,
            depends_on=deps,
        ))
    else:
        steps.append(SetTilingStep(
            id=next_id("tile"),
            window_id=wid,
            description=f"set {ar.app_name} tiling",
            app_name=ar.app_name,
            workspace_name=ws_name,
            depends_on=deps,
        ))
```

Add import at top:
```python
from collections.abc import Callable
from nirip.resolve.models import AppResolution
```

**Note about `action_required` guard:** The old code didn't have this — it emitted placement steps for MATCHED apps too (column_width/window_height unconditionally). The new code only emits when `ar.action_required` is true. For spawned apps, `action_required=True` when `launch_missing=True`. For drifted apps, `action_required=True` always. For MATCHED apps with no drift, `action_required=False`, so they're correctly skipped.

However: if the user specifies `column_width` and the window is MATCHED (no drift), the width won't be enforced. If you want "always enforce size," remove the `if not ar.action_required: continue` guard for size steps specifically. Decide based on user expectations — for now, only enforce on drift/spawn (consistent with the reconciliation model).

---

**Step 3: Executor resolves `window_id=None` at dispatch time**

**File: `src/nirip/execution/handlers.py`**

Add a resolution helper near the top:

```python
def _resolve_window_id(step: PlanStep, runtime: SessionRuntime) -> int | None:
    """Resolve the target window ID for a step.

    If the step has a literal window_id, use it.
    Otherwise, look up from runtime state using the step's app_name.
    """
    wid = getattr(step, "window_id", None)
    if wid is not None:
        return wid
    if step.app_name and step.app_name in runtime.apps:
        return runtime.apps[step.app_name].matched_window_id
    return None
```

Then, in every handler case that accesses `step.window_id`, replace with resolution:

```python
case MoveWindowToWorkspaceStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    workspace_ref = actions.workspace_by_name(step.target_workspace)
    await _request(ports.client, actions.move_window_to_workspace(workspace_ref, window_id=wid))
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window moved", window_id=wid)

case SetFloatingStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    await _request(ports.client, actions.move_window_to_floating(wid))
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window set floating", window_id=wid)
```

Apply the same pattern to: `SetTilingStep`, `SetFullscreenStep`, `SetMaximizedStep`, `SetColumnWidthStep`, `SetWindowHeightStep`, `FocusWindowStep`.

---

**Step 4: Update predicates for optional window_id**

**File: `src/nirip/execution/predicates.py`**

The `is_already_satisfied` function accesses `step.window_id` directly. When it's `None`, we can't check the predicate, so return `False` (don't skip — let the executor resolve the ID and run the step).

```python
case MoveWindowToWorkspaceStep():
    if step.window_id is None:
        return False
    w = snapshot.windows.get(step.window_id)
    ...
case SetFloatingStep():
    if step.window_id is None:
        return False
    w = snapshot.windows.get(step.window_id)
    ...
```

Apply to all cases that access `step.window_id`.

---

**Tests — new file: `tests/test_compiler_spawn_placement.py`**

```python
"""Tests that spawned apps get full placement steps."""

from nirip.planning.compiler import compile_plan
from nirip.resolve.models import (
    AppResolution, MatchDecision, NormalizedApp, NormalizedSession,
    NormalizedWorkspace, Resolution, ResolutionStatus, WorkspaceResolution,
)
from nirip.spec.models import MatchRule, PlacementSpec, SessionOptions, SpawnSpec


def _make_resolution(status: ResolutionStatus, wid: int | None = None) -> tuple[Resolution, NormalizedSession]:
    """Helper to build minimal resolution + normalized session for testing."""
    napp = NormalizedApp(
        name="myapp",
        workspace_name="dev",
        match=MatchRule(app_id="myapp"),
        spawn=SpawnSpec(command="myapp"),
        placement=PlacementSpec(floating=True, focus=True),
        optional=False,
        startup_timeout_s=10.0,
        depends_on=[],
    )
    decision = MatchDecision(
        app_name="myapp",
        workspace_name="dev",
        assigned_window_id=wid,
        candidates=[],
        confidence=0.0 if wid is None else 1.0,
        rationale=["test"],
    )
    ar = AppResolution(
        app_name="myapp",
        workspace_name="dev",
        status=status,
        match_decision=decision,
        drift=[],
        action_required=True,
    )
    wr = WorkspaceResolution(
        name="dev", exists=True, output_correct=True,
        desired_output=None, current_output=None,
        app_resolutions=[ar],
    )
    resolution = Resolution(
        session_name="test", workspace_resolutions=[wr],
        unmatched_apps=[ar] if status == ResolutionStatus.MISSING else [],
        ambiguous_apps=[], warnings=[],
    )
    normalized = NormalizedSession(
        name="test", description="", options=SessionOptions(),
        workspaces=[NormalizedWorkspace(name="dev", output=None, focus=False, app_names=["myapp"])],
        apps=[napp], app_index={"dev/myapp": napp},
    )
    return resolution, normalized


def test_spawned_app_gets_placement_steps():
    """A MISSING app with spawn gets move + floating + focus steps."""
    resolution, normalized = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, normalized)

    kinds = [s.kind for s in plan.steps]
    assert "spawn_window" in kinds
    assert "wait_for_window" in kinds
    assert "move_window_to_workspace" in kinds
    assert "set_floating" in kinds
    assert "focus_window" in kinds


def test_spawned_app_placement_has_null_window_id():
    """Placement steps for spawned apps have window_id=None (resolved at runtime)."""
    resolution, normalized = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, normalized)

    float_step = next(s for s in plan.steps if s.kind == "set_floating")
    assert float_step.window_id is None
    assert float_step.app_name == "myapp"


def test_spawned_app_placement_depends_on_wait():
    """Placement steps for spawned apps depend on the wait step."""
    resolution, normalized = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, normalized)

    wait_step = next(s for s in plan.steps if s.kind == "wait_for_window")
    float_step = next(s for s in plan.steps if s.kind == "set_floating")
    assert wait_step.id in float_step.depends_on
```

**Validate:**
```bash
python -m pytest tests/test_compiler_spawn_placement.py tests/test_compiler.py -x -v
python -m pytest tests/ -x  # full suite still passes
```

---

### C2. Wire `depends_on` into plan ordering

**Problem:** `NormalizedApp.depends_on` lists other app names that must complete first. The compiler never creates cross-app dependency edges, so `depends_on` has no effect on execution order.

**File: `src/nirip/planning/compiler.py`**

After the per-workspace app loop, add cross-app dependency wiring. The approach:
1. Track the last step emitted for each app (its "completion point").
2. For each app with `depends_on`, make its first step depend on the completion step of each referenced app.

Add this logic after the `for wr in resolution.workspace_resolutions:` loop, before the workspace focus section:

```python
    # Wire inter-app depends_on edges
    # Build index: app_name -> (first_step_id, last_step_id) within same workspace
    app_first_step: dict[str, str] = {}  # "ws/app" -> first step id
    app_last_step: dict[str, str] = {}   # "ws/app" -> last step id

    for s in steps:
        if s.app_name and s.workspace_name:
            key = f"{s.workspace_name}/{s.app_name}"
            if key not in app_first_step:
                app_first_step[key] = s.id
            app_last_step[key] = s.id

    # For each app with depends_on, inject dependency edge
    deps_to_add: dict[str, list[str]] = {}  # step_id -> additional depends_on
    for nws in normalized.workspaces:
        for app_name in nws.app_names:
            napp = normalized.app_index[f"{nws.name}/{app_name}"]
            if not napp.depends_on:
                continue
            first_key = f"{nws.name}/{app_name}"
            first_id = app_first_step.get(first_key)
            if first_id is None:
                continue  # app had no steps (e.g., MATCHED with no drift)
            for dep_name in napp.depends_on:
                dep_key = f"{nws.name}/{dep_name}"
                dep_last = app_last_step.get(dep_key)
                if dep_last:
                    deps_to_add.setdefault(first_id, []).append(dep_last)

    # Rebuild steps with added dependencies (models are frozen)
    if deps_to_add:
        steps = [
            s.model_copy(update={"depends_on": s.depends_on + deps_to_add[s.id]})
            if s.id in deps_to_add else s
            for s in steps
        ]
```

**Important:** This must come BEFORE `steps = topological_sort(steps)` so the new edges are respected by the sort.

**Tests — new file: `tests/test_compiler_depends_on.py`**

```python
"""Tests for inter-app depends_on wiring in the compiler."""

from nirip.planning.compiler import compile_plan
from nirip.resolve.models import (
    AppResolution, MatchDecision, NormalizedApp, NormalizedSession,
    NormalizedWorkspace, Resolution, ResolutionStatus, WorkspaceResolution,
)
from nirip.spec.models import MatchRule, PlacementSpec, SessionOptions, SpawnSpec


def test_depends_on_enforces_ordering():
    """App B depends on A => B's first step has A's last step in depends_on."""
    # App A: will be spawned
    napp_a = NormalizedApp(
        name="app_a", workspace_name="dev", match=MatchRule(app_id="app_a"),
        spawn=SpawnSpec(command="app_a"), placement=PlacementSpec(),
        optional=False, startup_timeout_s=10.0, depends_on=[],
    )
    # App B: will be spawned, depends on A
    napp_b = NormalizedApp(
        name="app_b", workspace_name="dev", match=MatchRule(app_id="app_b"),
        spawn=SpawnSpec(command="app_b"), placement=PlacementSpec(),
        optional=False, startup_timeout_s=10.0, depends_on=["app_a"],
    )

    def make_ar(name: str) -> AppResolution:
        return AppResolution(
            app_name=name, workspace_name="dev", status=ResolutionStatus.MISSING,
            match_decision=MatchDecision(
                app_name=name, workspace_name="dev",
                assigned_window_id=None, candidates=[], confidence=0.0, rationale=["test"],
            ),
            drift=[], action_required=True,
        )

    wr = WorkspaceResolution(
        name="dev", exists=True, output_correct=True,
        desired_output=None, current_output=None,
        app_resolutions=[make_ar("app_a"), make_ar("app_b")],
    )
    resolution = Resolution(
        session_name="test", workspace_resolutions=[wr],
        unmatched_apps=[], ambiguous_apps=[], warnings=[],
    )
    normalized = NormalizedSession(
        name="test", description="", options=SessionOptions(),
        workspaces=[NormalizedWorkspace(name="dev", output=None, focus=False, app_names=["app_a", "app_b"])],
        apps=[napp_a, napp_b],
        app_index={"dev/app_a": napp_a, "dev/app_b": napp_b},
    )

    plan = compile_plan(resolution, normalized)

    # Find app_b's first step and app_a's last step
    a_steps = [s for s in plan.steps if s.app_name == "app_a"]
    b_steps = [s for s in plan.steps if s.app_name == "app_b"]
    assert a_steps and b_steps

    a_last = a_steps[-1]
    b_first = b_steps[0]
    assert a_last.id in b_first.depends_on, (
        f"Expected {a_last.id} in {b_first.depends_on}"
    )

    # Verify topological order: all A steps appear before all B steps
    step_ids = [s.id for s in plan.steps]
    a_last_idx = step_ids.index(a_last.id)
    b_first_idx = step_ids.index(b_first.id)
    assert a_last_idx < b_first_idx
```

**Validate:**
```bash
python -m pytest tests/test_compiler_depends_on.py tests/test_compiler.py -x -v
python -m pytest tests/ -x
```

---

## Phase D: Executor Hardening

Goal: Fix error handling, clean up StepResult semantics, capture window IDs, add selective verification.

---

### D1. Centralize error handling in executor

**Problem:** Both `handlers.py` (line 179: `except Exception`) and `executor.py` (line 29: `except Exception`) catch broad exceptions, swallowing programming errors as FAILED results.

**Design:** Handlers are pure "do the thing" functions — they succeed or raise. The executor is the single error-policy boundary.

**File: `src/nirip/execution/handlers.py`**

Remove the outer `try/except` block (lines 54 and 172-187). The function body is just the `match step:` block that returns results directly. If anything raises, it propagates to the executor.

The function becomes:
```python
async def execute_step(step: PlanStep, ports: SessionPorts, runtime: SessionRuntime) -> StepResult:
    """Execute a single plan step. Raises on unexpected errors (executor handles them)."""
    if is_already_satisfied(step, ports.state.snapshot):
        return StepResult(step=step, outcome=StepOutcome.SKIPPED, message="already satisfied")

    match step:
        case EnsureWorkspaceStep():
            await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
            return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace ensured")
        # ... all other cases, each returning StepResult directly ...
        case _:
            return StepResult(step=step, outcome=StepOutcome.FAILED, message="unhandled step kind")
```

No try/except. No `duration_s` tracking (move to executor if needed).

**File: `src/nirip/execution/executor.py`**

The executor catches specific operational exceptions:
```python
import time
from niri_state import WaitTimeoutError

from nirip.execution.handlers import execute_step
from nirip.execution.models import ApplyResult, SessionPorts, StepOutcome, StepResult
from nirip.execution.runtime import AppRuntimeState, SessionRuntime
from nirip.planning.models import Plan
from nirip.spec.models import SessionOptions


async def execute_plan(plan: Plan, ports: SessionPorts, options: SessionOptions) -> ApplyResult:
    """Execute all steps in a plan, applying error policy."""
    t0 = time.monotonic()
    runtime = _init_runtime(plan)
    results: list[StepResult] = []

    for step in plan.steps:
        t_step = time.monotonic()
        try:
            result = await execute_step(step, ports, runtime)
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
        # All other exceptions propagate — they are programming errors, not operational failures.

        if result.duration_s == 0.0:
            result = result.model_copy(update={"duration_s": time.monotonic() - t_step})
        results.append(result)

        if result.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT) and options.stop_on_error:
            break

    return ApplyResult(
        session_name=plan.session_name,
        success=all(r.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED) for r in results),
        steps=results,
        total_duration_s=time.monotonic() - t0,
    )


def _init_runtime(plan: Plan) -> SessionRuntime:
    """Initialize runtime tracking state from plan steps."""
    runtime = SessionRuntime(session_name=plan.session_name, started_at=time.monotonic())
    for step in plan.steps:
        if step.app_name and step.app_name not in runtime.apps:
            runtime.apps[step.app_name] = AppRuntimeState(
                app_name=step.app_name,
                workspace_name=step.workspace_name or "",
            )
    return runtime
```

**Validate:**
```bash
python -m pytest tests/test_executor.py -x
```

---

### D2. Fix `StepResult.window_id` semantics

**Problem:** Spawn handler writes `proc.pid` to `window_id`, overloading a compositor window ID field with a UNIX process ID.

**File: `src/nirip/execution/models.py`**

Add `spawn_pid` field:
```python
class StepResult(NiripModel):
    step: PlanStep
    outcome: StepOutcome
    message: str
    window_id: int | None = None    # compositor window ID
    spawn_pid: int | None = None    # UNIX PID from spawn
    duration_s: float = 0.0
```

**File: `src/nirip/execution/handlers.py`**

In `SpawnWindowStep` handler, change:
```python
return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="spawned", window_id=proc.pid)
```
To:
```python
return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="spawned", spawn_pid=proc.pid)
```

**Validate:**
```bash
python -m pytest tests/ -x
grep -r "window_id=proc" src/  # should return nothing
```

---

### D3. Capture matched window ID during wait

**Problem:** `WaitForWindowStep` handler returns "window appeared" but never records WHICH window matched. Subsequent placement steps (C1) need this ID from `runtime.apps[name].matched_window_id`.

**File: `src/nirip/execution/handlers.py`**

Replace the `WaitForWindowStep` handler:
```python
case WaitForWindowStep():
    matched_wid: int | None = None

    async def wait_predicate(snap: Snapshot) -> bool:
        nonlocal matched_wid
        for w in snap.windows.values():
            is_match, _, _ = evaluate_rule(step.match, w)
            if is_match:
                matched_wid = w.id
                return True
        return False

    await _wait(ports.state, wait_predicate, step.timeout_s)

    # Record into runtime so downstream steps can resolve window_id
    if step.app_name and step.app_name in runtime.apps:
        runtime.apps[step.app_name].matched_window_id = matched_wid

    return StepResult(
        step=step,
        outcome=StepOutcome.COMPLETED,
        message=f"window appeared (id={matched_wid})",
        window_id=matched_wid,
    )
```

**This is the critical link** between C1 (spawn placement) and D3. Without this, `_resolve_window_id` will always find `None` for spawned apps.

**Validate:**

Add to `tests/test_executor.py` (or new file):
```python
async def test_wait_step_captures_window_id(fake_ports, fake_runtime):
    """WaitForWindowStep records matched window ID in runtime state."""
    # Setup: fake_ports.state progression that makes a window appear
    # Assert: runtime.apps["app_name"].matched_window_id == expected_id
    ...
```

---

### D4. Tiered post-action verification

**Problem:** Handlers fire actions and return immediately. No confirmation that the compositor applied the change. Race conditions possible.

**Design:** Not all actions need verification. Some are instantaneous (focus), some are observable (move), some are best-effort (floating toggle).

| Tier | Actions | Strategy |
|------|---------|----------|
| Verify (3-5s) | `EnsureWorkspace`, `MoveWindowToWorkspace` | `wait_until` confirms state change |
| Best-effort (1.5s) | `SetFloating`, `SetTiling`, `SetFullscreen`, `SetMaximized` | `wait_until`, but timeout degrades to COMPLETED (action was sent) |
| No verify | `FocusWindow`, `FocusWorkspace`, `SetColumnWidth`, `SetWindowHeight`, `Spawn` | Return immediately |

**File: `src/nirip/execution/handlers.py`**

For verified actions (example — MoveWindowToWorkspace):
```python
case MoveWindowToWorkspaceStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    workspace_ref = actions.workspace_by_name(step.target_workspace)
    await _request(ports.client, actions.move_window_to_workspace(workspace_ref, window_id=wid))
    # Verify: wait for window to appear in target workspace
    def moved(snap: Snapshot) -> bool:
        w = snap.windows.get(wid)
        target = next((ws for ws in snap.workspaces.values() if ws.name == step.target_workspace), None)
        return w is not None and target is not None and w.workspace_id == target.id
    await _wait(ports.state, moved, timeout=5.0)
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window moved", window_id=wid)
```

For best-effort actions (example — SetFloating):
```python
case SetFloatingStep():
    wid = _resolve_window_id(step, runtime)
    if wid is None:
        return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
    await _request(ports.client, actions.move_window_to_floating(wid))
    # Best-effort verify
    try:
        await _wait(ports.state, lambda snap: (w := snap.windows.get(wid)) is not None and w.is_floating, timeout=1.5)
    except WaitTimeoutError:
        pass  # Action was sent; verification timed out — still report success
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="window set floating", window_id=wid)
```

**Note:** The `WaitTimeoutError` from best-effort verification must NOT propagate to the executor (it would become TIMED_OUT). Catch it locally with an explicit try/except inside the handler — this is the ONE exception to the "no try/except in handlers" rule, and it's local and intentional.

For EnsureWorkspaceStep:
```python
case EnsureWorkspaceStep():
    await _request(ports.client, actions.focus_workspace(step.workspace_name or ""))
    # Verify workspace exists
    await _wait(
        ports.state,
        lambda snap: any(ws.name == step.workspace_name for ws in snap.workspaces.values()),
        timeout=3.0,
    )
    return StepResult(step=step, outcome=StepOutcome.COMPLETED, message="workspace ensured")
```

**Validate:**
```bash
python -m pytest tests/test_executor.py -x
# Manual integration test with real niri:
nirip apply test-session.yaml
```

---

## Phase E: CLI and Facade Cleanup

---

### E1. Remove or simplify `SyncNirip`

**Question to answer before implementing:** Does anything use `SyncNirip`? Check:
```bash
grep -r "SyncNirip" src/ tests/ --include="*.py"
```

**If only tests or nothing:** Remove `src/nirip/facade/sync_nirip.py`. Remove from `src/nirip/__init__.py` exports.

**If keeping:** Replace `asyncio.run()` per-method with a persistent `asyncio.Runner`:

```python
import asyncio
from typing import Any

class SyncNirip:
    def __init__(self, *, state: NiriState, client: NiriClient, config: NiripConfig | None = None) -> None:
        self._async = AsyncNirip(state=state, client=client, config=config)
        self._runner = asyncio.Runner()

    @classmethod
    def open(cls, config: NiripConfig | None = None) -> SyncNirip:
        runner = asyncio.Runner()
        state = runner.run(NiriState.open())
        client = NiriClient.create()
        instance = cls.__new__(cls)
        instance._async = AsyncNirip(state=state, client=client, config=config)
        instance._runner = runner
        return instance

    def diff(self, spec: SessionSpec) -> SessionDiff:
        return self._runner.run(self._async.diff(spec))

    def plan(self, spec: SessionSpec) -> Plan:
        return self._runner.run(self._async.plan(spec))

    def apply(self, spec: SessionSpec) -> ApplyResult:
        return self._runner.run(self._async.apply(spec))

    def capture(self, *, name: str | None = None) -> CapturedSession:
        return self._runner.run(self._async.capture(name=name))

    def close(self) -> None:
        self._runner.run(self._async.close())
        self._runner.close()

    def __enter__(self) -> SyncNirip:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
```

**Validate:**
```bash
python -m pytest tests/ -x
```

---

### E2. Fix blocking `input()` in async context

**Problem:** `src/nirip/cli/commands.py` line 25 calls `input()` inside an async function, blocking the event loop.

**File: `src/nirip/cli/commands.py`**

Replace:
```python
answer = input("Apply? [y/N] ")
```

With:
```python
answer = await asyncio.to_thread(input, "Apply? [y/N] ")
```

Add `import asyncio` at the top if not already imported.

**Validate:**
```bash
python -m pytest tests/ -x
nirip apply test-session.yaml  # manual: confirm prompt still works
```

---

### E3. Add `--dry-run` and structured output formatters

**File: `src/nirip/cli/main.py`**

Add `--dry-run` to the apply subparser:
```python
p_apply.add_argument("--dry-run", action="store_true", help="Show plan without executing")
```

Update dispatch:
```python
if args.command == "apply":
    output = asyncio.run(cmd_apply(args.session_file, yes=args.yes, dry_run=args.dry_run))
```

**File: `src/nirip/cli/commands.py`**

Update `cmd_apply` signature:
```python
async def cmd_apply(session_file: str, *, yes: bool = False, dry_run: bool = False) -> str:
```

Add dry-run path:
```python
if dry_run:
    async with await AsyncNirip.open() as nirip:
        plan = await nirip.plan(validated.spec)
        return format_plan(plan)
```

**New file: `src/nirip/cli/formatting.py`**

```python
"""Human-readable CLI output formatters."""

from __future__ import annotations

from nirip.execution.models import ApplyResult, StepOutcome
from nirip.planning.models import Plan, SessionDiff


def format_diff(diff: SessionDiff) -> str:
    """Format a session diff for terminal display."""
    lines: list[str] = []
    if not diff.has_drift:
        lines.append("No changes needed — session is converged.")
        return "\n".join(lines)

    if diff.already_matched:
        lines.append(f"Matched: {len(diff.already_matched)} app(s)")

    if diff.will_spawn:
        lines.append("Will spawn:")
        for app in diff.will_spawn:
            lines.append(f"  + {app}")

    if diff.will_move:
        lines.append("Will move:")
        for app in diff.will_move:
            lines.append(f"  ~ {app}")

    if diff.will_adjust:
        lines.append("Will adjust:")
        for app in diff.will_adjust:
            lines.append(f"  * {app}")

    if diff.workspace_changes:
        lines.append("Workspace changes:")
        for change in diff.workspace_changes:
            lines.append(f"  {change}")

    if diff.errors:
        lines.append("Errors:")
        for err in diff.errors:
            lines.append(f"  ! {err}")

    return "\n".join(lines)


def format_plan(plan: Plan) -> str:
    """Format a plan for terminal display."""
    if plan.is_empty:
        return "Empty plan — nothing to do."

    lines = [f"Plan: {plan.step_count} step(s)"]
    for i, step in enumerate(plan.steps, 1):
        deps = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
        lines.append(f"  {i}. [{step.kind}] {step.description}{deps}")
    return "\n".join(lines)


def format_result(result: ApplyResult) -> str:
    """Format an apply result for terminal display."""
    lines: list[str] = []
    status = "SUCCESS" if result.success else "FAILED"
    lines.append(f"Result: {status} ({result.total_duration_s:.1f}s)")
    lines.append(f"  Completed: {result.completed_count}, Skipped: {result.skipped_count}")

    if result.failed_steps:
        lines.append("  Failed steps:")
        for fs in result.failed_steps:
            lines.append(f"    - {fs.step.description}: {fs.message}")

    return "\n".join(lines)
```

**Update `cmd_diff`, `cmd_plan`, `cmd_apply`** to use formatters instead of `yaml.dump(model_dump())`:

```python
from nirip.cli.formatting import format_diff, format_plan, format_result

async def cmd_diff(session_file: str) -> str:
    validated = load_spec_from_file(session_file)
    async with await AsyncNirip.open() as nirip:
        diff = await nirip.diff(validated.spec)
        return format_diff(diff)

async def cmd_plan(session_file: str) -> str:
    validated = load_spec_from_file(session_file)
    async with await AsyncNirip.open() as nirip:
        plan = await nirip.plan(validated.spec)
        return format_plan(plan)

async def cmd_apply(session_file: str, *, yes: bool = False, dry_run: bool = False) -> str:
    validated = load_spec_from_file(session_file)
    for w in validated.validation.warnings:
        print(f"  warning: {w}", file=sys.stderr)

    async with await AsyncNirip.open() as nirip:
        if dry_run:
            plan = await nirip.plan(validated.spec)
            return format_plan(plan)

        if not yes:
            diff = await nirip.diff(validated.spec)
            print(format_diff(diff), file=sys.stderr)
            if diff.has_drift:
                answer = await asyncio.to_thread(input, "Apply? [y/N] ")
                if answer.lower() != "y":
                    return "Aborted."

        result = await nirip.apply(validated.spec)
        return format_result(result)
```

**Tests — new file: `tests/test_cli_formatting.py`**

```python
"""Tests for CLI output formatters."""

from nirip.cli.formatting import format_diff, format_plan
from nirip.planning.models import Plan, SessionDiff


def test_format_diff_converged():
    diff = SessionDiff(session_name="test")
    output = format_diff(diff)
    assert "No changes needed" in output


def test_format_diff_with_spawn():
    diff = SessionDiff(session_name="test", will_spawn=["dev/firefox"])
    output = format_diff(diff)
    assert "+ dev/firefox" in output


def test_format_plan_empty():
    plan = Plan(session_name="test", steps=[], resolution=..., warnings=[])
    # You'll need a minimal Resolution here — adjust based on actual constructor
    output = format_plan(plan)
    assert "nothing to do" in output.lower()
```

**Validate:**
```bash
ruff check src/nirip/cli/ tests/test_cli_formatting.py
python -m pytest tests/test_cli_formatting.py -x -v
nirip diff test-session.yaml   # manual: should show readable output
nirip apply --dry-run test-session.yaml  # manual: shows plan
```

---

## Final Validation

After all phases are complete, run the full suite:

```bash
ruff check src/nirip/ tests/
ty check src/nirip/
python -m pytest tests/ -x -v
```

If any failures:
1. Type errors first (often cascade from model changes in C1).
2. Test failures next (usually fixture updates needed).
3. Lint last (formatting, unused imports).

---

## Commit Sequence

```
A1: chore: remove dead SessionOptions fields (mode, match_existing, move_unmatched)
A2: chore: remove _wait compatibility hack, use direct wait_until call
A3: chore: clean up unused conftest fakes
B1: fix: negation-only MatchRule now matches correctly (confidence 0.4)
B2: refactor: type _detect_drift with concrete types, table-driven structure
B3: fix: _parse_size raises PlanningError on invalid input
B4: fix: dependency validator skips DFS when graph has dangling refs
C1: feat: spawned apps receive full placement steps (optional window_id)
C2: feat: depends_on creates inter-app ordering edges in plan
D1: refactor: centralize error handling in executor, remove broad catch from handlers
D2: fix: StepResult.spawn_pid field (window_id no longer overloaded with PID)
D3: feat: WaitForWindowStep captures matched window ID into runtime
D4: feat: tiered post-action verification (critical/best-effort/fire-and-forget)
E1: refactor: SyncNirip uses asyncio.Runner (or removed)
E2: fix: replace blocking input() with asyncio.to_thread
E3: feat: CLI formatters and --dry-run flag
```

---

## Acceptance Checklist

- [ ] `SessionOptions` has exactly 3 fields.
- [ ] No `TypeError`-catching `_wait` hack exists.
- [ ] `evaluate_rule` returns `(True, 0.4, ...)` for satisfied negation-only rules.
- [ ] `_detect_drift` signature uses `Window`, `NormalizedApp` (no `object`).
- [ ] `_parse_size("px:abc")` raises `PlanningError`.
- [ ] Dependency validator reports clear error, skips DFS on incomplete graph.
- [ ] All 8 placement step types have `window_id: int | None`.
- [ ] Compiler emits placement steps for MISSING/spawned apps.
- [ ] Executor resolves `window_id=None` from `runtime.apps[name].matched_window_id`.
- [ ] `depends_on` produces ordering edges in compiled plans.
- [ ] No `except Exception` outside `executor.py`.
- [ ] `StepResult` has separate `window_id` and `spawn_pid`.
- [ ] `WaitForWindowStep` handler persists matched window ID into runtime.
- [ ] Move/ensure steps verify state; float/fs/max degrade gracefully on timeout.
- [ ] `SyncNirip` uses `asyncio.Runner` or is deleted.
- [ ] `input()` call uses `asyncio.to_thread`.
- [ ] CLI uses structured formatters, not `yaml.dump`.
- [ ] `--dry-run` flag shows plan without executing.
- [ ] `ruff check`, `ty check`, `pytest` all pass.
