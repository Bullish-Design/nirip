# Skill: Nirip Structure Navigation

## Purpose
Place changes in the correct `nirip` layer and preserve separation between pure planning logic and execution/integration side effects.

## Use This Skill When
- A task is ambiguous about module placement.
- You need fast repo orientation before implementation.
- You need to prevent boundary/coupling regressions.

## Mental Model
- Entrypoints: `src/nirip/__main__.py`, `src/nirip/cli.py`
- Pure domain: `src/nirip/core/*.py`
- Execution side effects: `src/nirip/executor/*.py`
- Managed state persistence: `src/nirip/state/*.py`
- Integrations/adapters: `src/nirip/integrations/*.py`
- Tests and fixtures: `tests/**`

## Workflow
1. Start from the affected interface (CLI, profile config, planner output, executor action).
2. Place behavior in pure `core/*` modules first when possible.
3. Keep process/IPC/file side effects in executor/state/integration modules.
4. Use `grep` or `rg` to verify call sites and boundary consistency.

## Handy Commands
- `grep --files src/nirip tests`
- `grep -r "def |class " src/nirip -n`
- `grep -r "profile\|match\|plan\|operation\|execute\|snapshot\|workspace" src/nirip tests -n`

## Done Criteria
- Change is in the correct layer.
- Core/executor boundary remains clean.
- No duplicated ownership or contract drift introduced.