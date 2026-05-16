# RESEARCH_REPORT_ANALYSIS

## Purpose
This report compares two documents:
- `.scratch/projects/009-revised-dependency-code-review/Nirip_Code_Review_Research.md` (current-state architecture review)
- `.scratch/projects/006-v3-revised-python-concept/NIRIP_CONCEPT_FINAL.md` (target concept design)

It identifies convergence and conflict, then defines a refined final concept for a full refactor of `nirip` with no backward-compatibility constraints.

## High-level conclusion
Both documents agree on the core direction: `nirip` should be a declarative, event-confirmed session reconciler on top of `niri-state` (live state) and `niri-pypc` (command protocol). The concept doc is directionally correct, but the code-review document exposes concrete runtime and modeling failures that the final concept must explicitly correct.

The refined concept below keeps the concept doc’s architecture and UX, while tightening type safety, execution semantics, and dependency boundaries so the implementation cannot regress into “planner-only” behavior.

## Similarities (strong alignment)
1. **Role of nirip**
`nirip` is a declarative session reconciler, not a macro script runner.

2. **Dependency posture**
`niri-pypc` is the protocol/command boundary; `niri-state` is the state/selector/waiter boundary; `nirip` owns session semantics only.

3. **Pipeline shape**
Spec -> Normalize -> Resolve -> Plan -> Execute is the right architecture, with `Resolution` as a first-class intermediate representation and `SessionDiff` derived from it.

4. **Execution model**
Execution must be event-driven and verified through live state predicates/waiters, not sleep-based timing.

5. **API design**
Async-first facade with a thin sync wrapper is the preferred public API shape.

6. **Validation philosophy**
Aggressive early validation is mandatory for spec reliability and deterministic behavior.

## Differences and gaps
1. **Runtime reality vs conceptual intent**
- Concept doc assumes live-by-default `AsyncNirip.open()`.
- Review doc shows current code is snapshot-injection dependent and can no-op `apply()` while reporting completion.

Implication: the final concept must enforce real runtime wiring as a hard invariant, not optional behavior.

2. **Plan model strictness**
- Concept doc uses enum + metadata `PlanStep` for diffability and display.
- Review doc identifies this as under-modeled and prone to invalid states.

Implication: keep serializable plan data, but move to discriminated step unions so each step carries required typed payload.

3. **Spec/model safety defaults**
- Concept doc emphasizes validation but does not globally enforce strict model config.
- Review doc identifies `extra='ignore'` default behavior as a correctness risk.

Implication: final concept should use shared strict model policy (`extra='forbid'`) across core domain models.

4. **Feature completeness vs declared schema**
- Concept doc declares options/placement/dependency features.
- Review doc shows many fields currently unwired (or only partially wired).

Implication: final concept must include a feature contract: every public field is either fully enforced end-to-end or removed.

5. **Matching semantics**
- Concept doc defines scoring and ambiguity handling.
- Review doc highlights missing global one-to-one assignment and a workspace-missing drift edge case.

Implication: final concept needs globally consistent assignment and explicit drift classification rules.

6. **Warning propagation**
- Concept doc expects high observability.
- Review doc notes validation warnings are dropped.

Implication: final concept should treat warnings as first-class outputs in load/doctor/diff/plan.

## Refined final concept (target architecture)

### 1) System contract
`nirip` is a **live, stateful reconciler** with this hard contract:
- `AsyncNirip.open()` always initializes runtime adapters (state + command + process).
- `apply()` never silently simulates execution in default mode.
- Any non-live mode is explicit (`dry_run=True` / dedicated API), never implicit.

### 2) Strict architecture boundaries
- `spec/`, `resolve/`, `planning/`, `capture/`: pure, deterministic, no I/O.
- `execution/`: side effects and verification orchestration.
- `facade/`: lifecycle, wiring, API ergonomics.
- `cli/`: input/output and command routing only.

Dependency flow:
- `spec -> resolve -> planning -> execution`
- `capture <- facade -> cli`
- `execution` runtime ports implemented by `niri-state`, `niri-pypc`, and subprocess adapter.

### 3) Runtime ports (explicit)
Define three explicit interfaces used by executor/facade:
- `StatePort`: snapshot access, subscription, selectors/waiters.
- `CommandPort`: send compositor actions.
- `ProcessPort`: spawn local processes with cwd/env/shell semantics.

Default adapters:
- `StatePort` -> `niri-state`
- `CommandPort` -> `niri-pypc`
- `ProcessPort` -> `asyncio.subprocess` (or delegated spawn action when intentionally chosen)

### 4) Data model strategy
- Shared strict base model for core domain (`extra='forbid'`; frozen where feasible).
- Replace generic `PlanStep` metadata payload with discriminated `PlanStep` union types.
- Keep plans serializable/displayable, but with typed payload invariants per step kind.
- Use stable semantic identifiers (`workspace_name/app_name`) rather than transient IDs in planning layers; resolve transient IDs at execution time.

### 5) Matching and resolution semantics
- Implement **global one-to-one assignment** between declared app roles and live windows.
- Preserve explainable confidence scoring and ambiguity surfaces.
- Fix drift semantics: if a matched window exists and target workspace is missing, classify as drift requiring post-workspace move.
- Record unresolved ambiguity as explicit non-fatal operational outcome (unless strict mode requests failure).

### 6) Planning semantics
Plan compilation must output executable intent only:
- Every spawned app step includes concrete spawn payload (`command`, `cwd`, `env`, `shell`, timeout).
- Workspace materialization and workspace-output placement are explicit steps.
- Dependency ordering is deterministic and validated (topological with clear cycle error surfaces).
- Focus steps always terminal and deterministic.

### 7) Execution semantics
For each step:
1. Verify dependencies satisfied.
2. Pre-check predicate: mark `SKIPPED` if already satisfied.
3. Execute action/spawn.
4. Verify with event-driven waiter and optional fail-fast predicate.
5. Emit structured `StepResult`.

Operational failures (timeout, ambiguity, unmet optional, etc.) are structured outcomes in `ApplyResult`; programmer/config/dependency failures raise typed errors.

### 8) Field-to-behavior completeness rule
Every public schema field (`SessionOptions`, placement controls, `depends_on`, etc.) must be one of:
- Fully enforced through normalization -> resolution -> plan -> execution, or
- Removed from public schema.

No latent/dead fields.

### 9) Observability and diagnostics
Warnings/errors are first-class artifacts:
- Loader returns/attaches validation warnings.
- `doctor`, `diff`, and `plan` expose warning streams consistently.
- `inspect` exposes state health and session-managed bindings.

### 10) Capture philosophy
Keep capture conservative and scaffold-first:
- Infer safe match rules.
- Never fabricate brittle spawn details.
- Emit explicit TODO diagnostics for manual hardening.

## Recommended refactor priorities
1. **Make runtime live-by-default** (`AsyncNirip.open` wiring + non-simulated `apply`).
2. **Introduce strict base model policy** and migrate core models.
3. **Replace `PlanStep` metadata model with typed step union models**.
4. **Implement global one-to-one matcher and corrected drift rules**.
5. **Wire full field contract** (`depends_on`, placement controls, options).
6. **Unify warning propagation in loader/diff/doctor/plan outputs**.
7. **Harden executor around waiters/fail-fast predicates and deterministic outcomes**.

## Final position
Use the concept doc as the structural blueprint, and use the code-review findings as non-negotiable correctness constraints. The resulting `nirip` should be a strictly typed, live-wired, event-verified reconciler whose public schema exactly matches implemented behavior, with no placeholder abstractions and no silent success paths.
