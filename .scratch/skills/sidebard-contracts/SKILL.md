# Skill: Nirip Runtime Contracts

## Purpose
Maintain clear, typed contracts across profile config, planner outputs, and executor/integration boundaries.

## Use This Skill When
- Adding/changing profile schema fields.
- Adding new operation/effect types in planner/executor flow.
- Adjusting matcher semantics or reconciliation policy.
- Auditing drift between CLI commands and underlying contract behavior.

## Canonical Ownership
- Domain and operation types: `src/core/types.nim`
- Profile parsing/validation: `src/core/config.nim`
- Match + planning semantics: `src/core/matcher.nim`, `src/core/planner.nim`
- Freeze/export semantics: `src/core/freezer.nim`
- Execution/confirmation: `src/executor/*.nim`
- CLI contract surface: `src/cli.nim`

## Ownership Rules
1. Profile and operation schemas live in core modules.
2. Executor modules apply operations, confirm outcomes, and report typed execution results.
3. Integration modules only translate external inputs/outputs.
4. Policy (what should happen) belongs in planner/matcher, not adapter glue.

## Workflow
1. Classify change: contract, policy, or transport/execution mechanics.
2. Edit canonical files for that concern.
3. Update tests for typed mapping and behavior.
4. Validate targeted build/tests.
5. Report changed files, verified behavior, and residual risks.

## Guardrails
- Never duplicate schema definitions across layers.
- Never hide planner policy in side-effect wrappers.
- Never change contract semantics without test updates.

## Done Criteria
- Boundaries stay explicit and consistent.
- CLI and internals stay aligned.
- Tests cover changed contract behavior.
