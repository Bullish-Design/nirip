# CONCEPT REVIEW: nirip

**Reviewer:** Claude (automated analysis)
**Date:** 2026-04-25
**Documents reviewed:** `NIRIP_CONCEPT.md`, `IMPLEMENTATION_PLAN.md`
**Verdict:** Strong concept with a well-scoped MVP. Several design areas need resolution before implementation begins.

---

## 1. Executive Assessment

The concept document is unusually thorough for an early-stage feasibility analysis. It correctly identifies the product niche (declarative project profiles, not automatic session restore), maps Niri's IPC surface accurately, and makes honest scope commitments. The implementation plan translates the concept into a credible execution roadmap with appropriate phasing.

The biggest risk is not feasibility — it's execution complexity in the reconciler/layout engine, which both documents acknowledge but neither fully resolves at the design level.

**Overall quality: High.** The concept is ready to move into implementation with the caveats noted below.

---

## 2. Concept Document Analysis

### 2.1 Strengths

**Accurate problem framing.** The tmuxp analogy is the right one. The document correctly avoids the "desktop session restore" framing and commits to compositor-level orchestration with plugins for app-internal state. This is the only honest scope for a tool built on top of Niri IPC.

**Thorough IPC surface mapping.** Sections 3.1–3.6 demonstrate real familiarity with Niri's IPC model. Key details are captured: the two-socket requirement for event streaming, the eventual-consistency caveat for sequential requests, the 1-based `pos_in_scrolling_layout` indices, and the dynamic workspace disappearance behavior. These are exactly the details that would cause bugs if missed.

**Honest non-goals.** Section 4.4 is disciplined. Not promising app-internal state restore, bit-for-bit layout recovery, or compositor independence keeps the project from overselling.

**Score-based matching with explanations.** Section 8.7 is one of the strongest parts of the concept. The scoring table, the explanation format, and the confidence threshold are all well-thought-out. This is the feature that will differentiate nirip from simpler tools and make debugging tolerable.

**Safety model.** Section 11 correctly identifies the trust and destructive-action risks. Conservative defaults, no-close-by-default, and the profile-as-shell-script trust warning are all appropriate.

**Ecosystem awareness.** The comparison with `nirinit` and `niri-session-manager` (Section 16) is fair and identifies genuine differentiation: explicit profiles vs. automatic restore, dry-run/diff, and plugin extensibility.

### 2.2 Weaknesses and Gaps

**Column construction is underspecified.** Section 9.4 describes the most complex reconciliation operation — forming multi-window columns — but only sketches an approach. The focus-verify-consume-verify loop is the hardest part of the entire project. The concept acknowledges this ("Column construction is the hardest part") but does not work through failure modes:

- What happens if a window refuses to be consumed (e.g., it's a dialog or popup)?
- What happens if the target column index shifts during construction because another column was formed first?
- What happens if two profile columns share a window that matched ambiguously?

This needs a more detailed design before implementation, or a clear "we'll discover this during M4 and iterate" commitment.

**Async architecture is implied but not specified.** The IPC client interface (Section 8.2) uses `async def` signatures, the reconciler needs event-stream watching, and the launcher needs bounded waits. But the concept never states which async framework to use (asyncio, trio, anyio) or whether the CLI should be sync-with-async-internals or fully async. This matters because:

- Pydantic models are sync by nature.
- CLI frameworks (click, typer, argparse) have varying async support.
- The event stream reader will need a long-lived connection.
- Plugin hooks are declared async.

**Recommendation:** Explicitly choose asyncio as the runtime and decide whether the CLI layer uses `asyncio.run()` as its entry point.

**Size representation is ambiguous.** Section 9.5 proposes a dual interpretation: `0.62` means proportion, `1180` means pixels. This is convenient but fragile — what does `1` mean? Proportion 1.0 or 1 logical pixel? The explicit `kind: proportion` / `kind: fixed` representation is shown but described as an alternative. Pick one canonical representation and make the shorthand an explicit loader normalization step.

**Plugin system is premature for MVP.** Sections 10.1–10.9 describe a full plugin lifecycle with 5 hook types, 4 plugin concepts, and async protocol methods. The implementation plan correctly defers plugins to Phase 2, but the concept document spends significant space on plugin design that may change substantially once the core reconciler is proven. The risk is that the plugin API gets designed around assumptions about the reconciler that don't survive contact with reality.

**Recommendation:** Keep the plugin *concept* but defer the API design to Phase 2. Remove plugin-related fields (`plugins` key) from the MVP schema entirely rather than including them as ignored fields.

**Output alias resolution is vague.** Section 6.2 introduces output aliases (`primary: [DP-1, eDP-1]`) but neither document specifies:

- What happens when no alias target is connected?
- Whether resolution is first-match or priority-ordered.
- Whether aliases are profile-level or global config.
- How freeze handles aliases (does it emit the alias name or the physical output?).

**Open question #5 acknowledges this but it should be resolved before M1.**

**`focus_after_load` path syntax is undefined.** The options show `focus_after_load: backend:code/editor` but the path format (`workspace/window`) is never formally specified. Can it reference columns? Is it `workspace:column/window`? What about `workspace` alone to focus the workspace's active window?

### 2.3 Observations

**The `freeze` metadata section is useful.** The `freeze.niri_window_id` and `freeze.captured_title` fields (Section 9.2) are a smart design for roundtrip debugging. They should be explicitly marked as informational/non-authoritative in the schema.

**The Wayland Protocols section (15) is appropriately conservative.** XDG Session Management is correctly treated as a future enhancement path rather than a blocker or competitor.

**Process lineage matching may be fragile.** The scoring table gives +0.30 for "PID is descendant of launched process" but process tree inspection on Linux requires reading `/proc`, which may not work reliably for all applications (e.g., Flatpak, sandboxed apps, apps that fork and exec). This should be documented as best-effort with a clear fallback.

---

## 3. Implementation Plan Analysis

### 3.1 Strengths

**Clean milestone decomposition.** M0–M6 maps well to the dependency graph and avoids the common mistake of trying to integrate everything at once. The critical path (Section 8) is correctly identified.

**Workstream parallelism is realistic.** Config (B) and IPC (C) can genuinely proceed in parallel. The plan correctly identifies that Snapshot (D) depends on IPC and that Matcher depends on Snapshot + Config.

**Testing strategy is practical.** The fake IPC server approach (Workstream I) is the right call. Requiring a live Niri session for unit tests would make CI impossible and development painful.

**Distribution as MVP exit criteria.** Including the Nix flake and Home Manager module (Workstream K) as part of MVP rather than post-MVP is a good decision for a Niri-ecosystem tool where the target audience heavily overlaps with NixOS users.

### 3.2 Weaknesses and Gaps

**No CLI framework choice.** The plan mentions "CLI entrypoint wiring" (Workstream A) but never specifies the CLI framework. For a tool with subcommands (`load`, `freeze`, `plan`, `doctor`), the choice matters:

| Option | Pros | Cons |
|---|---|---|
| `click` | Mature, composable, well-documented | No native async, no type generation |
| `typer` | Pydantic-adjacent, type-driven, auto-help | Depends on click, async support is bolt-on |
| `argparse` | Zero dependencies, stdlib | Verbose, no auto-help quality, manual wiring |

**Recommendation:** Use `click` for stability and composability, or `typer` for Pydantic alignment. Decide before M0.

**No dependency management strategy.** The plan lists Pydantic as a dependency but doesn't address:

- PyYAML or ruamel.yaml for YAML parsing?
- Any async library needs?
- Whether SQLModel/SQLAlchemy is in scope for MVP (the concept mentions it for state DB, but state DB is Phase 2).
- Whether `rich` or similar is used for CLI output formatting.

The `pyproject.toml` currently only lists `pydantic>=2.12.5`. The full dependency set should be locked down before M0.

**Missing: error taxonomy design.** Workstream A mentions "error taxonomy" as a deliverable but the plan never defines it. For a tool that promises "actionable errors" (concept Section 12.4), the error hierarchy matters:

- IPC errors (connection refused, timeout, malformed response)
- Config errors (schema validation, semantic validation)
- Matching errors (no candidates, ambiguous candidates, below threshold)
- Reconciliation errors (action failed, state drift, window disappeared)
- Launch errors (command not found, process exited immediately)

Each category needs different user-facing messaging. Define this before M1.

**Workstream ordering could be tighter.** The plan lists 11 workstreams (A–K) but doesn't assign them to milestones explicitly. The milestone section (Section 7) defines exit criteria but doesn't say "M1 = Workstreams A + B + C done." This creates ambiguity about what work happens when.

**Suggested mapping:**

| Milestone | Workstreams |
|---|---|
| M0 | A (Foundation) |
| M1 | B (Config) + C (IPC) |
| M2 | D (Snapshot/Matcher) |
| M3 | E (Planner) |
| M4 | F (Reconciler/Launcher) |
| M5 | G (Diagnostics) + H (Freeze) + I (Testing) |
| M6 | J (Docs) + K (Distribution) |

**No performance budget.** For a tool that needs bounded waits (20s default timeout), event stream processing, and potentially many IPC round-trips per load, there should be at least a rough performance target:

- How long should `plan` take for a 5-workspace, 20-window profile?
- How long should `load` take in the common case (most windows already exist)?
- How long should `freeze --all` take?

These don't need precise numbers but should have order-of-magnitude targets (sub-second for plan/freeze, under timeout for load).

**`operations.py` is listed in the package layout but not clearly scoped.** Is this the operation dataclass definitions (which the plan attributes to Workstream E), or is it the operation execution logic (which belongs in the reconciler)? Clarify.

### 3.3 Alignment Between Concept and Plan

**Generally strong alignment.** The plan faithfully translates the concept's scope, safety model, and phasing. Notable alignment points:

- MVP feature cut matches between documents.
- Phase 2/3 sequencing is consistent.
- Safety defaults are preserved.
- Testing approach is consistent.

**Minor divergences:**

1. The concept's package is named `niri_profiles/` (Section 5.1) while the plan and `pyproject.toml` use `src/nirip/`. The plan's layout is correct for the chosen project name; the concept's layout is from an earlier naming iteration. **No action needed** — the plan supersedes.

2. The concept includes `testing/fake_niri.py` and `testing/fixtures.py` inside the package. The plan puts tests in `tests/` at the repo root. **The plan's approach is better** — test infrastructure shouldn't ship in the package.

3. The concept mentions `list`, `close`, `watch`, and `plugin` CLI commands (Section 5.2). The plan correctly defers all of these beyond MVP. **No action needed.**

4. The concept describes `launch_mode` as a per-window field (Section 8.6). The plan's open decisions (Section 17, item 1) flags this as unresolved. **Resolve during M1:** default to Niri `Spawn` for simplicity (it handles Wayland env correctly) and add subprocess mode as an option later.

---

## 4. Technical Risk Assessment

### 4.1 High Risk: Column Construction Correctness

**Risk level: High**
**Impact: Core feature (load) may produce incorrect layouts**

The column construction algorithm requires:
1. Focus window A → verify focus → consume window B into column → verify column formed → repeat for each window in column → move column to target index → verify index.

Each step can fail silently if focus shifts. The event stream helps but adds latency. The concept correctly identifies this as the hardest problem but provides no fallback strategy.

**Mitigation:** Accept "best-effort column construction" as an explicit MVP limitation. Implement a column-construction verifier that checks `pos_in_scrolling_layout` after each consume operation and reports partial success. Consider an upstream Niri feature request for ID-addressed column operations (concept Section 21, item 1) as a parallel effort.

### 4.2 Medium Risk: Window Matching False Positives

**Risk level: Medium**
**Impact: Wrong window moved to wrong workspace**

Score-based matching is the right approach, but the default threshold (0.75) and score weights are arbitrary until tested against real window populations. A profile with two Chrome windows or three Ghostty terminals will stress the matcher quickly.

**Mitigation:** Ship with conservative defaults (higher threshold, require explicit `match` rules for ambiguous apps), add `plan` output that shows all candidate scores for each window, and tune weights based on real usage in M2.

### 4.3 Medium Risk: Niri IPC Compatibility

**Risk level: Medium**
**Impact: Breakage on Niri updates**

The concept correctly notes that `niri-ipc` is not semver-stable and that non-Rust clients should tolerate unknown fields. However, the JSON wire format for actions (Section 19.1) is derived from Rust enum serialization (tagged unions), which can be surprising. For example, `{"Action":{"FocusWorkspace":{"reference":{"Name":"backend:code"}}}}` has nested tagging that must exactly match Niri's serde config.

**Mitigation:** Build a comprehensive IPC request/response test suite early (M1). Capture real Niri JSON responses as fixtures. Test against at least two Niri versions. Add `niri msg --json version` output to `doctor`.

### 4.4 Low Risk: Async Complexity

**Risk level: Low (if addressed early)**
**Impact: Development velocity, code complexity**

The project doesn't need heavy concurrency. The main async need is the event stream reader running alongside command execution. A simple `asyncio.run()` entry point with `asyncio.create_task()` for the event stream is sufficient. The risk is low if the architecture is decided upfront and high if it's deferred and discovered piecemeal.

### 4.5 Low Risk: Nix/Home Manager Packaging

**Risk level: Low**
**Impact: Distribution quality**

Python packaging in Nix is well-understood. The `pyproject.toml` is already structured correctly with hatchling. The Home Manager module is straightforward (enable flag, package override, optional config file generation). The main risk is getting the dependency closure right in the Nix derivation.

---

## 5. Schema Design Feedback

### 5.1 Profile Schema

The profile schema is well-designed. Specific feedback:

**Good decisions:**
- `version: 1` for forward compatibility.
- Window `id` as profile-local identity (not Niri window ID).
- `match` as a separate sub-object rather than top-level window fields.
- Columns as explicit ordered lists rather than inferred from window metadata.
- `options` as a top-level profile-wide config.

**Suggested changes:**

1. **Make `name` required on workspaces.** The concept recommends this but the schema allows it to be optional. For MVP, require it — anonymous workspaces add complexity without clear value.

2. **Remove `outputs.aliases` from MVP schema.** Alias resolution adds complexity. For MVP, use raw output names. Add aliases in Phase 2 when multi-monitor fallback logic is designed.

3. **Clarify `width` semantics definitively.** Adopt the rule: values in `(0, 1]` are proportions; values > 1 are logical pixels; `null` means "use Niri default." Document that `1` means proportion 1.0 (full width), not 1 pixel.

4. **Add `match.app_id` as the primary matching field, make `match.app_id_regex` secondary.** The current schema allows both, which is fine, but the scoring should heavily favor exact `app_id` matches to reduce false positives.

5. **Consider adding a `match.count` field** for profiles that expect multiple windows from the same app (e.g., two Ghostty terminals). Without this, the matcher has no way to know that window 1 and window 2 are both expected matches for the same app_id.

### 5.2 IPC Models

The concept's IPC model sketches (Section 8.2) are appropriate for the abstraction level. One addition:

- The `NiriWindow` model should include a `raw: dict[str, Any]` field to preserve unknown fields from Niri's JSON. This supports forward compatibility and debugging without requiring model updates for every Niri release.

---

## 6. Recommendations

### 6.1 Resolve Before M0

1. **CLI framework choice** (click or typer).
2. **Async strategy** (asyncio with sync CLI wrapper).
3. **YAML library choice** (PyYAML vs ruamel.yaml — recommend ruamel.yaml for roundtrip preservation in freeze).
4. **Full dependency list** in `pyproject.toml`.
5. **Error taxonomy** (at least the top-level categories).

### 6.2 Resolve Before M1

1. **Default launch mode** (recommend Niri `Spawn` for MVP simplicity).
2. **Output alias deferral** (cut from MVP schema).
3. **Width/height value semantics** (proportion vs pixel threshold).
4. **Workspace name requirement** (require for MVP).
5. **`focus_after_load` path syntax**.

### 6.3 Resolve Before M3

1. **Column construction algorithm** — needs a detailed design document with failure modes and fallback behavior.
2. **Operation ordering guarantees** — does the planner guarantee a canonical ordering for deterministic plans?
3. **Replan strategy** — how many replans does the reconciler attempt before declaring partial failure?

### 6.4 General Recommendations

1. **Start with the simplest possible profile.** The M5 success scenario (one workspace, two columns, three windows) is the right target. Don't implement multi-workspace or multi-output until single-workspace works reliably.

2. **Build the fake IPC server early.** This is the highest-leverage test infrastructure. It should be the first thing built after the package scaffold.

3. **Record real Niri IPC sessions.** Before writing the IPC client, capture real `niri msg --json windows`, `niri msg --json workspaces`, and event stream sessions as fixture files. These will ground the models in reality.

4. **Don't over-engineer the matcher in M2.** Start with exact `app_id` + `title_regex` matching only. Add PID tracking and score-based ranking after the basic flow works end-to-end.

5. **Ship `plan` before `load`.** The plan command is safe, useful for debugging, and validates the planner without risking side effects. Users should be able to `nirip plan profile.yaml` and review the output before ever running `load`.

6. **Add `--dry-run` to `load` as an alias for `plan`.** This is a common UX pattern that builds user confidence.

---

## 7. Missing Items for Implementation Readiness

| Item | Status | Priority |
|---|---|---|
| CLI framework choice | Not decided | M0-blocking |
| Async architecture | Implied but unspecified | M0-blocking |
| Full dependency list | Incomplete | M0-blocking |
| Error taxonomy | Mentioned but undefined | M1-blocking |
| Launch mode default | Open question | M1-blocking |
| Width/height semantics | Ambiguous | M1-blocking |
| Column construction design | Underspecified | M3-blocking |
| Output alias resolution | Vague | Phase 2 (cut from MVP) |
| Plugin API | Premature | Phase 2 (defer entirely) |
| Performance targets | Missing | Nice-to-have |
| Concurrency/lockfile strategy | Open question | Phase 2 |
| `.desktop` file inference for freeze | Open question | Phase 2 |

---

## 8. Conclusion

This is a well-conceived project with a clear niche, honest scope, and a realistic execution plan. The concept document demonstrates strong understanding of Niri's capabilities and limitations. The implementation plan is appropriately phased.

The primary work before implementation begins is resolving the M0-blocking decisions (CLI framework, async strategy, dependencies) and accepting that column construction will require iterative design during M3–M4 rather than a perfect upfront algorithm.

The project should proceed to implementation.
