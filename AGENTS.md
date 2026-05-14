# AGENTS.md

## Purpose
This repository builds `nirip`, a declarative workspace orchestrator for the Niri compositor. It loads, diffs, freezes, and reconciles workspace layouts from profile files with typed planning and event-confirmed execution.

## Project Scope
`nirip` owns:
- Declarative profile schema for workspaces, columns, and window roles.
- Typed planning from desired layout + live compositor snapshot.
- Execution loop that applies operations and confirms outcomes via events.
- Session freeze/export from live Niri state into profile form.
- Diagnostics (`diff`, `doctor`, plan explanations) for predictable workflows.
- Optional integration boundaries (for example, sidebard RPC lookups) behind adapters.

`nirip` does not own:
- Niri protocol schema or transport internals (owned by `nimri-ipc`).
- Shell/session ownership logic that belongs to `sidebard`.
- Application-internal state restore guarantees (browser tabs, editor buffers, etc).
- Remote/cloud orchestration or external control planes.

## Architecture
Actual layout under `src/nirip/`:

| Module | Purpose | I/O? |
|---|---|---|
| `spec/` | Session spec models, YAML loading, validation, defaults | No |
| `resolve/` | Normalization, window matching, drift resolution | No |
| `planning/` | Plan compilation, step ordering, diff generation | No |
| `execution/` | Plan executor, action translation, predicates, runtime | Yes (async) |
| `capture/` | Snapshot-to-spec scaffolding, name/rule inference | No |
| `facade/` | AsyncNirip/SyncNirip orchestration facades | Yes (asyncio.run) |
| `cli/` | Argparse, command dispatch, file I/O, stdout | Yes |

Key architectural decisions:
- Planning logic (`spec/`, `resolve/`, `planning/`) remains pure and side-effect free.
- Execution side effects are explicit and confirmed by Niri events.
- Durable identity prefers profile/workspace names and match rules, not transient window IDs.
- `nimri-ipc` stays the only Niri protocol boundary.

## Dependency Rules
```
spec -> resolve -> planning -> execution
                           ↓
capture <- facade -> cli
```

**Boundary discipline:** `spec/`, `resolve/`, `planning/`, `capture/` must not import `asyncio`, `subprocess`, `socket`, or perform I/O. All such side effects live in `execution/`, `facade/`, and `cli/`.

## Forbidden Couplings
- Core modules (`spec/`, `resolve/`, `planning/`, `capture/`) must not perform process, socket, or filesystem side effects (except config/state persistence modules).
- Executor modules must not redefine policy that belongs in planner/matcher.
- CLI must not bypass typed plan/execution contracts.
- Niri transport/protocol handling must not leak outside `nimri-ipc` integration points.

## Implementation Notes
- Predicates in `execution/predicates.py` must verify specific window appearance, not just presence of any window.
- The executor must check predicates *after* spawning, not before (to avoid skipping steps already "satisfied" by pre-existing state).
- `SessionOptions` fields (`stop_on_error`, `mode`, `match_existing`, `launch_missing`, `move_unmatched`) must be wired and enforced or removed as dead code.

## Development Environment
All development should run inside `devenv` for reproducible Python versions.

### Common commands
```bash
devenv shell -- ruff check src/nirip/
devenv shell -- ty check src/nirip/
devenv shell -- python -m pytest tests/
```

### Agent rule
When linting, type checking, or testing, run through `devenv shell -- <command>` unless already inside a devenv shell.

## Technology Stack
- Python >= 3.11
- `ruff` for linting
- `ty` for static type checking
- `nimri-ipc` for typed Niri IPC request/event handling
- Stdlib pathlib/json/argparse/subprocess utilities as needed

## Design Principles
1. Deterministic planning and reconciliation from explicit inputs.
2. Typed contracts across config, planner, and executor boundaries.
3. Side effects isolated in executor/integration modules.
4. Observable, explainable behavior through diff/doctor diagnostics.
5. Event-confirmed execution over blind fire-and-forget actions.

## Testing Expectations
- Add or update tests for each behavior change.
- Prioritize pure core tests for matcher/planner/freezer/diagnostics.
- Add executor tests for sequencing, timeout, and confirmation behavior.
- If tests depend on a live Niri socket, skip cleanly when unavailable.

## Agent Workflow
1. Confirm task scope and impacted boundary (core vs executor vs interface).
2. Implement changes in the narrowest valid module.
3. Add/update tests nearest to changed behavior.
4. Run targeted tests, then broader suite as needed.
5. Run `ruff check` and `ty check` to ensure code quality.
6. Report what was validated and any residual risk.
