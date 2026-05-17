# Refactoring Plan: Extract Common Patterns from Handlers

## Context

The codebase has solid architecture (6-phase pipeline, clean layer separation), but `execution/handlers.py` contains significant repetition across step handlers. Several handlers follow near-identical patterns (resolve window → send request → wait for state → return result), making the dispatch logic harder to scan and maintain. `predicates.py` has a smaller version of the same issue.

## Target Files

- `src/nirip/execution/handlers.py` (268 lines → ~180 lines) — **primary target**
- `src/nirip/execution/predicates.py` (51 lines → ~35 lines) — **secondary target**

## Refactoring: `handlers.py`

### Pattern 1: "Window state toggle" (4 handlers)

`SetFloatingStep`, `SetTilingStep`, `SetFullscreenStep`, `SetMaximizedStep` all follow:
```
1. resolve window ID (fail if None)
2. send one action request
3. wait for predicate with timeout (swallow WaitTimeoutError)
4. return StepResult(COMPLETED, message, window_id)
```

**Extract:** `_execute_window_state_step(step, ports, runtime, action, predicate_fn, message)` helper that does all 4 steps. Each case becomes a 5-line call.

### Pattern 2: "Window sizing" (2 handlers)

`SetColumnWidthStep` and `SetWindowHeightStep` share:
```
1. resolve window ID (fail if None)
2. build size change from proportion/pixels
3. send request
4. return StepResult
```

**Extract:** `_build_size_change(step)` to compute the `actions.size_set_*` value from proportion/pixels fields (shared between both).

### Pattern 3: Repeated "resolve or fail" guard

8 handlers do:
```python
wid = _resolve_window_id(step, runtime)
if wid is None:
    return StepResult(step=step, outcome=StepOutcome.FAILED, message="window ID not yet available")
```

**Extract:** `_require_window_id(step, runtime)` that raises a small sentinel or returns `StepResult | int`. The cleanest approach: have it return the int directly and use a try/except or Optional pattern at the call site — but since we're already extracting the state-step helper, most call sites disappear anyway.

### Resulting structure

```python
# helpers (new, top of file)
async def _execute_window_state_step(step, ports, runtime, action_fn, check_fn, message) -> StepResult
def _build_size_change(step) -> Any

# match statement cases become:
case SetFloatingStep():
    return await _execute_window_state_step(
        step, ports, runtime,
        action_fn=lambda wid: actions.move_window_to_floating(wid),
        check_fn=lambda w: w.is_floating,
        message="window set floating",
    )
# ... similar one-liners for SetTiling, SetFullscreen, SetMaximized
```

## Refactoring: `predicates.py`

Extract a `_check_window(step, snapshot, predicate)` helper:
```python
def _check_window(step, snapshot, predicate):
    if step.window_id is None:
        return False
    w = snapshot.windows.get(step.window_id)
    return w is not None and predicate(w)
```

Then each case becomes: `case SetFloatingStep(): return _check_window(step, snapshot, lambda w: w.is_floating)`

## What We're NOT Touching (and why)

- **`compiler.py`**: Already reasonably structured. The inner loop sections each have slightly different conditions (drift-based vs always-apply). Table-driving it would obscure the logic. `_emit_float_tiling` is already extracted as a pattern to follow if more extraction is needed later.
- **`matcher.py`**: The rule evaluation has different comparison logic per field (exact vs regex, different confidence values). A table-driven approach adds indirection without reducing cognitive load for 5 cases.

## Verification

1. Run existing tests: `pytest tests/`
2. The refactoring is purely mechanical — same logic, just deduplicated into helpers. No behavioral changes.
