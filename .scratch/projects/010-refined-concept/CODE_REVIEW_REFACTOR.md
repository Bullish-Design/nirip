# Nirip Refactor Implementation Guide

This document is a step-by-step implementation guide to address all issues and improvement recommendations from `.scratch/projects/010-refined-concept/NIRIP_CODE_REVIEW.md`.

It is intentionally execution-focused: what to change, where to change it, in what order, and how to validate each change.

## 0. Scope and Success Criteria

### In scope
- Fix all identified correctness bugs.
- Close architecture gaps (especially spawn-to-placement flow and dependency wiring).
- Enforce or remove dead `SessionOptions` fields.
- Improve executor reliability and observability.
- Improve CLI usability and output readability.
- Expand tests to cover resolver/planner/executor edge cases.

### Out of scope
- New remote orchestration features.
- Niri protocol changes (owned by `niri-pypc`).

### Definition of done
- All critical/medium issues in the review are resolved in code.
- All new behaviors are covered by tests.
- `devenv shell -- ruff check src/nirip/ tests/` passes.
- `devenv shell -- ty check src/nirip/` passes.
- `devenv shell -- python -m pytest tests/` passes.

---

## 1. Execution Order (High-Level)

Implement in this sequence to avoid rework:

1. Matcher/resolver correctness fixes.
2. Planner dependency graph + spawn placement design.
3. Executor runtime data flow + action verification.
4. `SessionOptions` enforcement (`mode`, `match_existing`, `move_unmatched`).
5. Sync wrapper and CLI improvements.
6. Test suite expansion and cleanup.
7. Final hardening and docs.

---

## 2. Phase A: Matcher and Resolver Correctness

## A1. Fix negation-only `MatchRule` bug

### Problem
`resolve/matcher.py:evaluate_rule()` returns no match when a rule has only `not_rule` and no positive score contributors.

### Changes
- File: `src/nirip/resolve/matcher.py`
- In `evaluate_rule`:
  - Keep current failure semantics.
  - If rule did not fail and `scores` is empty, treat as a successful negation-only/composite-only match with deterministic baseline confidence.
  - Suggested confidence: `0.5` for negation-only rules.

### Tests
- Add to `tests/test_matcher.py`:
  - Rule `{not: {app_id: "firefox"}}` matches non-firefox windows.
  - Same rule does not match firefox.
  - Ensure confidence is non-zero and stable.

## A2. Remove ambiguous typing in drift detection

### Problem
`_detect_drift()` in `resolve/resolver.py` accepts `object` and relies heavily on `getattr`.

### Changes
- File: `src/nirip/resolve/resolver.py`
- Change signatures to concrete types:
  - `window: Window`
  - `napp: NormalizedApp`
  - `ws_by_name: dict[str, Workspace]` (or exact generated workspace type from niri models).
- Keep only defensive field access where protocol uncertainty is real (for `is_maximized` if truly optional).

### Tests
- Update/extend `tests/test_resolver_drift.py` for typed fixtures.

## A3. Strengthen dependency validation behavior

### Problem
`_check_depends_on_refs` reports missing deps but still runs DFS across a graph that may include dangling nodes.

### Changes
- File: `src/nirip/spec/validators.py`
- Build graph only from valid edges (known in-workspace targets).
- If unknown deps exist, still return errors, but avoid DFS through unknown nodes.
- Improve error wording: explicitly say cross-workspace deps are invalid.

### Tests
- Add to `tests/test_spec_validators.py`:
  - dangling dep error format.
  - cross-workspace dep rejection.
  - cycle detection still works for valid graph.

---

## 3. Phase B: Planner Refactor (Dependencies + Spawn Placement)

## B1. Wire `AppSpec.depends_on` into compiled plan edges

### Problem
`NormalizedApp.depends_on` is never consumed by `compile_plan()`.

### Changes
- File: `src/nirip/planning/compiler.py`
- During per-workspace app planning:
  - Maintain map of app -> completion step id(s).
  - For each app, convert `depends_on` names to step dependencies against referenced app completion step(s).
  - Apply these deps to spawn/wait/move/placement/focus steps.
- Ensure ordering guarantees:
  - Workspace ensure before all app steps.
  - Dependent app steps after dependency completion.

### Tests
- Add `tests/test_compiler_depends_on.py`:
  - App B depends on A => topological order enforces A completion before B spawn.

## B2. Implement post-spawn placement gap fix (core architecture change)

### Problem
Missing apps get spawn+wait, but no placement/move steps because `window_id` is unknown at plan compile time.

### Recommended design
Use **deferred window references** resolved at runtime (Option 3 from review), because it preserves typed planning without requiring full re-plan cycles.

### Concrete implementation
1. Extend planning model to support deferred IDs:
   - File: `src/nirip/planning/models.py`
   - Introduce `WindowRef` type:
     - `LiteralWindowRef(window_id: int)` and `AppWindowRef(app_name: str, workspace_name: str)` (or equivalent tagged union).
   - Replace `window_id: int` in step models that target windows with `window_ref: WindowRef`.
2. Update compiler:
   - File: `src/nirip/planning/compiler.py`
   - For matched windows, emit literal refs.
   - For spawned apps, emit app refs on move/placement/focus steps after wait step.
   - Ensure those steps depend on wait step and app deps.
3. Update executor resolution path:
   - File: `src/nirip/execution/handlers.py` and/or `executor.py`
   - Add helper to resolve `WindowRef` at execution time using `SessionRuntime.apps[app_name].matched_window_id`.
4. Update runtime update logic:
   - File: `src/nirip/execution/runtime.py`
   - Persist matched window id after `WaitForWindowStep`.

### Tests
- Add `tests/test_compiler_spawn_placement.py`:
  - Spawned app includes move/floating/fullscreen/size/focus steps with deferred refs.
- Add `tests/test_executor_spawn_resolution.py`:
  - wait step captures matched window id.
  - later steps resolve app ref and act on correct window id.

## B3. Harden size parsing

### Problem
`_parse_size("px:abc")` raises `ValueError` directly.

### Changes
- File: `src/nirip/planning/compiler.py`
- Catch parsing errors and raise `PlanningError` with context (app/workspace/field/value).
- Optionally validate in spec validator to fail earlier.

### Tests
- Add parser error case in `tests/test_compiler.py` or dedicated test file.

---

## 4. Phase C: Executor Reliability and Verification

## C1. Stop swallowing programming errors

### Problem
`handlers.py` catches broad `Exception`, converting internal bugs into `FAILED` results.

### Changes
- File: `src/nirip/execution/handlers.py`
- Catch only expected operational exceptions:
  - `WaitTimeoutError`, transport errors (`ConnectionError`, `OSError`, known client exceptions).
- Let unexpected exceptions propagate to executor-level handler (or fail fast with explicit internal-error classification).
- In `executor.py`, keep single boundary catch that marks internal failure and stops.

### Tests
- Add `tests/test_executor_error_propagation.py`:
  - Inject handler programming error; verify explicit internal failure behavior.

## C2. Fix `StepResult.window_id` semantics

### Problem
Spawn handler writes PID to `window_id`.

### Changes
- File: `src/nirip/execution/models.py`
- Add optional `spawn_pid` field to `StepResult`.
- Keep `window_id` exclusively compositor window id.
- File: `src/nirip/execution/handlers.py`
  - Spawn step populates `spawn_pid`, not `window_id`.

### Tests
- Add spawn result assertions in executor tests.

## C3. Capture matched window during wait

### Problem
Wait step returns no matched window identity.

### Changes
- File: `src/nirip/execution/handlers.py`
- Wait predicate should return matched window id (not only bool).
- Persist matched id into `runtime.apps[app_name].matched_window_id`.
- Include matched `window_id` in `StepResult`.

### Tests
- Add/extend `tests/test_executor.py` with fake snapshot progression and assert runtime updates.

## C4. Add post-action verification waits

### Problem
Most handlers fire action and return immediately.

### Changes
- File: `src/nirip/execution/handlers.py`
- For each stateful action (workspace creation/move, window move, floating/tiling/fullscreen/maximized, size where observable), do:
  1. issue action request,
  2. `wait_until` for predicate confirming intended state,
  3. timeout -> `TIMED_OUT`.
- Keep idempotent skip predicate in `predicates.py`.
- For toggle actions (`fullscreen`, `maximize`), rely on post-action verification predicate to prevent incorrect success.

### Tests
- Add `tests/test_executor_verification.py`:
  - action success after delayed state update.
  - timeout path.
  - stale snapshot toggle protection.

## C5. Replace fragile `_wait` compatibility hack

### Problem
Current `_wait` catches `TypeError` broadly and retries with alternate signature.

### Changes
- File: `src/nirip/execution/handlers.py`
- Inspect `wait_until` signature once at module init (or wrap with explicit adapter chosen by introspection).
- Remove generic `TypeError` fallback from runtime path.

### Tests
- Add unit test for adapter selection behavior.

---

## 5. Phase D: Enforce or Remove Dead `SessionOptions`

AGENTS.md requires fields to be enforced or removed.

## D1. Enforce `match_existing`

### Target behavior
- `match_existing=False` means existing windows should not satisfy apps; only spawned windows should be considered for missing apps.

### Changes
- Files: `src/nirip/resolve/resolver.py`, possibly `resolve/normalizer.py`
- Gate matching input set by option, or mark matched windows as ineligible when disabled.

## D2. Enforce `mode`

### Target behavior
- `reconcile`: current behavior.
- `clean`: deterministic cleanup mode for windows not in spec (close/move policy decided explicitly).

### Changes
- Minimum viable clean mode:
  - Extend resolve model to report unmatched live windows.
  - Planner emits cleanup steps under `mode="clean"`.
- If cleanup semantics are not ready, remove `clean` from schema now and reintroduce later.

## D3. Enforce `move_unmatched`

### Target behavior
- When true, unmatched windows are moved to a designated workspace or retained area (define policy).

### Changes
- Decide policy and encode in planner.
- If no clear policy now, remove option as dead code.

### Tests for D-phase
- Add `tests/test_session_options_behavior.py` covering each retained option.
- If fields removed, update model tests and fixtures accordingly.

---

## 6. Phase E: Sync Facade and CLI Improvements

## E1. Stabilize `SyncNirip` loop lifecycle

### Problem
Each method uses `asyncio.run()`, creating separate loops.

### Changes
- File: `src/nirip/facade/sync_nirip.py`
- Use a persistent `asyncio.Runner` (Python 3.11+) owned by `SyncNirip` instance.
- Execute all async calls via one runner until close.
- Ensure `close()` shuts runner and async resources exactly once.

### Tests
- Add `tests/test_sync_nirip.py`:
  - multiple sequential method calls with same underlying state/client.
  - idempotent close.

## E2. Replace blocking `input()` in async apply path

### Changes
- File: `src/nirip/cli/commands.py`
- Option A: keep prompt logic in sync CLI entrypoint before entering async context.
- Option B: use `asyncio.to_thread(input, ...)`.

## E3. Add `--dry-run` behavior and formatters

### Changes
- Files: `src/nirip/cli/main.py`, `src/nirip/cli/commands.py`
- Add `apply --dry-run` to print diff/plan without execution.
- Introduce formatter helpers (new module `src/nirip/cli/formatting.py`):
  - `format_diff(SessionDiff) -> str`
  - `format_plan(Plan) -> str`
  - `format_apply_result(ApplyResult) -> str`
- Replace raw `yaml.dump(model_dump())` for human-oriented terminal output.

## E4. Add missing concept commands or trim concept claim

### Changes
- Either implement `doctor` first (recommended), then `inspect/watch/status` incrementally,
- Or explicitly document unsupported commands and remove references from user-facing docs.

### Tests
- Add `tests/test_cli_commands.py` for dry-run and formatter outputs.

---

## 7. Phase F: Test Suite Overhaul

## F1. Consolidate fakes in `conftest.py`

### Changes
- Rework tests to use shared fake snapshot/window/workspace/client structures.
- Remove ad-hoc `SimpleNamespace`, custom `W` classes where feasible.

## F2. Add missing high-priority test groups

1. Resolver classification matrix:
- MATCHED, DRIFTED, MISSING, OPTIONAL_MISSING, AMBIGUOUS.
- workspace exists/missing and output correctness.

2. Matcher assignment edge cases:
- N apps, M windows competition.
- tie confidence behavior.
- no-candidate behavior.

3. Compiler propagation:
- all step types and fields.
- dependency edges including `depends_on`.
- spawn placement deferred refs.

4. Executor sequencing:
- `stop_on_error` true/false.
- skip predicates.
- timeout handling.
- post-action verification paths.

5. Validator edge cases:
- nested any/not regex validation.
- long chains/cycles.
- duplicate names across workspace boundaries.

6. Integration:
- full pipeline golden tests for representative sessions.

## F3. Coverage goal
- Raise from current thin baseline to meaningful behavior coverage in core layers:
  - resolver/planning/execution should have broad branch coverage.

---

## 8. Phase G: Final Hardening and Documentation

## G1. Update docs

- Update README command examples and options behavior.
- Document spawn placement behavior and dependency semantics.
- Document any intentionally deferred features.

## G2. Add explicit invariants in code comments

- In planner/executor boundary, document how window references are resolved.
- In matcher, document confidence semantics for composite/negation-only rules.

## G3. Final validation run

Run in order:

```bash
devenv shell -- ruff check src/nirip/ tests/
devenv shell -- ty check src/nirip/
devenv shell -- python -m pytest tests/
```

If failures remain:
- fix type drift first,
- then resolver/planner test failures,
- then executor timing flakes.

---

## 9. Suggested PR Breakdown

Use small PRs with isolated risk:

1. Matcher/resolver bugfixes + tests.
2. Planner dependency wiring + tests.
3. Deferred window ref model + compiler + executor integration.
4. Executor verification + error-handling hardening.
5. SessionOptions enforcement/removal decision.
6. Sync facade + CLI formatting/dry-run.
7. Test consolidation + broad coverage additions.
8. Docs cleanup.

---

## 10. Risk Register and Mitigations

- Risk: Deferred window refs complicate type model.
  - Mitigation: use explicit discriminated union for ref types and exhaustive `match` in executor.

- Risk: Action verification introduces flaky waits.
  - Mitigation: centralized wait helper, conservative timeouts, deterministic fake-state tests.

- Risk: Clean/move_unmatched semantics become under-specified.
  - Mitigation: either formalize explicit policy now or remove options from schema until ready.

- Risk: Sync runner lifecycle bugs.
  - Mitigation: strict open/close ownership tests and idempotent shutdown path.

---

## 11. Acceptance Checklist

- [ ] Negation-only match rules work.
- [ ] `_detect_drift` uses concrete types.
- [ ] `depends_on` affects plan ordering.
- [ ] Spawned apps receive full placement actions after wait.
- [ ] Executor records matched window IDs and verifies actions.
- [ ] `StepResult.window_id` no longer overloaded with PID.
- [ ] Dead `SessionOptions` fields are enforced or removed.
- [ ] CLI has readable output and `apply --dry-run`.
- [ ] Sync wrapper uses stable event-loop lifecycle.
- [ ] Test suite materially expanded for resolver/planner/executor.
- [ ] Lint/typecheck/tests pass in `devenv`.
