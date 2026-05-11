# Skill: Nirip Change Validation

## Purpose
Run practical validation for nirip changes and report clearly what was verified.

## Use This Skill When
- Editing any `src/` module.
- Changing profile/planner/executor contracts.
- Preparing an implementation report.

## Validation Ladder
1. Static sanity:
- `rg "<symbol-or-field>" src tests -n`

2. Build:
- `devenv shell -- nimble build`

3. Tests:
- Run targeted tests first for changed modules.
- Run broader suite for contract-level changes.

4. Contract checks:
- Verify planner output aligns with executor expectations.
- Verify config parsing/validation matches documented schema.

## Reporting Template
- Files changed:
- Validation run:
- Result:
- Residual risks:

## Guardrails
- Do not claim live Niri behavior was tested unless it was.
- If full tests cannot run, state exact scope executed.
- If interfaces changed, explicitly note compatibility risk.
