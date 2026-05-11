# Skill: Nirip Diagnostics and Explainability

## Purpose
Keep nirip diagnostics actionable by preserving typed errors, clear operation context, and explainable plan/execution output.

## Use This Skill When
- Editing error types/messages.
- Adding logs around planning, reconciliation, or execution confirmation.
- Investigating profile parsing, match failures, or timeout behavior.

## Primary Targets
- `src/core/diagnostics.nim`
- `src/core/config.nim`
- `src/core/planner.nim`
- `src/executor/*.nim`
- `src/cli.nim`
- `tests/**` (especially failure-path tests)

## Workflow
1. Identify failure origin and propagation path.
2. Preserve low-level detail near failing boundary.
3. Add high-level context without obscuring root cause.
4. Validate failure and success paths with tests.

## Guardrails
- Do not replace typed errors with opaque strings.
- Do not log sensitive command/env values unnecessarily.
- Do not add noisy logs that hide operation sequencing.

## Done Criteria
- Errors are typed and debuggable.
- Output explains what failed and where.
- Failure-path tests reflect changed behavior.
