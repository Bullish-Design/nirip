# Skill: Nirip Structure Navigation

## Purpose
Place changes in the correct `nirip` layer and preserve separation between pure planning logic and execution/integration side effects.

## Use This Skill When
- A task is ambiguous about module placement.
- You need fast repo orientation before implementation.
- You need to prevent boundary/coupling regressions.

## Mental Model
- Entrypoints: `src/nirip.nim`, `src/cli.nim`
- Pure domain: `src/core/*.nim`
- Execution side effects: `src/executor/*.nim`
- Managed state persistence: `src/state/*.nim`
- Integrations/adapters: `src/integrations/*.nim`
- Tests and fixtures: `tests/**`

## Workflow
1. Start from the affected interface (CLI, profile config, planner output, executor action).
2. Place behavior in pure `core/*` modules first when possible.
3. Keep process/IPC/file side effects in executor/state/integration modules.
4. Use `rg` to verify call sites and boundary consistency.

## Handy Commands
- `rg --files src tests`
- `rg "proc\s+|type\s+|template\s+" src -n`
- `rg "profile|match|plan|operation|execute|snapshot|workspace" src tests -n`

## Done Criteria
- Change is in the correct layer.
- Core/executor boundary remains clean.
- No duplicated ownership or contract drift introduced.
