# Nirip Concept Review: NIRIP_CONCEPT.md vs Deep Research Analysis

A comparative analysis of the two concept documents, their architectural differences, and a final recommendation for how to build Nirip.

---

## 1. Documents under review

- **NIRIP_CONCEPT.md** (mine) — A concrete, implementation-oriented concept with full Pydantic model definitions, YAML examples, package layout, CLI commands, and integration code samples.
- **Nirip_Architecture_Concepting-Deep_Research.md** (intern's) — An analytical architecture review that evaluates the dependency libraries, critiques the earlier concept notes, and proposes structural improvements with emphasis on internal layering and separation of concerns.

---

## 2. Where they agree

Both documents converge strongly on the following points:

### 2.1 Foundational architecture
Both agree that nirip should be built **on top of** `niri-pypc` and `niri-state`, not alongside them. Neither proposes duplicating protocol handling, state reduction, or event stream management. Both explicitly reject the old Nim-era idea of nirip owning its own `protocol/` or `state/` packages.

### 2.2 Core product identity
Both describe nirip as a **declarative session reconciler**, not a macro runner. Both use the tmuxp analogy as inspiration, not as a blueprint. Both emphasize reconciliation-first (match before spawn, skip what's already correct, idempotent re-apply).

### 2.3 Event-driven execution
Both reject sleep-based automation in favor of event-verified execution using `niri-state`'s snapshot subscriptions and waiter utilities.

### 2.4 Pydantic-first modeling
Both agree on Pydantic v2 for all user-facing models: specs, plans, diffs, results, capture output.

### 2.5 Matching philosophy
Both prioritize stable identifiers (`app_id` > title > regex), require explainable match decisions, and surface ambiguity explicitly rather than silently picking wrong.

### 2.6 Capture as scaffold
Both agree capture produces a starting template, not a perfect replay artifact.

### 2.7 Async core, sync facade
Both agree the internal engine should be async (matching the async dependencies), with thin sync wrappers for CLI and simple scripting.

### 2.8 Scope boundaries
Both exclude exact geometry replay, app-specific integrations, multi-version niri compatibility, and non-niri compositors from v1.

### 2.9 Implementation phasing
Both propose: spec/matching first → diff/plan → execution → capture → polish. The deep research is more explicit about why this order matters (forces domain language to crystallize before execution code is written).

---

## 3. Where they differ

### 3.1 Internal layering: two stages vs three stages

**NIRIP_CONCEPT.md** uses a two-stage internal pipeline:
```
spec → plan (matching + step generation) → execution
```
The planner takes a `SessionSpec` + `Snapshot`, runs matching internally, and emits a flat list of `PlanStep` objects.

**Deep Research** proposes a three-stage pipeline with explicit intermediate representations:
```
spec → normalized intent → resolution (matching) → compiled plan → execution
```

With three distinct model layers:
1. **Normalized intent** — spec after defaults, inheritance, and reference resolution
2. **Resolution** — which live entities match, are missing, drifted, or ambiguous
3. **Execution** — imperative steps compiled from the resolution

| Aspect | NIRIP_CONCEPT | Deep Research |
|---|---|---|
| Internal stages | 2 (plan + execute) | 3 (normalize + resolve + compile) |
| Match results | Embedded in Plan | Standalone Resolution model |
| Diff derivation | Separate PlanDiff type | Falls out naturally from Resolution |

**Pros of three-stage approach:**
- `diff` becomes a first-class view of the Resolution, not a reformatted Plan
- Resolution model is independently testable without plan compilation
- Normalization catches spec problems (missing defaults, conflicting references) before matching begins
- Cleaner separation of "what matched?" from "what should we do about it?"

**Cons of three-stage approach:**
- More types to define and maintain
- More conceptual overhead for contributors
- Risk of over-engineering if the intermediate representations don't earn their keep

**Implication:** The three-stage split is worth adopting. The key insight is that Resolution is a genuinely different concern from Plan compilation. In the two-stage design, `PlanDiff` is an awkward afterthought — you generate a full plan and then strip it down for display. In the three-stage design, diff is just "show the Resolution," which is more natural and more informative.

---

### 3.2 Spec model structure: apps nested vs apps top-level

**NIRIP_CONCEPT.md** nests apps inside workspaces:
```yaml
workspaces:
  - name: code
    apps:
      - name: editor
        match: ...
        spawn: ...
```

**Deep Research** proposes both workspace-level and top-level app lists:
```python
class SessionSpec(BaseModel):
    workspaces: tuple[WorkspaceSpec, ...]
    apps: tuple[AppSpec, ...] = ()  # top-level apps with target.workspace
```

Where `WorkspaceSpec` has no `apps` field — apps declare their workspace via `target.workspace`.

| Aspect | NIRIP_CONCEPT | Deep Research |
|---|---|---|
| App location | Nested under workspace | Top-level with target reference |
| Workspace spec | Contains apps list | Pure workspace declaration |
| YAML ergonomics | More intuitive grouping | Flatter, more flexible |

**Pros of nested (NIRIP_CONCEPT):**
- More intuitive YAML structure — you see all apps for a workspace together
- No need for apps to repeat their workspace name
- Clearer mental model for users coming from tmuxp

**Pros of top-level (Deep Research):**
- Apps that might move between workspaces are easier to express
- Workspace spec stays purely declarative (name, output, focus)
- Normalization pass can validate workspace references centrally

**Implication:** The nested approach is better for user-facing YAML. Most users think "workspace X should have apps A, B, C" — nesting reflects that mental model. Internally, normalization can flatten apps into a list with workspace references if the engine prefers it. This is a presentation/normalization split, not a fundamental architecture difference.

**GO WITH NESTED**

---

### 3.3 Naming: `AppSpec.name` vs `AppSpec.key`

**NIRIP_CONCEPT.md** uses `name: str` as the app identifier.
**Deep Research** uses `key: str`.

| Aspect | `name` | `key` |
|---|---|---|
| YAML readability | `name: editor` reads naturally | `key: editor` is slightly more technical |
| Semantic clarity | Could be confused with display name | Clearly an identifier |
| Consistency | Matches `WorkspaceSpec.name` | Distinguishes identity from display |

**Implication:** Minor. `name` is fine for YAML ergonomics. If we need a separate display label later, we can add a `label` field. No action needed.

---

### 3.4 Placement model: `PlacementSpec` vs `TargetSpec`

**NIRIP_CONCEPT.md** uses `PlacementSpec` with `floating`, `focus`, `column_width`, `window_height`.

**Deep Research** proposes `TargetSpec` which could include `workspace`, `output`, `floating`, `fullscreen`, `maximized`, `focus`. It also argues output affinity should be a workspace concern first, with per-app output only as a normalized shorthand.

| Aspect | NIRIP_CONCEPT | Deep Research |
|---|---|---|
| Per-app workspace | Implicit (nested under workspace) | Explicit `target.workspace` |
| Per-app output | Not supported | Supported but normalized away |
| Fullscreen/maximized | Not modeled | Included |

**Pros of Deep Research approach:**
- More complete (fullscreen, maximized are real placement concerns)
- Explicit about output being workspace-level

**Pros of NIRIP_CONCEPT approach:**
- Simpler for v1 — fullscreen/maximized can be added later
- No ambiguity about where output is specified

**Implication:** Add `fullscreen` and `maximized` to `PlacementSpec`. Keep output as workspace-level only. This is the right merge of both approaches.

---

### 3.5 Package layout

**NIRIP_CONCEPT.md:**
```
spec/ matching/ planning/ execution/ capture/ state/ cli/
```

**Deep Research:**
```
spec/ model/ resolve/ planning/ execution/ capture/ observe/ facade/ cli/
```

Key differences:

| NIRIP_CONCEPT | Deep Research | Notes |
|---|---|---|
| `matching/` | `resolve/` | DR splits matching, ambiguity, normalization, workspace refs |
| `planning/` | `planning/` | Same concept, DR adds `ordering.py` and `policies.py` |
| `client.py` | `facade/async_client.py` + `facade/sync_client.py` | DR separates async/sync facades explicitly |
| `state/managed.py` | (in `execution/runtime.py`) | DR keeps runtime state closer to executor |
| — | `observe/` | DR adds explicit observation layer over niri-state |
| — | `model/` | DR adds output models (diff, plan, apply, capture, doctor) |

**Pros of Deep Research layout:**
- `resolve/` as a standalone package makes matching independently testable
- `observe/` wrapping niri-state selectors/waiters gives nirip a stable internal API if niri-state changes
- `model/` centralizes output types (good for serialization/CLI)
- `facade/` makes async-first explicit

**Cons of Deep Research layout:**
- `observe/` might be unnecessary indirection — niri-state's API is already clean
- `model/` package containing diff, plan, apply, capture models is a grab-bag
- More packages = more `__init__.py` files and import paths

**Implication:** The `resolve/` split is worth adopting. The `observe/` layer is over-engineering — we should import niri-state directly. The `model/` package should be distributed: each subsystem owns its own models (as in NIRIP_CONCEPT). The `facade/` split is clean and worth adopting.

---

### 3.6 Step definition model

**NIRIP_CONCEPT.md** defines steps as a flat `PlanStep` with `kind: StepKind` enum and `metadata: dict`.

**Deep Research** proposes steps defined as:
- An optional request to issue
- A predicate over Snapshot that says the step is complete
- An optional failure predicate
- A timeout and ambiguity policy
- Structured recording

| Aspect | NIRIP_CONCEPT | Deep Research |
|---|---|---|
| Step structure | Enum + metadata dict | Predicate-driven protocol |
| Type safety | Metadata is untyped | Predicates are typed callables |
| Extensibility | New StepKind enum value | New step class |
| Readability | Step kinds are self-documenting | Predicate logic may be opaque |

**Pros of predicate-driven steps:**
- Each step is self-contained: it knows how to verify itself
- No giant switch statement in the executor
- Failure predicates prevent waiting the full timeout when something goes clearly wrong

**Cons of predicate-driven steps:**
- Harder to serialize/display plans (predicates aren't YAML-friendly)
- More complex step construction
- Less obvious what each step does from its type alone

**Implication:** Use a hybrid. Keep `StepKind` enum for plan display and serialization. Attach verification predicates to steps in the executor, not in the plan model. The plan is a data structure (displayable, diffable); the executor adds behavior. This gives us the best of both.

---

### 3.7 MatchSpec validation philosophy

**NIRIP_CONCEPT.md** defines `MatchRule` as a permissive Pydantic model — all fields optional.

**Deep Research** argues for **safety-oriented validation**: reject specs with no matcher at all, warn on title-regex-only matching unless optional, surface when multiple AppSpecs compete for the same window identity.

| Aspect | NIRIP_CONCEPT | Deep Research |
|---|---|---|
| Empty match rule | Implicitly invalid (no criteria) | Explicitly rejected by validator |
| Weak matchers | Allowed | Warning unless `optional: true` |
| Cross-app competition | Detected during matching | Detected during spec validation |

**Implication:** The deep research is right. Spec validation should be aggressive. A `MatchRule` with zero criteria should fail at load time, not at match time. A title-regex-only matcher should produce a warning. And the validator should check for inter-app match conflicts (two apps with `app_id: firefox` and no differentiating criteria). This is cheap to implement and prevents real user confusion.

---

### 3.8 Dependency library improvements

**Deep Research** proposes improvements to both dependency libraries:

For **niri-pypc**:
- Hand-written action helper layer (e.g., `spawn_action(...)`, `move_window_to_workspace_action(...)`)
- Public compatibility surface exposing schema version metadata

For **niri-state**:
- Matching-oriented selectors ("windows with app_id X", "windows matching regex")
- Richer publication metadata (which specific window/workspace IDs changed)
- First-class waiter helpers ("wait for window matching predicate")

**NIRIP_CONCEPT.md** does not propose dependency changes.

**Implication:** The action helper layer in niri-pypc is worth doing — the generated action types are verbose to construct (nested `Action(root=SpawnAction(...))` wrapped in `ActionRequest`). A thin ergonomics layer would keep nirip's executor readable.

The matching-oriented selectors in niri-state are borderline — nirip's matching engine is inherently nirip-specific (it evaluates `MatchRule` objects). Generic "windows by app_id" selectors could go either way. I'd lean toward keeping them in nirip since the matching policy is session-specific.

The granular changed-entity metadata in `PublishedState` is a nice-to-have but not blocking. Nirip can re-evaluate matches against the full snapshot without knowing exactly which window changed.

---

### 3.9 Output model naming

**NIRIP_CONCEPT.md** uses `NiripClient` as the public API class.
**Deep Research** uses `AsyncNirip` with methods returning `LiveDesktop`, `SessionDiff`, `ExecutionPlan`, `ApplyResult`, `CapturedSession`.

| Aspect | NIRIP_CONCEPT | Deep Research |
|---|---|---|
| Client name | `NiripClient` | `AsyncNirip` |
| inspect returns | `Snapshot` (from niri-state) | `LiveDesktop` (nirip-specific) |
| diff returns | `PlanDiff` | `SessionDiff` |
| plan returns | `Plan` | `ExecutionPlan` |
| apply returns | `ExecutionResult` | `ApplyResult` |

**Implication:** `AsyncNirip` is a better name — it's the library name, not a "client." The return types from the deep research are better named for a public API. `LiveDesktop` vs raw `Snapshot` is a real improvement — it lets nirip present a richer, session-aware view of state (e.g., annotating which windows are managed). `SessionDiff` is clearer than `PlanDiff`. `ApplyResult` is cleaner than `ExecutionResult`.

---

### 3.10 `@computed_field` usage

**Deep Research** explicitly recommends Pydantic `@computed_field` for derived values on result models: `MatchDecision.is_ambiguous`, `ApplyResult.failed_steps`, `ExecutionPlan.requires_spawn`, `SessionDiff.has_drift`, `CapturedAppSpec.suggested_key`.

**NIRIP_CONCEPT.md** uses plain fields or separate methods for these.

**Implication:** Good recommendation. `@computed_field` makes derived values appear in serialization and JSON output without manual maintenance. Adopt for all result/output models.

---

## 4. Summary of differences

| # | Topic | NIRIP_CONCEPT | Deep Research | Verdict |
|---|---|---|---|---|
| 1 | Internal pipeline | 2-stage | 3-stage (normalize → resolve → compile) | **Adopt 3-stage** |
| 2 | App nesting | Apps nested under workspace | Apps top-level with target | **Keep nested** for YAML, normalize internally |
| 3 | App identifier | `name` | `key` | **Keep `name`** |
| 4 | Placement model | `PlacementSpec` (simple) | `TargetSpec` (fuller) | **Extend PlacementSpec** with fullscreen/maximized |
| 5 | Package layout | 7 packages | 9 packages + observe/facade | **Adopt `resolve/` and `facade/`**, skip `observe/` and `model/` |
| 6 | Step definition | Enum + metadata | Predicate-driven | **Hybrid**: enum for data, predicates in executor |
| 7 | Spec validation | Permissive | Aggressive safety checks | **Adopt aggressive validation** |
| 8 | Dep improvements | None proposed | Action helpers, selectors, metadata | **Action helpers yes**, rest deferred |
| 9 | Public API naming | `NiripClient` | `AsyncNirip` + richer return types | **Adopt `AsyncNirip`** and richer names |
| 10 | Computed fields | Not used | `@computed_field` recommended | **Adopt** |

---

## 5. Final recommendation

### Concept

The core concept from NIRIP_CONCEPT.md is sound and should be the foundation. The deep research's most valuable contributions are structural — the three-stage internal pipeline and aggressive spec validation. These should be merged in.

The product identity is clear and both documents agree on it:

> **Nirip is a declarative session reconciler for Niri. Users write YAML specs describing workspace layouts. Nirip matches live windows, computes a convergence plan, and executes it with event-verified steps. It builds on niri-pypc (protocol/transport) and niri-state (live state mirror) and owns only session semantics: specs, matching, planning, execution, and capture.**

### Architecture

The recommended architecture adopts the deep research's three-stage pipeline while keeping NIRIP_CONCEPT's user-facing YAML structure and concrete model definitions:

```
┌──────────────────────────────────────────────────────┐
│                    CLI / Facade                       │
│  AsyncNirip (async-first)                            │
│  SyncNirip  (thin wrapper)                           │
├──────────────────────────────────────────────────────┤
│                                                      │
│  spec/           Session spec models, YAML loader,   │
│                  defaults, aggressive validation      │
│                                                      │
│  resolve/        Normalization → matching →           │
│                  resolution model (what matched,      │
│                  what's missing, what drifted)         │
│                                                      │
│  planning/       Resolution → compiled Plan           │
│                  (ordered steps with dependencies)    │
│                                                      │
│  execution/      Plan runner, action translation,     │
│                  verification predicates, runtime     │
│                  bookkeeping                          │
│                                                      │
│  capture/        Snapshot → scaffold SessionSpec      │
│                  with inferred match rules            │
│                                                      │
├──────────────────────────────────────────────────────┤
│  niri-state      Snapshot, selectors, waiters, health │
│  niri-pypc       Actions, requests, client, events   │
└──────────────────────────────────────────────────────┘
```

### Package layout

```
src/nirip/
  __init__.py
  config.py
  errors.py

  facade/
    __init__.py
    async_nirip.py        # AsyncNirip: primary async API
    sync_nirip.py          # SyncNirip: thin sync wrappers

  spec/
    __init__.py
    models.py              # SessionSpec, WorkspaceSpec, AppSpec, MatchRule, etc.
    loader.py              # YAML parsing
    validators.py          # aggressive safety validation
    defaults.py            # default option merging

  resolve/
    __init__.py
    normalizer.py          # spec → NormalizedSession (defaults applied, refs resolved)
    matcher.py             # MatchRule evaluation against Window
    resolver.py            # NormalizedSession + Snapshot → Resolution
    models.py              # NormalizedSession, MatchDecision, Resolution, AppResolution

  planning/
    __init__.py
    compiler.py            # Resolution → Plan (ordered steps)
    ordering.py            # topological sort, dependency handling
    models.py              # Plan, PlanStep, StepKind, SessionDiff

  execution/
    __init__.py
    executor.py            # Plan runner with verification
    actions.py             # PlanStep → niri-pypc Action translation
    predicates.py          # Snapshot predicates for step verification
    runtime.py             # SessionRuntime, AppRuntimeState
    models.py              # StepResult, StepOutcome, ApplyResult

  capture/
    __init__.py
    capturer.py            # Snapshot → SessionSpec scaffold
    inference.py           # infer MatchRules from live Windows

  cli/
    __init__.py
    main.py                # CLI entrypoint
    commands.py            # apply, diff, capture, inspect, doctor, watch
```

### Key design decisions

1. **Three-stage pipeline**: spec → resolve (normalize + match) → plan → execute. Resolution is the standalone intermediate representation that powers both `diff` and `plan`.

2. **Apps nested under workspaces in YAML**: The normalizer flattens this internally. Users think in workspaces; the engine thinks in app-to-window bindings.

3. **Aggressive spec validation**: Reject empty match rules at load time. Warn on weak matchers. Detect inter-app match conflicts before anything runs.

4. **Hybrid step model**: `PlanStep` is a data class with `StepKind` enum (serializable, displayable). The executor attaches verification predicates at execution time.

5. **`AsyncNirip` as primary API**: Async-first, small surface. `SyncNirip` wraps it for CLI and scripting.

6. **Results use `@computed_field`**: `ApplyResult.failed_steps`, `SessionDiff.has_drift`, `MatchDecision.is_ambiguous` — derived values appear in serialization automatically.

7. **No `observe/` wrapper**: Import `niri-state` selectors and waiters directly. The API is already clean; wrapping it adds indirection without value.

8. **Action helper layer**: Either add to `niri-pypc` upstream or create a thin `execution/actions.py` that wraps the verbose generated action construction. Prefer upstream if practical.

9. **Output affinity is workspace-level only**: No per-app output in v1. Workspace declares its output; apps inherit.

10. **Capture stays humble**: Scaffold with `app_id`-based match rules, no spawn commands, comments guiding manual refinement.

### Implementation order

1. **Phase 1 — Spec + Matching**: `spec/`, `resolve/normalizer.py`, `resolve/matcher.py`, `resolve/models.py`. Deliverable: load YAML, normalize, evaluate matches against mock Windows.

2. **Phase 2 — Resolution + Diff**: `resolve/resolver.py`, `planning/models.py` (SessionDiff). Deliverable: `nirip diff` shows what would change.

3. **Phase 3 — Planning**: `planning/compiler.py`, `planning/ordering.py`. Deliverable: full Plan from Resolution.

4. **Phase 4 — Execution**: `execution/`, `facade/`. Deliverable: `nirip apply` works end-to-end.

5. **Phase 5 — Capture + Polish**: `capture/`, `cli/` polish, `doctor`, `watch`, `inspect`.
