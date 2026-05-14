# REPO RULES — nirip

## ABSOLUTE RULES — READ FIRST

1. **NO SUBAGENTS** — Do all work directly in this session.
2. **RESUME AFTER COMPACTION** — Re-read `.scratch/CRITICAL_RULES.md`, then project context files, and continue.

---

Repo-specific standards and conventions. Loaded after `CRITICAL_RULES.md`.
These rules are in addition to universal rules.

---

## Coding Standards (repo-specific)

- Keep `src/nirip/spec`, `src/nirip/resolve`, and `src/nirip/planning` deterministic and side-effect free.
- Keep `src/nirip/execution`, `src/nirip/facade`, and `src/nirip/cli` responsible for process/IPC/runtime side effects.
- Prefer typed errors/results over string-only failures.
- Preserve compatibility for session schema changes; document any breaking change.

---

## Key Reference Files

| Document | Path |
|----------|------|
| Agent/project boundaries | `AGENTS.md` |
| Final architecture concept | `.scratch/projects/006-v3-revised-python-concept/NIRIP_CONCEPT_FINAL.md` |
| Nirip implementation details | `.scratch/projects/006-v3-revised-python-concept/NIRIP_IMPLEMENTATION_GUIDE.md` |

---

## Architecture Overview

`nirip` is a declarative Niri workspace orchestrator with:
- Spec loading/validation in `src/nirip/spec/*`.
- Pure normalization, matching, and planning in `src/nirip/resolve/*` + `src/nirip/planning/*`.
- Execution and event-confirmation logic in `src/nirip/execution/*`.
- Capture, public facade APIs, and CLI in `src/nirip/capture/*`, `src/nirip/facade/*`, and `src/nirip/cli/*`.

---

## Test Suite

- Use `devenv shell -- python -m pytest tests/` for suite runs.
- Use `devenv shell -- ruff check src/nirip tests` for linting.
- Use `devenv shell -- ty check src/nirip` for type checks.
- Prefer targeted module tests first, then full suite.
- Live Niri-dependent tests must skip cleanly without `$NIRI_SOCKET`.
