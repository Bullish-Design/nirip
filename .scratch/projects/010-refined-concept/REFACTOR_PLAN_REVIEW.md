# Refactor Plan Review

Review of the intern's `CODE_REVIEW_REFACTOR.md` against the actual codebase and the original code review findings.

---

## Assessment: The Review is Correct, The Plan Needs Tightening

The code review (`NIRIP_CODE_REVIEW.md`) is accurate and thorough. Every bug and gap it identifies is real and verified against the source. The refactor guide (`CODE_REVIEW_REFACTOR.md`) addresses the right issues in approximately the right order, but leans toward over-engineering in places and under-engineering in others.

---

## Verified Bugs and Gaps

All confirmed by reading the source:

1. **Negation-only match bug** (`matcher.py:80-81`): `if not scores: return False, 0.0, reasons` kills negation-only rules.
2. **`_detect_drift` typing** (`resolver.py:92`): `object` types with `getattr` everywhere.
3. **Post-spawn placement gap** (`compiler.py:91-93`): `wid = ar.match_decision.assigned_window_id` is None for MISSING apps; all placement conditionals skipped.
4. **`depends_on` not wired**: Field propagates through normalization but compiler never creates cross-app edges.
5. **Broad exception catch**: Both `handlers.py:179` and `executor.py:29`.
6. **`window_id` overloaded with PID**: `handlers.py:79`.
7. **`WaitForWindowStep` doesn't capture matched window**: Returns generic "window appeared" without identity.

---

## Disagreements with Intern's Approach

### 1. Post-Spawn Placement: WindowRef Is Over-Engineered

**Intern proposes:** `WindowRef` discriminated union (`LiteralWindowRef` / `AppWindowRef`) — new types, compiler changes, executor resolution logic.

**Better:** Make `window_id: int` → `window_id: int | None = None` on the 8 placement step types. The compiler emits placement steps for spawned apps with `window_id=None` and `depends_on=[wait_step_id]`. The executor resolves None from `runtime.apps[step.app_name].matched_window_id` just before dispatch.

**Why:** Zero new types. The plan still declares intent. `None` is honest ("resolve at runtime"). All existing code that sets `window_id` from matched windows works unchanged. The topological sort already ensures wait completes before placement steps fire.

### 2. SessionOptions Dead Code: Don't Implement, Remove

**Intern proposes:** Implement `mode="clean"`, `match_existing`, `move_unmatched`.

**Better:** Delete them. Keep only `launch_missing`, `stop_on_error`, `default_startup_timeout_s`. The AGENTS.md instruction was "enforce or remove" — removing is correct because the semantics aren't even defined. Add them back with proper design when needed.

### 3. Test Phasing: Tests-at-End Is an Anti-Pattern

**Intern proposes:** Phase F as standalone test expansion after all implementation.

**Better:** Every phase delivers its own tests. Tests aren't a separate phase — they're definition-of-done for each change. Phase F should not exist.

### 4. `_wait` Compatibility Hack: Fix Upstream

**Intern proposes:** Inspect `wait_until` signature at module init and choose adapter.

**Better:** Pin `niri-state` version. Use the correct signature directly. If you own the ecosystem, fix the API upstream. Runtime introspection of your own dependencies is a code smell.

### 5. Post-Action Verification: Tiered, Not Uniform

**Intern proposes:** Verification waits for all stateful actions.

**Better:** Tiered approach:
- **Critical** (workspace create, window move): `wait_until` with meaningful timeout
- **Important** (floating/tiling/fullscreen/maximized): Short wait (1-2s), degrade gracefully on timeout
- **Fire-and-forget** (focus, column width): No verification needed

### 6. `_detect_drift`: Not Just Typing, Restructure

**Intern proposes:** Change parameter types to concrete.

**Better:** Also make the function table-driven. The repeated `getattr` + `DriftItem` construction is boilerplate that grows with every new drift dimension. A declarative drift-check table is more maintainable.

### 7. Error Handling: Move All Policy to Executor

**Intern proposes:** Narrow exception types in handlers.py.

**Better:** Eliminate try/except in handlers.py entirely. Handlers are pure "do the thing" functions. Executor wraps each call with error policy (timeout → TIMED_OUT, transport error → FAILED, anything else → propagate as bug).

### 8. SyncNirip: Question Its Existence

**Intern proposes:** Use `asyncio.Runner` for stable loop lifecycle.

**Better:** First ask: who uses this? CLI is async. Primary API is `AsyncNirip`. If it's for "simple scripts," those scripts can `asyncio.run()` an async block. Consider removing entirely. If it stays, `asyncio.Runner` is correct.

---

## Issues Missing from Both Documents

### Global Assignment Ignores Workspace Locality

`resolver.py:23` evaluates ALL apps against ALL windows globally. A window already in the correct workspace gets no confidence boost over one that would need to be moved. This means the greedy algorithm may choose to move windows unnecessarily when a "leave it where it is" assignment exists.

**Fix:** Add a small workspace-locality bonus (e.g., +0.05) to confidence when a window is already in the app's target workspace.

### Idempotent Size Steps Without Drift Check

The compiler emits `SetColumnWidthStep`/`SetWindowHeightStep` for ALL matched apps with a size spec, regardless of whether the current size matches the desired size. `predicates.py` doesn't check size drift either. This is wasteful — every reconciliation will re-set sizes that haven't changed.

**Fix:** Either add size drift detection (requires knowing current column width from snapshot, which may not be available), or accept the idempotent overhead and document it.

### Duplicate Match Rules Across Workspaces

If workspace "dev" and workspace "media" both define an app matching `{app_id: "firefox"}`, the global assignment gives one firefox window to one and marks the other MISSING. This is technically correct but will surprise users who expect "match the firefox that's already on this workspace."

**Fix:** Workspace locality bonus (same fix as above) naturally resolves this.

---

## Recommended Execution Order

1. **Remove dead code** — SessionOptions dead fields, unused conftest fakes, `_wait` hack (pin upstream)
2. **Fix correctness bugs** — negation-only match, `_detect_drift` typing/structure
3. **Core architecture** — optional `window_id` on placement steps, compiler emits for spawned apps, executor resolution, `depends_on` wiring
4. **Executor hardening** — error handling to executor level, tiered verification, window ID capture in wait handler
5. **CLI/facade** — remove or fix SyncNirip, CLI formatting, `--dry-run`
6. **Tests accompany each phase** — no standalone test phase

---

## Summary

The intern's work is competent and identifies the right problems. The execution plan needs tightening: simpler solutions where available (optional window_id vs WindowRef), deletion over speculative implementation (SessionOptions), and structural improvements (tests inline, error policy centralization, tiered verification).
