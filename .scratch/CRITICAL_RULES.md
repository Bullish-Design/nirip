# CRITICAL RULES — READ EVERY SESSION

This is the session entrypoint for work in this repository.
Read this file first after each session start or compaction.

---

## 0. ABSOLUTE RULE — NO SUBAGENTS

Do all work directly in this session. Do not delegate with subagents.

---

## 1. Session Startup (Including After Compaction)

1. Read this file in full.
2. Read `.scratch/REPO_RULES.md` for repo-specific standards.
3. Identify the active project under `.scratch/projects/`.
4. Read that project's `CONTEXT.md`, `PROGRESS.md`, and `ISSUES.md` if present.
5. Resume the next pending task immediately.

---

## 2. Project Convention

Each task/feature/refactor should use a project directory:

```
.scratch/projects/<num>-<project-name>/
```

Use kebab-case names (for example `005-planner-timeout-policy`).

### Standard Files

| File | Purpose |
|------|---------|
| `PLAN.md` | Ordered implementation plan and acceptance criteria |
| `ASSUMPTIONS.md` | Constraints and context that shape decisions |
| `DECISIONS.md` | Decisions and rationale |
| `PROGRESS.md` | Task checklist and status |
| `CONTEXT.md` | Resume context after compaction |
| `ISSUES.md` | Roadblocks and linked issue notes |

Create missing files as needed.

---

## 3. Context Preservation

- Keep notes and scratch artifacts inside the active project directory.
- Update `CONTEXT.md` whenever you complete a significant chunk or shift focus.
- If a problem stalls after multiple attempts, log it in `ISSUES.md` and create a detailed `ISSUE_<num>.md`.

---

## 4. Coding Standards

- Practice TDD when practical: failing test -> implementation -> pass.
- Keep changes minimal (DRY/YAGNI).
- Maintain core/executor boundary discipline for nirip.

---

## 5. Large Documents

For large docs:
1. Write and save an outline first.
2. Append sections incrementally.
3. Avoid single-pass generation of very large files.

---

## 6. Continue Until Done

After compaction/startup, continue from project context and complete the active scope unless redirected by the user.
