# IMPLEMENTATION PLAN: NIRIP (Revised)

## 1. Purpose and Scope

This plan translates `NIRIP_CONCEPT.md` into an execution-ready roadmap for building `nirip`: a typed Python library and CLI for loading, freezing, planning, and reconciling declarative Niri workspace/window profiles.

In scope for this plan:

- MVP delivery for `load`, `freeze`, `plan`, `doctor`.
- Architecture and package scaffolding aligned with the concept.
- Testing strategy and release quality gates.
- GitHub-first distribution and release workflow.
- Nix flake packaging with Home Manager module support for URL-based install.
- Post-MVP Phase 2 and Phase 3 sequencing.

Out of scope for MVP:

- Plugin system (API, schema fields, hooks) — deferred to Phase 2.
- Output aliases and multi-monitor fallback logic — deferred to Phase 2.
- `diff` command — deferred to Phase 2.
- Browser/editor deep-state plugins.
- Daemon/autosave as primary workflow.
- Destructive window-closing flows by default.

## 1.1 Key Technical Decisions

These decisions are resolved and apply throughout implementation:

| Decision | Choice | Rationale |
|---|---|---|
| CLI framework | `click` | Mature, composable command groups, broad ecosystem |
| Async runtime | `asyncio` (stdlib) | No third-party dependency; CLI uses `asyncio.run()` entry point |
| YAML library | `pyyaml` | Sufficient for MVP; `ruamel.yaml` added in Phase 2 if roundtrip preservation needed |
| Default launch mode | Niri `Spawn` / `SpawnSh` | Correct Wayland session environment without library replication |
| Size semantics | `(0, 1.0]` = proportion, `> 1.0` = logical pixels, `null` = default | `1.0` means full proportion, not 1 pixel |
| Workspace names | Required in profile schema | Named workspaces are Niri's durable anchor |
| Plugin schema | Not in MVP profile schema | Deferred until core reconciler is proven |
| Output aliases | Not in MVP | Raw output names only; aliases designed in Phase 2 |

## 2. Guiding Product Principles

- Declarative profiles are source of truth.
- Conservative defaults; avoid destructive actions.
- Explainable behavior over hidden automation.
- Best-effort layout fidelity, not pixel-perfect guarantees.
- Niri-specific correctness over compositor-agnostic abstractions.

## 3. Target Delivery Strategy

Use incremental phases with strict quality gates:

1. Foundation (repo/package/tooling skeleton, config models, IPC client).
2. MVP Core (snapshot, planner, reconciler, CLI commands).
3. Distribution (GitHub repo hardening, flake package, Home Manager module).
4. Hardening (diagnostics quality, integration tests, docs/examples).
5. Phase 2 extensions (event-stream store, state DB, plugin skeleton, `diff`).
6. Phase 3 productization (watch mode, autosave, unload semantics, TUI helper).

## 4. Architecture and Repository Shape

Target package layout:

```text
src/nirip/
  __init__.py
  cli.py
  errors.py                    # Error taxonomy (IpcError, ConfigError, MatchError, etc.)
  ipc/
    client.py
    models.py
    requests.py
    events.py
  config/
    models.py
    loader.py
    freezer.py
    validator.py
  engine/
    snapshot.py
    planner.py
    reconciler.py
    matcher.py
    layout.py
    launcher.py
    diagnostics.py
    operations.py              # Operation dataclass definitions (EnsureWorkspace, LaunchWindow, etc.)
tests/
  unit/
  integration/
  fixtures/                    # Stored Niri JSON snapshots for testing
  conftest.py
  fake_niri.py                 # Fake IPC server for protocol tests
flake.nix
home-manager/
  modules/
    nirip.nix
pkgs/
  default.nix
```

Notes:
- `plugins/` and `state/` modules are deferred to Phase 2.
- `operations.py` contains operation dataclass/enum definitions used by the planner. Operation *execution* logic lives in `reconciler.py`.
- Test infrastructure lives in `tests/`, not inside the shipped package.

## 5. Workstreams

### 5.1 Workstream A: Project Foundation

Deliverables:

- `src/nirip/` package structure and module stubs.
- CLI entrypoint wiring using `click` with command groups for `load`, `freeze`, `plan`, `doctor`.
- `load --dry-run` as an alias for `plan`.
- `errors.py` with the full error taxonomy hierarchy:
  - `NiripError` (base)
  - `IpcError` (connection, timeout, malformed response)
  - `ConfigError` (schema validation, semantic validation)
  - `MatchError` (no candidates, ambiguous, below threshold)
  - `ReconcileError` (action failed, state drift)
  - `LaunchError` (command not found, process exit, window timeout)
  - `FreezeError` (no connection, empty workspace set)
- Async entry point pattern: CLI calls `asyncio.run()` to enter async runtime.
- Logging policy (structured logging with per-run ID).
- `pyproject.toml` updated with full dependency list:
  - Runtime: `pydantic >= 2.12`, `click >= 8.0`, `pyyaml >= 6.0`
  - Dev: existing deps plus `pytest-asyncio >= 0.23`
- Local developer commands (lint/type/test).

Acceptance criteria:

- `nirip --help` renders command tree with `load`, `freeze`, `plan`, `doctor` subcommands.
- `nirip load --dry-run` routes to plan logic.
- All error classes importable and tested.
- Static checks run locally without runtime dependencies on live Niri.

### 5.2 Workstream B: Profile Configuration System

Deliverables:

- Pydantic models for profile schema (`version`, `options`, `workspaces`, `columns`, `windows`, `match`, `layout`).
  - Workspace `name` is required (not optional).
  - `plugins` field is not present in MVP schema.
  - `output` uses raw output names (no alias resolution).
  - `match.count` field for multi-window expectations.
  - `focus_after_load` uses `workspace_name/window_id` path syntax.
- YAML loader using `pyyaml`. JSON loader via Pydantic's native JSON support.
- Validation layer for uniqueness and schema semantics.
- Freeze serializer with stable ordering.

Acceptance criteria:

- Invalid profiles return targeted `ConfigError` instances with field references.
- Profiles with missing workspace names are rejected.
- Roundtrip `load -> model -> dump` preserves meaning and field defaults.
- Window/workspace ID uniqueness checks are enforced.
- Size values are correctly normalized (proportion vs pixel threshold at 1.0).

### 5.3 Workstream C: Niri IPC Client

Deliverables:

- Asyncio-based Unix socket connection from `$NIRI_SOCKET`.
- Typed request helpers: `Version`, `Outputs`, `Workspaces`, `Windows`, `Action`.
- Event stream reader on a separate socket connection.
- Error normalization using `IpcError` hierarchy.
- Unknown-field-tolerant Pydantic parsing with `raw: dict[str, Any]` field on all IPC models for forward compatibility.

Acceptance criteria:

- Request/reply layer works against a fake IPC server.
- Timeouts and malformed replies map to `IpcError` subclasses.
- Event stream disconnect/reconnect failure path is explicit.
- Unknown fields in Niri JSON responses are preserved in `raw` and do not cause parse failures.

### 5.4 Workstream D: Snapshot and Matcher

Deliverables:

- Snapshot model joining windows, workspaces, outputs.
- Derived column reconstruction from `pos_in_scrolling_layout`.
- Matching engine with score contributions (`app_id`, regex title, optional PID hints).
- Confidence threshold behavior from profile options.

Acceptance criteria:

- Matching deterministically selects candidates or reports ambiguity.
- Snapshot layer handles missing optional metadata safely.

### 5.5 Workstream E: Planner and Operations

Deliverables:

- Operation model (`EnsureWorkspace`, `LaunchWindow`, `MoveWindowToWorkspace`, `ConsumeWindowIntoColumn`, `SetColumnWidth`, `SetWindowHeight`, `FocusWindow`, etc.).
- Ordered planning logic from current snapshot + profile.
- Dry-run rendering for `plan`.

Acceptance criteria:

- Planner emits no side effects.
- Plan output is stable across identical input states.
- Non-managed windows are untouched under default options.

### 5.6 Workstream F: Reconciler and Launcher

Deliverables:

- Reconciler applying one operation at a time with state refresh.
- Focus verification before every focus-sensitive action (consume, move column).
- Column construction algorithm (4 phases: placement → formation → ordering → sizing) with:
  - Single-retry on focus-shift failures.
  - Partial-success reporting for incomplete columns.
  - Right-to-left column ordering to avoid index shifting.
  - Verification of `pos_in_scrolling_layout` after each consume operation.
- Launcher using Niri `Spawn`/`SpawnSh` as default launch mode.
  - `cwd` and `env` passed via `SpawnSh` shell wrapping.
  - Launch timestamp recorded for match-scoring.
- Bounded waits for launched/matched windows.
- Replan strategy: up to 3 replans on state drift before declaring partial failure.

Acceptance criteria:

- Re-running `load` avoids unnecessary duplicate windows.
- Load failures include per-window `ReconcileError` / `LaunchError` with reasons and next actions.
- Reconciler can recover from partial drift by re-evaluating state.
- Column construction reports partial success (not silent failure) when windows cannot be grouped.

### 5.7 Workstream G: Diagnostics UX

Deliverables:

- `plan` human-readable intent view.
- `doctor` environment/profile checks.
- Structured failure explanations with candidate-match scoring.

Acceptance criteria:

- Diagnostics show what will change and what will not change.
- Doctor surfaces missing socket, invalid regex, and unsafe options.

### 5.8 Workstream H: Freeze Pipeline

Deliverables:

- Freeze algorithm for selected workspaces.
- Column/window ordering capture.
- Best-effort capture of widths/heights and floating state.
- Generated match scaffolding and unknown-command diagnostics.

Acceptance criteria:

- `freeze --all` generates valid schema output.
- Frozen output can be fed into `plan` and `doctor` without manual edits.

### 5.9 Workstream I: Testing and CI

Deliverables:

- Unit tests for config, matching, planner, freeze serializer.
- Fake Niri IPC protocol tests.
- Fixture-based tests using windows/workspaces/events JSON.
- Optional integration test path against real Niri environment.

Acceptance criteria:

- Unit suite covers all core modules.
- Contract tests validate request and response compatibility assumptions.

### 5.10 Workstream J: Documentation and Adoption

Deliverables:

- README with safety model and command flow.
- Example profiles (simple dev, multi-workspace).
- Troubleshooting section for matching and workspace dynamics.

Acceptance criteria:

- New user can run `doctor -> plan -> load -> freeze` from docs alone.

### 5.11 Workstream K: Distribution and Nix/Home Manager Integration

Deliverables:

- Public GitHub repository structure and contribution metadata (`README`, `LICENSE`, issue/PR templates, changelog policy).
- `flake.nix` exposing:
  - package output (`packages.<system>.default`) for `nirip`.
  - app output (`apps.<system>.nirip`) for direct execution.
  - Home Manager module output (`homeManagerModules.default`).
- Home Manager module (`home-manager/modules/nirip.nix`) with options:
  - `programs.nirip.enable`
  - `programs.nirip.package`
  - `programs.nirip.settings` (optional config file generation)
  - `programs.nirip.profiles` (optional profile file deployment)
- Example Home Manager usage for URL-based flake input install.
- Tag-based release workflow for stable installation pins.

Acceptance criteria:

- User can install from GitHub URL in Home Manager without local path checkout.
- `nix build .#nirip` and `nix run .#nirip -- --help` succeed.
- Example Home Manager configuration evaluates and activates successfully.

Reference install snippet (to include in README):

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
    nirip.url = "github:<your-user-or-org>/nirip";
  };

  outputs = { nixpkgs, home-manager, nirip, ... }: {
    homeConfigurations."<user>" = home-manager.lib.homeManagerConfiguration {
      pkgs = import nixpkgs { system = "x86_64-linux"; };
      modules = [
        nirip.homeManagerModules.default
        {
          programs.nirip.enable = true;
        }
      ];
    };
  };
}
```

## 6. MVP Feature Cut (Execution Baseline)

MVP commands:

- `nirip load <profile.yaml>`
- `nirip freeze --all`
- `nirip plan <profile.yaml>`
- `nirip doctor <profile.yaml>`

MVP capabilities:

- YAML profile support + typed validation.
- Snapshot of windows/workspaces via IPC.
- Existing window matching by `app_id` + title regex scoring.
- Launch missing windows.
- Move windows to named workspaces.
- Basic column grouping/order with best-effort sizing.
- Explicit diagnostics for unresolved/mismatched windows.

Explicitly deferred:

- Plugin system (API, schema fields, hooks).
- Output aliases and multi-monitor fallback logic.
- `diff` command.
- Daemon/watch workflows.
- Close/kill semantics.
- Direct subprocess launch mode (`launch_mode: subprocess`).
- Roundtrip YAML preservation (ruamel.yaml).

Distribution is part of MVP exit quality:

- GitHub repo is installable via Home Manager flake URL.
- Installation path is documented and validated on at least one NixOS host.

## 7. Milestones, Workstream Mapping, and Exit Criteria

### M0: Skeleton + Toolchain — Workstream A

Exit criteria:

- Package/CLI scaffold with click commands in place.
- Error taxonomy defined and tested.
- `asyncio.run()` entry point wired.
- `pyproject.toml` has full dependency list.
- Lint/type/test local commands available.

### M1: Config + IPC Contract — Workstreams B + C

Exit criteria:

- Profile models + loader + validator done with required workspace names.
- IPC client supports core request types with asyncio.
- Fake IPC server test harness operational.
- Real Niri JSON snapshots captured as test fixtures.

### M2: Snapshot + Matching — Workstream D

Exit criteria:

- Snapshot derivation and column reconstruction implemented.
- Matching engine stable with exact `app_id` + `title_regex` as primary signals.
- Confidence threshold diagnostics show candidate scores.
- PID-based matching implemented as best-effort.

### M3: Planner + Plan Command — Workstream E

Exit criteria:

- Operation dataclasses defined in `operations.py`.
- Planner generates canonical ordered operation list from state/profile.
- `plan` output clearly shows create/launch/move/no-touch sets.
- `plan` command is usable before `load` is implemented (ships first).

### M4: Reconciler + Load Command — Workstream F

Exit criteria:

- `load` executes plan safely and idempotently in common cases.
- `load --dry-run` aliases to `plan`.
- Column construction uses 4-phase algorithm with partial-success reporting.
- Focus-sensitive operations guarded by verification checks.
- Replan on drift (up to 3 attempts).

### M5: Freeze + Doctor + MVP Release Candidate — Workstreams G + H + I

Exit criteria:

- `freeze --all` emits valid portable profile files (named workspaces only by default).
- `doctor` validates environment/profile correctness.
- MVP scenario from concept (`simple-dev`) succeeds end-to-end.
- Unit and contract test suites pass.
- At least one end-to-end scenario verified on live Niri.

### M6: GitHub + Nix Distribution Ready — Workstreams J + K

Exit criteria:

- Repository published with semantic tags.
- `flake.nix` outputs package, app, and Home Manager module.
- Home Manager install-from-URL flow tested end-to-end.
- README includes copy-paste install snippets for flake and Home Manager.

### Performance Targets (order-of-magnitude)

| Command | Target | Notes |
|---|---|---|
| `plan` | < 1s for 5-workspace, 20-window profile | IPC round-trips only |
| `freeze --all` | < 2s | Single snapshot, serialization |
| `load` (most windows exist) | < 5s | Matching + minimal reconciliation |
| `load` (cold start, all launched) | < timeout (default 20s) | Dominated by app launch waits |
| `doctor` | < 1s | Validation + environment checks |

## 8. Dependency Graph (Critical Path)

1. Foundation must precede all streams.
2. Config and IPC can proceed in parallel.
3. Snapshot depends on IPC models.
4. Matcher depends on snapshot + config.
5. Planner depends on matcher + config + snapshot.
6. Reconciler depends on planner + IPC actions + launcher.
7. `load` depends on reconciler.
8. `freeze` depends on snapshot + config serializer.
9. Diagnostics depend on planner/matcher/validator.
10. Distribution depends on CLI packaging stability and docs.

## 9. Testing Plan and Coverage Targets

### 9.1 Unit Tests

- `config.models`: schema defaults, validation errors, uniqueness constraints.
- `engine.matcher`: score function behavior, ambiguity outcomes.
- `engine.planner`: operation ordering and no-side-effect guarantees.
- `config.freezer`: deterministic serialization from fixture snapshots.

### 9.2 Contract/Protocol Tests

- Fake IPC server request-reply compliance.
- Event stream parse handling for unknown fields/variants.
- Error and timeout propagation.

### 9.3 Integration Tests

- Fixture-driven pseudo-integration with stored Niri JSON.
- Optional live-Niri gated tests for `doctor`, `plan`, and controlled `load`.

### 9.4 Release Gate for MVP

- All unit and contract tests passing.
- At least one end-to-end scenario passing on live Niri.
- No critical severity bugs in matching, workspace targeting, or safety defaults.
- `nix flake check` passes.
- Home Manager module evaluation test passes.

## 10. Safety and Risk Controls

Controls implemented in MVP:

- Conservative defaults: no closing/moving unmanaged windows by default.
- Match confidence threshold enforcement.
- Explicit unresolved-match reporting.
- Dry-run planning before apply.

Risk-specific mitigations:

- Window ambiguity: score reasons + stronger matcher hints.
- Focus sensitivity: verify focus before each focus-dependent action.
- Workspace dynamics: named workspace anchoring, index treated as hint.
- Launch nondeterminism: bounded waits, match-existing before launch.

## 11. Operational Observability

Add structured logging with per-load run ID:

- Planned operations count by type.
- Action success/failure with timing.
- Match score summaries per managed window.
- Replan count and drift reasons.

Store historical runs (post-MVP Phase 2 DB) for troubleshooting trends.

## 12. Phase 2 Plan (Post-MVP)

Scope:

- Event-stream-backed continuously refreshed state model.
- SQLite state DB for managed window history and run logs (using `sqlmodel`).
- Output alias/fallback policy (design and implement `outputs.aliases` schema).
- Plugin API skeleton and one proof-of-concept plugin (designed based on proven reconciler behavior).
- `plugins` field added to `WindowSpec` schema.
- `diff` command with drift categories.
- Direct subprocess launch mode (`launch_mode: subprocess`).
- `ruamel.yaml` for roundtrip YAML preservation in freeze.
- `rich` for enhanced CLI output formatting.
- Lockfile/concurrency guard for concurrent profile loads.
- `.desktop` file inference for freeze command suggestions.
- Nixpkgs packaging polish (if upstreaming outside flake-local package).

Exit criteria:

- `diff` reports `OK / DRIFT / MISSING` clearly.
- Plugin hooks can validate config and contribute launch/match behavior.
- Output aliases resolve correctly with fallback behavior documented.
- DB remains optimization-only; profile + live state remains source of truth.

## 13. Phase 3 Plan (Productization)

Scope:

- Watch/daemon mode and autosave profiles.
- Profile unload/close semantics with explicit user confirmation.
- TUI or fuzzy-picker launcher integration.
- Import path from adjacent ecosystem formats if practical.

Exit criteria:

- Optional background workflows do not compromise explicit file-based UX.
- Unload semantics remain opt-in and safe.

## 14. Roles and Execution Model

Single-team model with rotating ownership:

- Core runtime owner: IPC/snapshot/planner/reconciler.
- Config/UX owner: schema/loader/freeze/diagnostics/CLI.
- Quality owner: tests/fixtures/CI release gates.
- Distribution owner: flake/module/release tagging/install docs.

Weekly cadence:

- Early week: implementation + tests.
- Midweek: integration and drift bug triage.
- End week: docs/examples and milestone review.

## 15. Initial Task Backlog (Ready-to-Implement)

### M0: Foundation
1. Update `pyproject.toml` with full dependencies (`click`, `pyyaml`, `pytest-asyncio`).
2. Scaffold `src/nirip/` modules and `tests/` structure.
3. Implement `errors.py` error taxonomy.
4. Wire CLI entrypoint with click command stubs (`load`, `freeze`, `plan`, `doctor`).
5. Wire `load --dry-run` alias to plan.
6. Set up `asyncio.run()` entry point pattern.

### M1: Config + IPC
7. Implement profile schema in `config/models.py` (required workspace names, no plugins field).
8. Build YAML/JSON loader with `pyyaml`.
9. Build validator (uniqueness, regex compilation, size normalization).
10. Capture real Niri IPC JSON snapshots as test fixtures.
11. Implement asyncio-based IPC client with `raw` field preservation.
12. Add fake IPC server test harness in `tests/fake_niri.py`.

### M2: Snapshot + Matching
13. Build snapshot assembler and derived column model.
14. Implement matching scorer (exact `app_id` + `title_regex` first, PID best-effort).

### M3: Planner
15. Define operation dataclasses/enums in `operations.py`.
16. Implement planner with canonical operation ordering.
17. Implement `plan` command rendering (ship before `load`).

### M4: Reconciler
18. Implement 4-phase column construction algorithm.
19. Implement reconciler apply loop with focus verification and bounded refresh.
20. Implement launcher using Niri `Spawn`/`SpawnSh`.
21. Add replan-on-drift logic (up to 3 attempts).

### M5: Freeze + Doctor + Testing
22. Implement `freeze --all` serializer (named workspaces only by default).
23. Implement `doctor` command checks.
24. Add unit tests for config, matching, planner, freeze.
25. Add end-to-end smoke tests with fixture data.

### M6: Distribution
26. Add `flake.nix`, package derivation, and Home Manager module.
27. Add CI jobs for `nix flake check` and module evaluation.
28. Draft README walkthrough, troubleshooting, and install-by-URL docs.
29. Add example profile fixtures for documentation.

## 16. Definition of Done

MVP is done when:

- All MVP commands work on a representative Niri setup.
- Repeat `load` is stable and does not aggressively duplicate or move unrelated windows.
- `freeze` output is valid and reusable.
- Errors are actionable, not generic.
- Test suite and docs are good enough for external early adopters.
- A user can install `nirip` from GitHub via Home Manager flake URL.

## 17. Decisions Log

### Resolved

1. **Default launch path:** Niri `Spawn` / `SpawnSh`. Subprocess mode deferred to Phase 2.
2. **Workspace naming strictness:** Required. Workspace `name` is a mandatory field.
3. **CLI framework:** `click`.
4. **Async runtime:** `asyncio` (stdlib). CLI uses `asyncio.run()`.
5. **YAML library:** `pyyaml` for MVP. `ruamel.yaml` in Phase 2 if needed.
6. **Size semantics:** `(0, 1.0]` = proportion, `> 1.0` = logical pixels, `null` = default.
7. **Plugin schema in MVP:** No. `plugins` field deferred to Phase 2.
8. **Output aliases in MVP:** No. Raw output names only.
9. **Column construction:** Best-effort with partial-success reporting. 4-phase algorithm.
10. **Lockfile/concurrency guard:** Deferred to Phase 2.

### Still Open

1. Initial confidence threshold defaults and override semantics (resolve during M2).
2. Minimum supported Niri versions for first release (resolve during M1 after IPC fixture capture).
3. Whether to publish binary cache artifacts or rely on source builds first (resolve during M6).
4. Whether to upstream module into Home Manager later or keep flake-local module (resolve post-MVP).
