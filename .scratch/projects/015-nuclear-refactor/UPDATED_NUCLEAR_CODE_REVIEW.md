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

### 1.6 [SIMPLIFY] Validation functions take mutable lists as out-params

Every `_check_*` function mutates external `errors` and `warnings` lists. This is a C-style pattern. A more Pythonic approach: each returns its own list, and the caller concatenates. But this is a *style* preference — the current approach works fine and avoids allocation. Acknowledge it as a deliberate choice.

---

### 2.2 [DESIGN] `_assign` is O(A × W) with an O(A × W log(A × W)) sort

The assignment algorithm builds all (app, window, tier) triples, sorts them, then greedily assigns. This is fine for desktop-scale data (tens of apps, hundreds of windows). But it's worth noting: for N apps and M windows, it's O(NM log NM). The v1 `GreedyAssigner` was the same, so no regression.

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

### 3.5 [CONSISTENCY] `_topological_sort` uses `sorted()` for determinism

```python
queue: deque[str] = deque(sorted([sid for sid, degree in indegree.items() if degree == 0]))
```

Good — deterministic ordering. But `sorted(edges[sid])` sorts by string, which means `"create_workspace-2"` sorts before `"spawn_window-1"`. The order is deterministic but not semantically meaningful. This is fine — just noting it's lexicographic, not priority-based.

---

### 4.3 [DESIGN] `_NullHook` could be simpler

The `_NullHook` class exists solely because `hook: ExecutionHook | None` needs a fallback. An alternative: make `hook` non-optional with a default factory, or use a conditional call pattern. The current approach is fine — it's the standard Null Object pattern.

### 4.8 [CONSISTENCY] `os` imported but `os.environ` used only once

```python
env = os.environ.copy()
env.update(step.env)
```

Fine — just noting the import is minimal usage.

---

### 5.1 [DESIGN] Cleanest file in the codebase

Nothing to critique. 37 lines, clear purpose, no unnecessary abstraction. This is the reference standard the other files should aspire to.

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

### 7.2 [SIMPLIFY] `__all__` is well-curated

Good: exactly the right symbols. No over-export, no under-export. The public API is: 2 errors, 3 domain types, 4 pipeline functions, 1 convenience function. Clean.

---

