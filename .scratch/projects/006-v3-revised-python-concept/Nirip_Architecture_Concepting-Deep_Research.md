# Nirip architecture for Niri sessions

## Recommendation

Nirip should be **a session reconciler built on top of `niri-state` and `niri-pypc`, not a third parallel implementation of protocol parsing or state reduction**. The old concept note is directionally right about the product: declarative, event-driven, reconciliation-first, YAML-friendly, with capture as a scaffold rather than a promise of perfect replay. tmuxp is a useful analogy because it manages sessions from structured config files, but Nirip should stop borrowing at the metaphor layer and lean into the realities of Niri’s asynchronous, window-driven world. fileciteturn2file4 fileciteturn2file2 citeturn0search2turn0search13

The strongest architectural conclusion from reviewing the two dependency libraries is that they already divide responsibilities almost exactly how Nirip needs them divided. `niri-pypc` already owns protocol generation, socket transport, per-request command dispatch, persistent event streaming, error taxonomy, and lifecycle state handling; it is pinned to generated models for `niri-ipc 25.11`, with provenance metadata and schema hashes tracked in generated metadata. `niri-state` already owns live event-derived state, snapshot publication, health transitions, resync, selectors, and waiting on state changes. That means Nirip should start **above** those layers, at spec normalization, matching, diffing, plan compilation, apply orchestration, capture, and diagnostics. citeturn2view0turn15view0turn13view0turn13view1turn18view1turn3view0turn25view0turn25view3

My highest-confidence recommendation is therefore:

- `niri-pypc` remains the **wire/protocol/action** dependency.
- `niri-state` remains the **source-of-truth live state** dependency.
- Nirip becomes the **desired-state engine** that transforms `SessionSpec + Snapshot` into `Diff -> Plan -> ApplyResult`. fileciteturn2file4 citeturn2view0turn3view0

## Review of the current dependencies

`niri-pypc` is already a very clean lower-level foundation. Its README documents a package layout that cleanly separates config, errors, API clients, transport, runtime lifecycle, and generated protocol types; the configuration model is frozen Pydantic with explicit timeouts, frame size, queue capacity, and a `BackpressureMode`; the command client opens a fresh Unix connection per request and validates replies; the event stream is a persistent connection with a bounded queue, bootstrap handshake, background reader, and explicit backpressure behavior; and the bundle object composes both sides while cleaning up correctly if stream startup fails. It also uses a protocol-model layer based on frozen Pydantic models, externally tagged enum decoding, and an `UnknownEvent` sentinel for forward compatibility. That is exactly the kind of narrow, disciplined IPC layer Nirip should depend on rather than re-wrap wholesale. citeturn2view0turn6view0turn13view0turn13view1turn13view2turn14view0turn14view2turn18view1turn13view4turn13view5turn14view4turn15view0turn18view3turn18view4turn20view0

The generated action surface in `niri-pypc` is also important for scoping Nirip correctly. The request layer clearly exposes `ActionRequest` and `EventStreamRequest`, and the generated action types include `FocusWorkspace`, `MoveWindowToWorkspace`, `MoveWorkspaceToMonitor`, `SetWorkspaceName`, `Spawn`, `SpawnSh`, `ToggleWindowFloating`, and `FullscreenWindow`. In other words, the action surface strongly supports **workspace-oriented restoring and verified window placement**, but it does not by itself imply that Nirip should promise exact replay of every GUI geometry detail. That aligns with the old concept note’s suggestion to keep exact layout replay out of v1. citeturn16view0turn16view1turn17view0turn17view1turn17view2turn17view3turn17view4turn17view5turn17view6 fileciteturn2file2

`niri-state` is even more directly aligned with Nirip’s needs. Its public README and package layout show a focused state engine with `NiriState.open`, snapshot publication, first-snapshot semantics on `subscribe`, health transitions, unknown-event policies, and automatic resync options. Its config model nests a `NiriConfig`, so the low-level and high-level libraries already compose naturally. Its `Snapshot` is a frozen Pydantic model over outputs, workspaces, windows, focus, health, and diagnostics. Its central `NiriState` class owns connection lifecycle, mutation processing from the event stream, stale/failure transitions, refresh, and publication of state changes. This is already the right abstraction for Nirip to observe, wait on, and reason over. citeturn3view0turn22view2turn25view0turn25view1turn25view2turn25view3turn25view4turn25view5turn25view6turn25view7

The most important design implication is that Nirip should **not** revive the old concept note’s idea of owning its own parallel `state/` package with reducers and protocol mirroring. Before the dependency split, that made sense. After the split, duplicating it would make the codebase less elegant, not more. The clean design is to let `niri-state` continue to answer, “What is true right now?” and let Nirip answer, “Given what should be true, what should I do next?” fileciteturn2file4 fileciteturn2file1 citeturn22view0turn3view0

## Proposed package architecture

The cleanest Nirip architecture is a five-stage pipeline:

**spec loading -> normalization -> resolution/matching -> plan compilation -> execution against live state**

Internally, Nirip should treat `niri_state.Snapshot` as canonical live truth and maintain only a small amount of additional ephemeral runtime bookkeeping: previous matches, pending spawns, step progress, and ambiguity records. That preserves a single source of truth and keeps the codebase conceptually flat. fileciteturn2file3 citeturn25view2turn25view3

A repository layout that fits the current dependency split better than the original note would look like this:

```text
nirip/
  __init__.py
  config.py
  errors.py

  facade/
    async_client.py
    sync_client.py

  spec/
    models.py
    validators.py
    loader.py
    dump.py

  model/
    diff.py
    plan.py
    apply.py
    capture.py
    doctor.py

  resolve/
    workspace_refs.py
    matching.py
    ambiguity.py
    normalization.py

  planning/
    compiler.py
    ordering.py
    policies.py

  execution/
    executor.py
    steps.py
    operations.py
    predicates.py
    runtime.py

  capture/
    capture.py
    inference.py

  observe/
    live.py
    selectors.py
    wait.py

  cli/
    main.py
    apply.py
    diff.py
    inspect.py
    capture.py
    doctor.py
    watch.py
```

Two deliberate departures from the old concept note are worth making. First, I would not create a `protocol/` package in Nirip at all, because `niri-pypc` already owns the pinned generated schema and request/event/action types. Second, I would not create a second “state store” in Nirip, because `niri-state` already exists precisely to provide the event-derived state mirror the concept note was asking for. fileciteturn2file1 fileciteturn2file4 citeturn2view0turn22view0

I would also make the **async API the core API**, with a thin sync convenience facade layered over it. The concept note suggested sync public API and async internals, which is reasonable for CLI ergonomics, but forcing a sync-first core on top of intrinsically async dependencies usually makes embedding harder and error handling less elegant. The clean version is: async first for correctness and composition, sync wrapper for callers that just want `nirip apply session.yaml` semantics. fileciteturn2file4 citeturn25view3turn13view1

A minimal public surface should stay small:

```python
class AsyncNirip:
    @classmethod
    async def open(cls, config: NiripConfig | None = None) -> "AsyncNirip": ...
    async def inspect(self) -> LiveDesktop: ...
    async def diff(self, spec: SessionSpec) -> SessionDiff: ...
    async def plan(self, spec: SessionSpec) -> ExecutionPlan: ...
    async def apply(self, spec: SessionSpec) -> ApplyResult: ...
    async def capture(self, *, name: str | None = None) -> CapturedSession: ...
```

The sync facade should be a wrapper, not a separate engine.

## Pydantic-first domain model

Pydantic v2 should be used aggressively, but tactically. The best use is on **all user-authored, user-observed, and user-reported models**: spec models, normalized intent models, diffs, plans, results, capture output, doctor findings, and runtime explanations. The official Pydantic v2 docs explicitly support computed fields for exposing derived values during serialization, `TypeAdapter` for validation and serialization of arbitrary types outside a `BaseModel`, and rich field constraints/metadata via `Field`. citeturn0search4turn0search1turn0search12turn0search7

I would model the spec around four primary concepts:

```python
class SessionSpec(BaseModel):
    name: str
    defaults: SessionDefaults = Field(default_factory=SessionDefaults)
    workspaces: tuple[WorkspaceSpec, ...]
    apps: tuple[AppSpec, ...] = ()

class WorkspaceSpec(BaseModel):
    name: str
    output: str | None = None
    focus_on_start: bool = False

class AppSpec(BaseModel):
    key: str
    spawn: SpawnSpec | None = None
    match: MatchSpec
    target: TargetSpec = Field(default_factory=TargetSpec)
    policy: AppPolicy = Field(default_factory=AppPolicy)
    depends_on: tuple[str, ...] = ()

class MatchSpec(BaseModel):
    app_id: str | None = None
    title: str | None = None
    title_regex: str | None = None
    pid: int | None = None
    workspace: str | None = None
    output: str | None = None
```

The critical validator is not “is every field typed?” but “is this spec **safe to reconcile**?” For example, `MatchSpec` should reject specs with no matcher at all, should strongly warn or fail on title-regex-only matching unless the app is marked optional, and should surface when multiple `AppSpec`s are likely to compete for the same window identity. That recommendation follows directly from the concept note’s insistence that matching must be explainable and should strongly prefer stable identifiers such as `app_id`. fileciteturn2file2 fileciteturn2file3

For Nirip’s internal models, I would split them into three layers instead of one giant “plan step” universe:

- **normalized intent models**, which are the spec after defaults, workspace inheritance, and reference normalization;
- **resolution models**, which describe which live entities currently match, are missing, drifted, or ambiguous;
- **execution models**, which are the imperative steps compiled from that resolution.

That separation makes the code much easier to test and makes `diff` and `plan` natural first-class features rather than side effects of `apply`. It also keeps `capture` clean, because capture can produce a `SessionSpec` scaffold without depending on the executor at all. fileciteturn2file3 fileciteturn2file4

For derived values that should be visible in dumps and logs, prefer `@computed_field` rather than ordinary properties. Good examples inside Nirip would be `MatchDecision.is_ambiguous`, `ApplyResult.failed_steps`, `ExecutionPlan.requires_spawn`, `SessionDiff.has_drift`, or `CapturedAppSpec.suggested_key`. Use `TypeAdapter` in the YAML loading layer to validate top-level unions and wrapped collections without inventing unnecessary model shells. citeturn0search4turn0search1turn0search12

## Planning, matching, and execution

The most important concept for Nirip is to distinguish **resolution** from **execution**.

Resolution answers questions like:

- Does a desired app already match a live window?
- Is that match exact, partial, or ambiguous?
- Is the window already on the correct workspace?
- Does the workspace already exist on the correct output?
- Is there any action required at all?

Execution should not rediscover those answers ad hoc. It should operate on a compiled plan derived from a stable resolution model. This is the cleanest way to keep `diff`, `plan`, `apply`, and `doctor` coherent. fileciteturn2file3 fileciteturn2file4

The matching engine should be **deterministic, explainable, and bias toward false negatives over false positives**. The old concept note was correct to prioritize exact identity and stable identifiers first. I would formalize the scoring order as:

1. explicit previously bound window id;
2. verified pid linkage from a spawn launched by Nirip;
3. exact `app_id`;
4. exact title;
5. title regex;
6. workspace/output hint agreement;
7. recency relative to the spawn timestamp;
8. tie-break ordering.

The output should never just be “matched window 42.” It should be something like `MatchDecision(best=42, candidates=(...), confidence=..., rationale=(...))`, so both CLI output and debugging are explainable. That is where real usability will come from. fileciteturn2file2 fileciteturn2file3

The executor should be a **state-driven step runner** over `niri-state`, not a sequence of `await sleep(...)`. `niri-state` already gives Nirip the right primitives: a live snapshot, subscription to publications, health modeling, stale/desync detection, refresh/resync behavior, and wait-style observation patterns over snapshots. So each step in Nirip should be defined as:

- an optional request to issue through `niri-pypc`;
- a predicate over `Snapshot` that says the step is complete;
- an optional failure predicate;
- a timeout and ambiguity policy;
- structured recording of what happened. fileciteturn2file4 citeturn3view0turn25view3turn25view4turn25view5turn25view6turn25view7

A v1 step vocabulary should stay intentionally small:

- ensure workspace naming or resolution;
- ensure workspace output placement;
- focus workspace if needed;
- spawn process;
- wait for match;
- move matched window to workspace;
- set floating/fullscreen state when requested;
- focus final window or workspace;
- verify convergence.

That step set is directly supported by the generated action surface in `niri-pypc`, and it matches the concept note’s emphasis on workspace-oriented session restoration rather than pixel-perfect replay. citeturn17view0turn17view1turn17view2turn17view3turn17view4turn17view5turn17view6 fileciteturn2file2

One important modeling improvement over the old concept note is this: **output affinity should be a workspace concern first, not a per-window concern first**. The reviewed action surface clearly exposes `MoveWorkspaceToMonitor(output=...)`, while the strongest named-output operation is workspace-centric. So a session spec should treat `workspace.output` as a declarative placement constraint and allow `app.target.output` only as a shorthand that is normalized into the workspace target during spec normalization. That will keep execution semantics much clearer. citeturn17view3turn17view1

Finally, `apply` should ordinarily return an `ApplyResult`, not raise, exactly as the concept note suggested. Reserve exceptions for programmer misuse, impossible internal states, or dependency failures before an apply attempt can even be evaluated. Operational failures like ambiguity, timeout, or an app not appearing should be represented as structured step failures with enough evidence to make the report actually useful. fileciteturn2file2

## Dependency refinements that would make Nirip better

The two dependency libraries are already well aligned. I do not think either one needs a conceptual rewrite. I do think each would benefit from a few targeted additions that would make Nirip both smaller and cleaner.

For `niri-pypc`, the biggest improvement would be a **small, intentionally hand-written action helper layer** on top of the generated types. Right now the generated action classes are excellent as a source of truth, but Nirip will otherwise end up importing a large number of generated symbols directly. A helper module with functions like `spawn_action(...)`, `focus_workspace_action(...)`, `move_window_to_workspace_action(...)`, `set_workspace_name_action(...)`, and `move_workspace_to_output_action(...)` would keep Nirip’s executor readable while preserving the generated protocol boundary underneath. The request and action models are already there; this is purely an ergonomics layer. citeturn16view0turn17view0turn17view1turn17view2turn17view3turn17view4

I would also add a public compatibility surface to `niri-pypc`, because the metadata already records upstream crate/version and schema hashes. Nirip’s `doctor` command should be able to report the effective protocol pin and whether the running environment appears compatible without spelunking into generated internals. That capability is already latent in the metadata file; it just needs a friendlier public home. citeturn15view0turn2view0

For `niri-state`, the biggest improvement would be **matching-oriented selectors and richer publication metadata**. Nirip will repeatedly need queries like “windows with an `app_id`”, “windows whose title matches regex”, “windows on workspace X”, and “newest candidate windows since this step began.” Today, a lot of that is possible by reading the snapshot directly, but Nirip would be simpler if `niri-state` exposed a few generic, dependency-neutral selector helpers for common lookup patterns. That would keep Nirip’s matcher focused on policy rather than raw collection plumbing. The existing public positioning of `niri-state` as “state modeling and selector helpers” already points in exactly that direction. citeturn3view0turn25view2

The second refinement I would make in `niri-state` is to augment `PublishedState` or `ChangeSet` with **more granular changed-entity metadata**. Today the state engine clearly tracks changed domains and publishes snapshots, which is very good for general consumers. Nirip, though, would benefit from optionally knowing which window ids or workspace ids changed in the most recent publication, because that makes explainable matching and efficient step waiting much easier. This should be optional and additive, not a redesign. citeturn3view0turn25view3turn25view5

A smaller but still valuable refinement is to add a few first-class waiter helpers to `niri-state`, such as “wait until a window matching predicate exists” and “wait until focused workspace satisfies predicate.” The current waiter direction is already sound, but Nirip will otherwise end up re-implementing a thin convenience layer around state predicates. Better to let the state library continue to own that pattern. citeturn3view0turn25view7

## Delivery path and limitations

If the goal is the cleanest possible codebase, I would deliver Nirip in this order.

**First**, build the spec, normalization, resolution, and diff layers before the executor. That will force the domain language to become crisp and testable. It will also let `nirip diff`, `nirip doctor`, and `nirip capture` become useful before `apply` is fully mature. This sequencing follows the concept note’s strongest idea: planner/executor separation. fileciteturn2file3 fileciteturn2file4

**Second**, keep the first execution engine intentionally conservative. Reconcile only what can be observed and verified cleanly through existing action support: workspace resolution, output placement at the workspace level, spawn, match, move-to-workspace, floating/fullscreen, and focus. Do not chase exact layout replay in v1. That will produce a smaller, more elegant system with much stronger correctness properties. fileciteturn2file2 citeturn17view0turn17view1turn17view2turn17view3turn17view5turn17view6

**Third**, make capture intentionally humble. The concept note is right: capture should produce a scaffold. Nirip should infer `app_id`, title, regex suggestion, workspace, and output hint, but always present the result as a starting template designed for human cleanup. That product decision will save a lot of downstream complexity and user confusion. fileciteturn2file2 fileciteturn2file3

There are two limitations to keep in mind. The first is that the recommendations above are based on a review of the attached exports and the corresponding public repository files, but I have not exhaustively enumerated every generated action variant or every test in the two repositories here. The second is that some fine-grained refactors I would make for Nirip convenience, especially around selectors and publication metadata, are additive design recommendations rather than defects in the current libraries. Even with those caveats, the main conclusion is firm: **the dependency split you already made was the right one, and the best Nirip architecture is the one that fully commits to it.** citeturn2view0turn3view0turn22view0turn22view2