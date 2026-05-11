# REPO RULES — nirip

## ABSOLUTE RULES — READ FIRST

1. **NO SUBAGENTS** — Do all work directly in this session.
2. **RESUME AFTER COMPACTION** — Re-read `.scratch/CRITICAL_RULES.md`, then project context files, and continue.

---

Repo-specific standards and conventions. Loaded after `CRITICAL_RULES.md`.
These rules are in addition to universal rules.

---

## Coding Standards (repo-specific)

- Keep `core/*` deterministic and side-effect free.
- Keep `executor/*` responsible for process and IPC side effects.
- Prefer typed errors/results over string-only failures.
- Preserve compatibility for profile schema changes; document any breaking change.

---

## Key Reference Files

| Document | Path |
|----------|------|
| Agent/project boundaries | `AGENTS.md` |
| Final architecture concept | `.scratch/projects/004-final-concept/FINAL_CONCEPT.md` |
| Nirip implementation details | `.scratch/projects/004-final-concept/NIRIP_IMPLEMENTATION_GUIDE.md` |

---

## Architecture Overview

`nirip` is a declarative Niri workspace orchestrator with:
- Pure planning/matching/freezing in `core/*`.
- Execution and event-confirmation in `executor/*`.
- Optional persisted managed state in `state/*`.
- Optional integration adapters in `integrations/*`.

---

## Test Suite

- Use `devenv shell -- nimble test` for suite runs.
- Prefer targeted module tests first, then full suite.
- Live Niri-dependent tests must skip cleanly without `$NIRI_SOCKET`.
