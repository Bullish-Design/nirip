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
Expected layout under `src/`:

| Module | Role | I/O |
|---|---|---|
| `nirip.nim` | Program entrypoint and subcommand dispatch | Yes |
| `cli.nim` | CLI argument parsing and command flow | Yes |
| `core/types.nim` | Domain identifiers and profile/operation types | No |
| `core/config.nim` | Profile schema load + validation | File I/O |
| `core/matcher.nim` | Window match rule evaluation | No |
| `core/planner.nim` | `plan(desired, actual) -> operations` | No |
| `core/freezer.nim` | Snapshot-to-profile conversion logic | No |
| `core/diagnostics.nim` | Human-readable diff/doctor output | No |
| `executor/runner.nim` | Operation execution + event-confirmation loop | Yes |
| `executor/launcher.nim` | Process launch + spawn tracking | Yes |
| `state/managed.nim` | Managed session state persistence | File I/O |
| `integrations/sidebard_rpc.nim` | Optional sidebard lookup adapter | Yes |

Key architectural decisions:
- Planning logic remains pure and deterministic.
- Executor side effects are explicit and confirmed by Niri events.
- Durable identity prefers profile/workspace names and match rules, not transient window IDs.
- `nimri-ipc` stays the only Niri protocol boundary.

## Dependency Rules
```
nirip.nim            -> cli, core/*, executor/*, state/*, integrations/*
cli.nim              -> core/types, core/config, core/planner, core/freezer, executor/runner
core/planner.nim     -> core/types, core/matcher
core/matcher.nim     -> core/types
core/freezer.nim     -> core/types
core/diagnostics.nim -> core/types, core/planner
executor/runner.nim  -> core/types, core/planner, state/managed (+ nimri-ipc)
executor/launcher.nim -> core/types
state/managed.nim    -> core/types
integrations/sidebard_rpc.nim -> core/types
```

## Forbidden Couplings
- Core modules must not perform process, socket, or filesystem side effects (except config/state persistence modules).
- Executor modules must not redefine policy that belongs in planner/matcher.
- CLI must not bypass typed plan/execution contracts.
- Niri transport/protocol handling must not leak outside `nimri-ipc` integration points.

## Development Environment
All compilation, testing, and tooling should run inside `devenv` for reproducible Nim/Nimble versions.

### Common commands
```bash
devenv shell -- nimble build
devenv shell -- nimble test
devenv shell -- nim c -r tests/test_planner.nim
```

### Agent rule
When compiling or testing, run through `devenv shell -- <command>` unless already inside a devenv shell.

## Technology Stack
- Nim >= 2.0
- Nimble for package/build workflow
- `results` for typed error returns
- `nimri-ipc` for typed Niri IPC request/event handling
- Stdlib async/process/options/tables/json utilities as needed

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
5. Report what was validated and any residual risk.
