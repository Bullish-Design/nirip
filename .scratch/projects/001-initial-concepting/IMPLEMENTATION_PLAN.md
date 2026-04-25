# IMPLEMENTATION PLAN: NIRIP

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

- Browser/editor deep-state plugins.
- Daemon/autosave as primary workflow.
- Destructive window-closing flows by default.

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
    operations.py
  plugins/
    base.py
    registry.py
  state/
    db.py
    models.py
tests/
  unit/
  integration/
  fixtures/
flake.nix
home-manager/
  modules/
    nirip.nix
pkgs/
  default.nix
```

## 5. Workstreams

### 5.1 Workstream A: Project Foundation

Deliverables:

- `src/` package structure and module stubs.
- CLI entrypoint wiring.
- Logging policy and error taxonomy.
- Local developer commands (lint/type/test).

Acceptance criteria:

- `nirip --help` renders command tree.
- Static checks run locally without runtime dependencies on live Niri.

### 5.2 Workstream B: Profile Configuration System

Deliverables:

- Pydantic models for profile schema (`version`, `options`, `workspaces`, `columns`, `windows`, `match`, `layout`).
- YAML/JSON loader.
- Validation layer for uniqueness and schema semantics.
- Freeze serializer with stable ordering.

Acceptance criteria:

- Invalid profiles return targeted validation errors.
- Roundtrip `load -> model -> dump` preserves meaning and field defaults.
- Window/workspace ID uniqueness checks are enforced.

### 5.3 Workstream C: Niri IPC Client

Deliverables:

- Unix socket connection from `$NIRI_SOCKET`.
- Typed request helpers: `Version`, `Outputs`, `Workspaces`, `Windows`, `Action`.
- Event stream reader.
- Error normalization and unknown-field-tolerant parsing.

Acceptance criteria:

- Request/reply layer works against a fake IPC server.
- Timeouts and malformed replies map to clear error classes.
- Event stream disconnect/reconnect failure path is explicit.

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
- Focus verification before focus-sensitive actions.
- Launcher abstraction (`Spawn` vs subprocess policy).
- Bounded waits for launched/matched windows.

Acceptance criteria:

- Re-running `load` avoids unnecessary duplicate windows.
- Load failures include per-window reasons and next actions.
- Reconciler can recover from partial drift by re-evaluating state.

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

- Plugin execution.
- `diff` command.
- Daemon/watch workflows.
- Close/kill semantics.

Distribution is part of MVP exit quality:

- GitHub repo is installable via Home Manager flake URL.
- Installation path is documented and validated on at least one NixOS host.

## 7. Milestones and Exit Criteria

### M0: Skeleton + Toolchain

Exit criteria:

- Package/CLI scaffold and test harness in place.
- Lint/type/test local commands available.

### M1: Config + IPC Contract

Exit criteria:

- Profile models + loader + validator done.
- IPC client supports core request types and fake-server tests.

### M2: Snapshot + Matching

Exit criteria:

- Snapshot derivation and column reconstruction implemented.
- Matching engine stable with confidence threshold diagnostics.

### M3: Planner + Plan Command

Exit criteria:

- Operation graph generated from state/profile.
- `plan` output clearly shows create/launch/move/no-touch sets.

### M4: Reconciler + Load Command

Exit criteria:

- `load` executes plan safely and idempotently in common cases.
- Focus-sensitive operations guarded by verification checks.

### M5: Freeze + Doctor + MVP Release Candidate

Exit criteria:

- `freeze --all` emits valid portable profile files.
- `doctor` validates environment/profile correctness.
- MVP scenario from concept (`simple-dev`) succeeds end-to-end.

### M6: GitHub + Nix Distribution Ready

Exit criteria:

- Repository published with semantic tags.
- `flake.nix` outputs package, app, and Home Manager module.
- Home Manager install-from-URL flow tested end-to-end.
- README includes copy-paste install snippets for flake and Home Manager.

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
- SQLite state DB for managed window history and run logs.
- Output alias/fallback policy.
- Plugin API skeleton and one proof-of-concept plugin.
- `diff` command with drift categories.
- Nixpkgs packaging polish (if upstreaming outside flake-local package).

Exit criteria:

- `diff` reports `OK / DRIFT / MISSING` clearly.
- Plugin hooks can validate config and contribute launch/match behavior.
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

1. Scaffold `src/nirip` modules and CLI command stubs.
2. Implement profile schema in `config/models.py`.
3. Build YAML/JSON loader and validator.
4. Implement IPC client request transport and typed responses.
5. Add fake IPC server test harness.
6. Build snapshot assembler and derived column model.
7. Implement matching scorer and diagnostics payloads.
8. Define operation dataclasses/enums.
9. Implement planner + `plan` command rendering.
10. Implement reconciler apply loop + bounded refresh.
11. Implement launcher abstraction and timeout policy.
12. Implement `doctor` command checks.
13. Implement `freeze --all` serializer.
14. Add example profile fixtures and end-to-end smoke tests.
15. Add `flake.nix`, package derivation, and Home Manager module.
16. Add CI jobs for `nix flake check` and module evaluation.
17. Draft README walkthrough, troubleshooting, and install-by-URL docs.

## 16. Definition of Done

MVP is done when:

- All MVP commands work on a representative Niri setup.
- Repeat `load` is stable and does not aggressively duplicate or move unrelated windows.
- `freeze` output is valid and reusable.
- Errors are actionable, not generic.
- Test suite and docs are good enough for external early adopters.
- A user can install `nirip` from GitHub via Home Manager flake URL.

## 17. Open Decisions to Resolve Early

1. Default launch path: Niri `Spawn` vs subprocess.
2. Required strictness for workspace naming in MVP.
3. Initial confidence threshold defaults and override semantics.
4. Minimum supported Niri versions for first release.
5. Whether lockfile/concurrency guard is needed in MVP or Phase 2.
6. Whether to publish binary cache artifacts or rely on source builds first.
7. Whether to upstream module into Home Manager later or keep flake-local module.
