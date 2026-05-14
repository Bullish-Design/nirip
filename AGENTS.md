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

| Module | Role | I/O |
|---|---|---|
| `__main__.py` | Program entrypoint and subcommand dispatch | Yes |
| `cli/` | CLI argument parsing and command flow | Yes |
| `spec/` | Session/workspace/app spec models and validation | No |
| `resolve/` | Normalization and window matching | No |
| `planning/` | Operation planning from desired vs actual state | No |
| `execution/` | Async operation execution and event confirmation | Yes |
| `capture/` | Snapshot-to-profile conversion (session freeze) | No |
| `facade/` | Sync/async API orchestration | Yes |
| `config.py` | Configuration model and file loading | File I/O |

Key architectural decisions:
- Planning logic (`spec/`, `resolve/`, `planning/`) remains pure and side-effect free.
- Execution side effects are explicit and confirmed by Niri events.
- Durable identity prefers profile/workspace names and match rules, not transient window IDs.
- `nimri-ipc` stays the only Niri protocol boundary.

## Dependency Rules
```
src/nirip/__main__.py -> cli, spec, resolve, planning, execution, capture, facade, config
src/nirip/cli/__init__.py -> spec, resolve, planning, execution, facade
src/nirip/spec/ -> (self-contained, no external deps)
src/nirip/resolve/ -> spec
src/nirip/planning/ -> spec, resolve
src/nirip/execution/ -> spec, planning (+ asyncio)
src/nirip/capture/ -> spec, resolve
src/nirip/facade/ -> spec, resolve, planning, execution, capture
```

**Boundary discipline:** `spec/`, `resolve/`, `planning/`, `capture/` must not import `asyncio`, `subprocess`, `socket`, or perform I/O. All such side effects live in `execution/`, `facade/`, and `cli/`.

## Forbidden Couplings
- Core modules must not perform process, socket, or filesystem side effects (except config/state persistence modules).
- Executor modules must not redefine policy that belongs in planner/matcher.
- CLI must not bypass typed plan/execution contracts.
- Niri transport/protocol handling must not leak outside `nimri-ipc` integration points.

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