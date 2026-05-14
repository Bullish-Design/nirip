# Skill: Nirip Change Validation

## Purpose
Run practical validation for nirip changes and report clearly what was verified.

## Use This Skill When
- Editing any `src/nirip/` module.
- Changing profile/planner/executor contracts.
- Preparing an implementation report.

## Validation Ladder
1. Static sanity:
   - `grep "<symbol-or-field>" src/nirip tests -rn`

2. Lint:
   - `devenv shell -- ruff check src/nirip/`

3. Type check:
   - `devenv shell -- ty check src/nirip/`

4. Tests:
   - Run targeted tests first for changed modules.
   - Run broader suite for contract-level changes.

5. Contract checks:
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