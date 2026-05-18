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


---


### 2.5 [CONSISTENCY] `ws_by_name` type annotation says `Workspace` but it's `Any` at runtime

```python
def _detect_drift(
    window: Window,
    app_spec: AppSpec,
    ws_name: str,
    ws_by_name: dict[str, Workspace],
) -> list[DriftItem]:
```

In tests, `FakeWorkspace` is passed. The type annotation `Workspace` is from `niri_pypc.types.generated.models` but the function uses duck typing (`.id`, `.output`). This is fine for duck-typing, but the import of `Workspace` at module level is then only used for this annotation. Could use a `Protocol` to fix?

### 2.6 [SIMPLIFY] `_PROPERTY_CHECKS` table in resolve vs `_STATE_DRIFT_MAP` table in plan

Two different lookup tables for the same conceptual mapping (drift kind → window property). `_PROPERTY_CHECKS` maps `(DriftKind, win_attr, place_attr)`. `_STATE_DRIFT_MAP` maps `(DriftKind, place_attr, true_prop, false_prop)`. They encode the same domain knowledge in different shapes. This is a subtle duplication of the "floating/fullscreen/maximized" mapping. Can this be abstracted and extracted for additional simplicity?

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
