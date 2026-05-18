# NIRIP Refactoring Ideas

Focused on reducing mental overhead, eliminating unnecessary indirection, and making the codebase maximally legible. No backwards compatibility concerns.

---

## 1. Kill the `SessionDiff` Model — It's Just a View of `Resolution`

**Problem:** `SessionDiff` is a second representation of the same information that `Resolution` already contains. `compile_diff` transforms `Resolution` → `SessionDiff` by walking the exact same tree and categorizing apps by status. But `Resolution` already *has* this info via its computed fields (`unmatched_apps`, `ambiguous_apps`, `has_drift`).

**The developer must keep two models in their head** when they're really the same data viewed differently. The diff is purely presentational — it belongs in the formatting layer, not the planning layer.

**Refactor:**
- Delete `SessionDiff` and `compile_diff`
- Move the categorization logic into `cli/formatting.py` as `format_resolution()`
- The facade's `diff()` method just returns `Resolution` directly
- If the categorized summary is needed programmatically, add methods to `Resolution` itself

**Result:** One fewer model, one fewer file-crossing concept, planning module focuses only on planning.

---

## 2. Flatten the Resolution Nesting — Remove `WorkspaceResolution` as Container

**Problem:** The current structure is:
```
Resolution
  └ workspace_resolutions: list[WorkspaceResolution]
      ├ name, exists, output_correct, ...
      └ app_resolutions: list[AppResolution]
          ├ app_name, workspace_name, status, ...
```

Every consumer of this data immediately flattens it: `all_app_resolutions`, `compile_plan` iterates both levels, `compile_diff` iterates both levels. The nesting adds cognitive load without value — `AppResolution` already carries `workspace_name`.

**Refactor:**
```python
class Resolution(NiripModel):
    session_name: str
    workspaces: list[WorkspaceState]  # workspace-level facts only
    apps: list[AppResolution]         # flat list, each knows its workspace
    warnings: list[str]
```

Where `WorkspaceState` is just:
```python
class WorkspaceState(NiripModel):
    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    focus: bool
```

**Result:** Every consumer just iterates `resolution.apps` — no nested loops, no `all_app_resolutions` helper. The workspace facts are queried by name when needed.

---

## 3. Unify PlanStep Into a Single Dataclass With a `kind` Enum

**Problem:** 9 separate step classes that each carry `id`, `description`, `depends_on`, `app_name`, `workspace_name` — with the actual payload being 1-3 unique fields per variant. The discriminated union is clever, but:
- Reading `builder.py` requires knowing the constructor signature of each
- `handlers.py` pattern-matches on 9 types
- Adding a new step kind requires touching 4+ files (models, builder, handlers, predicates)
- Steps that operate on windows all redundantly carry `window_id: int | None`

The 9-class hierarchy is the single biggest source of mental overhead in the codebase.

**Refactor:** A single `PlanStep` with an enum `kind` and a typed payload:

```python
class StepKind(StrEnum):
    CREATE_WORKSPACE = "create_workspace"
    MOVE_WORKSPACE_TO_OUTPUT = "move_workspace_to_output"
    SPAWN_WINDOW = "spawn_window"
    WAIT_FOR_WINDOW = "wait_for_window"
    MOVE_WINDOW = "move_window"
    SET_STATE = "set_state"
    RESIZE = "resize"
    FOCUS_WINDOW = "focus_window"
    FOCUS_WORKSPACE = "focus_workspace"

class PlanStep(NiripModel):
    id: str
    kind: StepKind
    description: str
    depends_on: list[str] = Field(default_factory=list)
    # Context
    app_name: str | None = None
    workspace_name: str | None = None
    window_id: int | None = None
    # Payload (sparse — only relevant fields populated per kind)
    command: list[str] | str | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False
    match: MatchRule | None = None
    timeout_s: float | None = None
    target_output: str | None = None
    property: WindowProperty | None = None
    value: bool = True
    axis: ResizeAxis | None = None
    proportion: float | None = None
    pixels: int | None = None
```

**Trade-off:** Loses compile-time field exhaustiveness checks on construction. But gains:
- Single type to understand
- Handler becomes a simple `if step.kind == ...` dispatch without destructuring
- Builder becomes much simpler (just sets fields on a dict)
- No discriminator magic

**Alternative (less radical):** Keep the union but remove `StepBase` — make each variant a flat standalone class with only its own fields plus `id`/`kind`/`depends_on`. Remove `app_name`/`workspace_name` from the base (put them only where relevant).

---

## 4. Merge `resolver.py` and `matcher.py` — They're One Concept

**Problem:** The resolve module has 4 files for what is conceptually one operation: "given a spec and a snapshot, figure out which windows belong to which apps."

- `matcher.py` — evaluates rules and assigns windows
- `resolver.py` — calls matcher, detects drift, builds Resolution
- `assigner.py` — 36-line class for greedy assignment
- `models.py` — the types

The developer must trace through 3 files (resolver → matcher → assigner) to understand what `resolve()` does. The separation is premature — `GreedyAssigner` is 20 lines of logic that will never be swapped out.

**Refactor:**
- Inline `GreedyAssigner.assign()` into `matcher.py` as a module-level function
- Merge `matcher.py` into `resolver.py` — one file, `resolve.py` (not a package)
- Keep `models.py` as a separate file if needed, or inline the small models

**Result:** `resolve/` becomes either a single `resolve.py` file or a 2-file package (models + logic). One file to read to understand the entire matching and resolution process.

---

## 5. Remove `_base.py` — Inline the Config Into Each Module

**Problem:** `_base.py` exists solely to define:
```python
class NiripModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
```

Every model file imports from `_base`. This 4-line file adds a layer of indirection. If you see a class inheriting `NiripModel` you have to check what it does.

**Refactor:** Define the config inline in each models file, or use a module-level constant:

```python
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

class MatchRule(BaseModel):
    model_config = _MODEL_CONFIG
    ...
```

Or even simpler — just repeat `model_config = ConfigDict(extra="forbid", frozen=True)` in each class. It's 1 line. Repetition of a config declaration is less costly than indirection.

**Alternative:** If you want DRY, keep `_base.py` but rename it to something self-documenting like `_frozen_model.py` or just document the convention in the module docstring.

---

## 6. Simplify the Builder — Make It a Pure Function, Not a Class

**Problem:** `PlanBuilder` is a stateful class with 5 methods that must be called in a specific order:
1. `ensure_workspace` (per workspace)
2. `spawn_app` + `place_window` (per app)
3. `focus_workspace` (per focused workspace)
4. `wire_app_dependencies` (once, at end)
5. `build` (once, at end)

The caller (`compile_plan`) must orchestrate this sequence correctly. If you call `build()` before `wire_app_dependencies()`, you get wrong results silently.

**Refactor:** Make it a single function that takes the resolution and returns steps:

```python
def build_steps(resolution: Resolution, options: SessionOptions) -> list[PlanStep]:
    steps = []
    app_spans = {}  # track first/last step per app

    for wr in resolution.workspace_resolutions:
        # workspace steps
        ...
        for ar in wr.app_resolutions:
            # app steps
            ...

    # wire inter-app deps
    ...

    return topological_sort(steps)
```

This removes the "protocol" of calling methods in order. Everything is in one function where the control flow is visible.

**Result:** `compile_plan` becomes trivial — it just calls `build_steps(resolution, options)` and wraps in a `Plan`. Or better, `compile_plan` *is* `build_steps` and `Plan` is constructed at the call site.

---

## 7. Collapse `_emit_state_steps` Repetition With Data-Driven Approach

**Problem:** `_emit_state_steps` in builder.py has the same pattern repeated 3 times:
```python
needs_X = any(d.kind == DriftKind.WRONG_X for d in ar.drift)
if not needs_X and ar.status == ResolutionStatus.MISSING:
    needs_X = ar.spec.placement.X
if needs_X:
    self._track(SetWindowStateStep(...))
```

This is classic "rule of three" — extract it.

**Refactor:**
```python
_STATE_DRIFT_MAP = [
    (DriftKind.WRONG_FLOATING, "floating", WindowProperty.FLOATING, WindowProperty.TILING),
    (DriftKind.WRONG_FULLSCREEN, "fullscreen", WindowProperty.FULLSCREEN, None),
    (DriftKind.WRONG_MAXIMIZED, "maximized", WindowProperty.MAXIMIZED, None),
]

for drift_kind, placement_attr, prop_true, prop_false in _STATE_DRIFT_MAP:
    has_drift = any(d.kind == drift_kind for d in ar.drift)
    desired = getattr(ar.spec.placement, placement_attr)
    if has_drift or (ar.status == ResolutionStatus.MISSING and desired):
        prop = prop_true if desired else (prop_false or prop_true)
        # emit step
```

**Result:** Adding a new window property (e.g., `always_on_top`) is a one-line table addition, not a 10-line block copy.

---

## 8. Remove `execution/predicates.py` and `execution/_checks.py` — Inline Into Handler

**Problem:** Two tiny files (15 and 36 lines) that exist solely to be called from one place (`execute_step`). The developer has to cross 3 files to understand skip logic:
1. `execute_step` calls `is_already_satisfied`
2. `is_already_satisfied` calls `STATE_CHECKS`
3. `STATE_CHECKS` has the lambda implementations

**Refactor:** Inline `is_already_satisfied` as a helper at the top of `handlers.py`. Put `STATE_CHECKS` in `handlers.py` as well — it's already imported there for the SetWindowState handler.

**Result:** Execution handler logic lives in one file. Two fewer files, two fewer import chains.

---

## 9. Make `AsyncNirip.open()` the Only Way to Create Instances

**Problem:** `AsyncNirip` has both `__init__` (takes pre-made state+client) and `open()` (creates them). The `__init__` path requires the caller to manage NiriState/NiriClient lifecycle manually, which is fragile. The `__aenter__`/`__aexit__` methods on the instance duplicate what `open()` already provides.

**Refactor:** Make `AsyncNirip` a simple namespace that you get from the context manager. Remove `__init__` from public API:

```python
@asynccontextmanager
async def open_nirip(config: NiripConfig | None = None) -> AsyncIterator[Nirip]:
    state = await NiriState.open()
    client = NiriClient.create()
    try:
        yield Nirip(state=state, client=client, config=config or NiripConfig())
    finally:
        await state.close()
        await client.close()
```

Or keep the class but make `__init__` private (underscore) and only expose `open()`.

**Result:** One way to use the system. No lifecycle ambiguity.

---

## 10. Remove `NiripConfig` — It's Unused Baggage

**Problem:** `NiripConfig` has 4 fields:
- `session_dir` — never read anywhere in the codebase
- `state_dir` — never read anywhere in the codebase
- `default_timeout_s` — never read anywhere (spec has its own)
- `confirm_before_apply` — never read anywhere (CLI handles this independently)

It's threaded through `AsyncNirip`, the sync wrappers, and the facade, but **nothing ever reads its fields**.

**Refactor:** Delete it. If/when you actually need config, add it then. Currently it's dead weight that suggests the system is configurable when it isn't.

**Result:** Removes a parameter from 4 function signatures. Removes a file. Removes a concept from the mental model.

---

## 11. Flatten `spec/` Into a Single File

**Problem:** The spec module is 4 files:
- `models.py` (93 LOC) — the types
- `validators.py` (160 LOC) — validation functions
- `loader.py` (44 LOC) — YAML loading
- `__init__.py` (15 LOC) — re-exports

Total: 312 LOC. This is small enough to be a single file without losing clarity. The separation into 4 files means understanding "how does spec loading work" requires opening 3 files.

**Refactor:** Merge into `spec.py` (not a package). Order: models → validation → loading. ~300 lines, entirely self-contained.

**Alternative:** Keep `models.py` separate if you want to import types without pulling in yaml/re dependencies. But given Python's import system, this optimization rarely matters.

---

## 12. Remove the `capture/` Module's Indirection

**Problem:** `capture/` has:
- `capturer.py` (45 LOC) — `capture_from_snapshot` + `CapturedSession` model
- `inference.py` (23 LOC) — `infer_app_name` + `infer_match_rule`
- `__init__.py` (5 LOC)

73 lines across 3 files. The "inference" module is two tiny functions that are only called from `capturer.py`.

**Refactor:** Single file `capture.py`. Inline the inference functions — they're 5 lines each.

---

## 13. Rethink the Execution Module's File Split

**Problem:** The execution module is split into:
- `executor.py` (72 LOC) — the plan loop
- `handlers.py` (221 LOC) — the big match statement
- `runtime.py` (28 LOC) — mutable state tracking
- `hooks.py` (43 LOC) — hook protocol + implementations
- `predicates.py` (36 LOC) — skip checks
- `_checks.py` (15 LOC) — state lambdas
- `models.py` (59 LOC) — StepResult, ApplyResult, SessionPorts

7 files for one conceptual operation: "execute a plan."

**Refactor:**
- `execution/engine.py` — the plan loop + step dispatch (merge executor + handlers + predicates + _checks)
- `execution/models.py` — keep as-is (types are useful standalone)
- `execution/hooks.py` — keep as-is (protocol is a clean extension point)
- Delete `runtime.py` — inline `SessionRuntime`/`AppRuntimeState` into engine.py (they're only used there)

**Result:** 4 files → 3 files, and the core logic (the thing you actually debug) is in one place.

---

## 14. Drop `computed_field` Proliferation — Use Regular Methods

**Problem:** `computed_field` on frozen Pydantic models makes properties appear in serialized output (`.model_dump()`). This is useful for API responses but adds overhead:
- Every access recomputes (no caching)
- Appears in `__repr__` and `.model_dump()`, making debug output noisy
- Requires `@property` decorator stacking which is visually heavy

Examples: `Resolution.all_app_resolutions`, `Plan.step_count`, `Plan.is_empty`, `ApplyResult.completed_count`

Most of these are never serialized — they're only used in-process.

**Refactor:** Replace with plain `@property` (no `@computed_field`). If serialization is needed for specific fields, add them back selectively.

`Plan.step_count` and `Plan.is_empty` should just be deleted — callers can use `len(plan.steps)` and `not plan.steps` directly. Don't wrap trivial attribute access in abstractions.

---

## 15. Simplify the `__init__.py` Public API

**Problem:** The top-level `__init__.py` exposes 11 names in `__all__` including both the async facade and sync wrappers. The sync wrappers (`apply_session`, `plan_session`, `diff_session`) are all 5-line functions that just `asyncio.run(async_func())`.

**Refactor:** Either:
1. Remove sync wrappers entirely — users who want sync can do `asyncio.run()` themselves
2. Or keep them but remove the facade from public API — make users choose sync *or* async, not both

The current API surface asks "which of these 3 ways do I use nirip?" Having one obvious way reduces decision fatigue.

---

## 16. Kill `errors.py` Hierarchy — Use Fewer, Simpler Exceptions

**Problem:** 6 exception classes for a library with 2,316 lines of code:
- `NiripError`
- `SpecError`
- `SpecValidationError`
- `PlanningError`
- `CycleError`
- `CaptureError`
- `NiripConnectionError`

Only `SpecError`/`SpecValidationError` are actually raised. `CaptureError` and `NiripConnectionError` are never raised anywhere. `CycleError` is raised in one place.

**Refactor:** Two exceptions:
```python
class NiripError(Exception):
    """Something went wrong."""

class ValidationError(NiripError):
    """Spec is invalid."""
    def __init__(self, errors: list[str], warnings: list[str] | None = None): ...
```

Raise `NiripError("cycle detected: ...")` instead of a dedicated `CycleError` class. Delete unused exceptions.

---

## 17. Remove `WindowAssigner` Protocol — YAGNI

**Problem:** `WindowAssigner` is a protocol that `GreedyAssigner` implements. But:
- There is exactly one implementation
- There is no user-facing way to provide an alternative
- The protocol adds indirection without value

**Refactor:** Delete the protocol. Make `assign_windows` use the greedy algorithm directly (inline the 20 lines). If a second strategy is ever needed, extract at that point.

---

## Summary: Proposed File Structure After Refactoring

```
src/nirip/
├── __init__.py          # Public API (slimmed)
├── __main__.py          # CLI entry
├── spec.py              # Models + validation + loading (was spec/)
├── resolve.py           # Matching + resolution + drift (was resolve/)
├── plan.py              # Step building + compilation + ordering (was planning/)
├── execution/
│   ├── __init__.py
│   ├── engine.py        # Plan loop + step handlers + runtime
│   ├── models.py        # StepResult, ApplyResult, SessionPorts
│   └── hooks.py         # ExecutionHook protocol + impls
├── capture.py           # Snapshot → spec scaffold (was capture/)
├── facade.py            # AsyncNirip (was facade/)
└── cli/
    ├── __init__.py
    ├── main.py          # Argparse
    └── commands.py      # Command handlers + formatting (merge formatting in)
```

**From 41 files → ~14 files.** Each file is self-contained and readable top-to-bottom.

---

## Priority Ranking

| # | Idea | Impact on Mental Overhead | Effort |
|---|------|--------------------------|--------|
| 1 | Kill SessionDiff | High — removes parallel model | Low |
| 10 | Remove NiripConfig | High — removes dead concept | Very Low |
| 4 | Merge resolver+matcher | High — one concept, one file | Medium |
| 6 | Builder → pure function | High — removes stateful protocol | Medium |
| 8 | Inline predicates/_checks | Medium — fewer files to trace | Very Low |
| 14 | Drop computed_field abuse | Medium — cleaner models | Low |
| 3 | Unify PlanStep types | Very High — biggest simplification | High |
| 2 | Flatten Resolution nesting | Medium — simpler iteration | Medium |
| 11 | Flatten spec/ | Medium — one file to understand | Low |
| 12 | Flatten capture/ | Low — it's already small | Very Low |
| 17 | Remove WindowAssigner | Low — removes unused abstraction | Very Low |
| 16 | Simplify exceptions | Low — fewer types to know | Very Low |
| 5 | Remove _base.py | Very Low — cosmetic | Very Low |
| 7 | Data-driven state steps | Medium — removes repetition | Low |
| 9 | Simplify AsyncNirip | Low — API clarity | Low |
| 13 | Consolidate execution files | Medium — fewer files | Medium |
| 15 | Simplify public API | Low — less decision fatigue | Low |

---

## The "Nuclear Option" — Maximum Simplification

If you were to start from scratch with the same functionality, the entire library could be:

```
src/nirip/
├── __init__.py      # Public API
├── spec.py          # ~300 LOC: models + validation + YAML loading
├── resolve.py       # ~300 LOC: matching + drift detection + resolution
├── plan.py          # ~350 LOC: step generation + ordering
├── execute.py       # ~300 LOC: async execution engine
├── capture.py       # ~70 LOC: snapshot export
└── cli.py           # ~180 LOC: argparse + commands + formatting
```

6 files, ~1,500 LOC total (down from 41 files, 2,316 LOC). Each file is independently comprehensible. The reduction comes from:
- Eliminating re-export `__init__.py` files (6 files)
- Merging split-within-module files (12 files)
- Removing dead code (NiripConfig, unused exceptions, WindowAssigner protocol)
- Replacing verbose computed_fields with inline expressions
- Combining related functions instead of spreading across files
