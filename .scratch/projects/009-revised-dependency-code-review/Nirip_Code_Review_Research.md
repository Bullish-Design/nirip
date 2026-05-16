# Nirip deep architecture review

## Executive assessment

The strongest part of your stack is **niri-pypc**. It already has a tight public surface, a clear split between transport, protocol, lifecycle, and ergonomic action builders, and it is using Pydantic in ways that match the framework’s intended strengths: `RootModel` for custom root types, `model_validator` for pre-validation decode, `model_serializer` for custom outbound wire formatting, and `model_validate_json()` for JSON-heavy paths. That is a very solid foundation for a session manager. `niri-state` is also structurally sound: it composes `niri-pypc` rather than reimplementing it, builds immutable snapshots, reconciles/rechecks invariants, and exposes wait/subscribe semantics that are exactly the sort of primitives Nirip should be built on. By contrast, **nirip is currently a strong planner prototype, not yet a functioning tmuxp-for-Niri runtime**. The spec → normalize → resolve → plan shape is promising, but the live integration layer is missing, so the current public API and CLI cannot actually operate against Niri as shipped. [`src/niri_pypc/types/base.py:41-103`, `src/niri_state/api/state.py:54-425`, `src/nirip/facade/async_nirip.py:17-78`, `src/nirip/cli/commands.py:12-39`] Pydantic’s docs explicitly support the architectural patterns already working well in `niri-pypc` and also point toward several improvements that would make Nirip much cleaner, especially centralized `ConfigDict` usage, discriminated unions, reusable `TypeAdapter`s, and stricter handling of extras and aliases. citeturn3view1turn3view5turn3view6turn10view1turn10view2turn11view0

My high-confidence conclusion is this: **do not treat Nirip as an application wrapper around “snapshot-like” objects anymore**. Promote it into a real orchestration library with explicit runtime ports for **state**, **commands**, and **process spawning**, backed concretely by `niri-state`, `niri-pypc`, and `asyncio.subprocess`. The code you already have becomes much more coherent once those boundaries are made explicit. [`src/nirip/resolve/resolver.py:24-37`, `src/nirip/execution/executor.py:13-30`, `src/niri_state/api/waiters.py:47-113`, `src/niri_pypc/actions.py:547-548`, `src/niri_pypc/actions.py:653-655`, `src/niri_pypc/actions.py:700-746`, `src/niri_pypc/actions.py:814-826`, `src/niri_pypc/actions.py:1045-1054`]

## Dependency foundations

### niri-pypc

`niri-pypc` is already very close to the kind of dependency Nirip wants. Its protocol layer is generated and pinned to upstream `niri-ipc 25.11`, with provenance tracked in generated metadata, which is exactly the right posture for a compositor IPC library: correctness first, ergonomics second. The public package then wraps that generated surface with a small number of handwritten abstractions: `NiriClient` for request/response, `NiriEventStream` for persistent events, `NiriConnectionBundle` for both, `NiriConfig`, an explicit error taxonomy, and the `actions` builder module. [`README.md`, `src/niri_pypc/__init__.py:1-44`, `src/niri_pypc/types/generated/_metadata.py:1-16`, `src/niri_pypc/api/client.py:48-135`, `src/niri_pypc/api/event_stream.py:45-299`, `src/niri_pypc/actions.py:1-175`] That layering is clean.

The most important architectural win is the way externally tagged enums are modeled. `ExternallyTaggedEnum` subclasses `RootModel`, decodes in a `model_validator(mode="before")`, and serializes with `model_serializer(mode="plain")`, while the actual encode/decode logic is centralized in `types/codec.py`. This is exactly the kind of problem `RootModel`, validators, and serializers are meant to solve in Pydantic v2. [`src/niri_pypc/types/base.py:41-103`, `src/niri_pypc/types/codec.py:19-141`] Pydantic documents `RootModel` as the way to model a custom root type, and `model_serializer` as the mechanism for whole-model custom serialization. citeturn3view1turn3view5

`NiriClient` is also sensibly implemented. It resolves the socket path, opens a fresh Unix connection per request, emits newline-delimited JSON, reads a bounded reply, and validates replies with `Reply.model_validate_json(raw)` before unwrapping them. That choice lines up well with Pydantic’s performance guidance to prefer `model_validate_json()` over `model_validate(json.loads(...))` for JSON payloads. [`src/niri_pypc/api/client.py:95-122`] citeturn10view2

The `actions.py` module is especially important for Nirip. It already gives you typed builders for most of the plan primitives Nirip needs: focusing windows and workspaces, moving windows to workspaces, toggling floating/fullscreen/maximized behavior, resizing windows, and moving workspaces between monitors. [`src/niri_pypc/actions.py:547-548`, `src/niri_pypc/actions.py:653-655`, `src/niri_pypc/actions.py:700-746`, `src/niri_pypc/actions.py:814-826`, `src/niri_pypc/actions.py:1005-1054`] That means Nirip does **not** need to invent its own execution request schema in parallel; it can compile directly to `ActionRequest`s or to a small Nirip command union that is trivially lowered into these builders.

I would make only small dependency-level changes here. First, keep `niri-pypc` as the canonical source for compositor command primitives; do not duplicate that abstraction in Nirip. Second, if you want to make Nirip’s executor even cleaner, a small `NiriClient.request_action(...)` convenience could reduce noise, but it is optional because the existing builder functions already return `ActionRequest`. Third, preserve the current high-discipline approach to generated types; nothing in the handwritten code review suggested a need for major restructuring here. [`src/niri_pypc/api/client.py:95-122`, `src/niri_pypc/actions.py:1-175`]

### niri-state

`niri-state` is a strong middle layer and, conceptually, the right live-state dependency for Nirip. It composes `NiriConfig` inside `NiriStateConfig`, re-exports a curated bundle of `niri-pypc` protocol types through `adapters/protocol.py`, and builds a state engine around bootstrap, reduction, reconciliation, invariants, health, diagnostics, broadcasting, and waiters. [`src/niri_state/api/config.py:37-63`, `src/niri_state/adapters/protocol.py:1-96`, `src/niri_state/core/bootstrap.py:172-228`, `src/niri_state/core/reducers.py:56-350`, `src/niri_state/core/reconcile.py:11-74`, `src/niri_state/core/invariants.py:8-109`, `src/niri_state/api/waiters.py:47-113`] That is exactly the kind of dependency Nirip should lean on instead of bypassing.

The `Snapshot` model is particularly well aligned with your goals. It freezes top-level mappings into `MappingProxyType`, computes useful derived indexes like `focused_output_name`, `workspaces_by_output`, `windows_by_workspace`, `active_workspace_by_output`, and `keyboard_current_name`, and is produced from an internal mutable `EngineState` only at publish boundaries. [`src/niri_state/api/snapshot.py:14-92`, `src/niri_state/core/engine_state.py:12-53`] In practice, this gives Nirip a stable, immutable, read-optimized view of the compositor state.

The wait layer is also exactly the kind of thing a session manager wants. `wait_until()` and `wait_for_selector()` already encode the right control flow for “wait until workspace exists”, “wait until this window lands in the correct workspace”, or “wait until health is live again”. [`src/niri_state/api/waiters.py:47-113`] That means Nirip should not write bespoke polling code; it should call into this layer.

The largest `niri-state` issues are not structural, but productization details. The most obvious one is **version drift inside the package itself**: `pyproject.toml` declares `0.2.1`, while `src/niri_state/_version.py` still says `0.2.0`. [`pyproject.toml`, `src/niri_state/_version.py:1-2`] That is easy to fix, but it is important because `niri-pypc` already handles runtime versioning more robustly through `importlib.metadata.version(...)` with a local fallback. [`src/niri_pypc/__init__.py:3-8`] I would standardize the version strategy across the two dependencies.

The other improvement I would make specifically for Nirip is **selector export ergonomics**. Right now, the selectors and waiters exist, but they are not exposed prominently from the top-level package. [`src/niri_state/__init__.py:1-55`, `src/niri_state/api/selectors/__init__.py:1-19`, `src/niri_state/api/waiters.py:1-113`] For Nirip, I would add first-class selectors such as `workspace_by_name`, `windows_by_app_id`, and `windows_by_pid`, or else a lightweight indexed view object derived from `Snapshot`. That would let Nirip stop re-scanning lists and reduce the amount of ad hoc lookup logic in the resolver and executor.

## Dependency alignment with Nirip

The core alignment fact is simple: **your dependencies are already aligned to each other, but Nirip is not aligned to them yet**.

`niri-state` is explicitly built on `niri-pypc`. It consumes `NiriConnectionBundle`, bootstrap queries, event value types, and upstream schema version metadata. [`src/niri_state/adapters/protocol.py:1-96`, `src/niri_state/core/bootstrap.py:6-35`, `src/niri_state/core/bootstrap.py:87-142`] Their abstractions fit together well: `niri-pypc` gives typed transport and commands; `niri-state` gives typed, immutable, continuously updated state.

By contrast, Nirip depends on both packages in `pyproject.toml`, but in the actual source tree it mostly ignores them. Instead of depending on `niri_state.Snapshot` and `niri_state.NiriState`, it defines its own weak `SnapshotLike` and `WorkspaceLike` protocols and expects callers to inject arbitrary snapshot-shaped objects. [`pyproject.toml`, `src/nirip/resolve/resolver.py:18-37`, `src/nirip/capture/capturer.py:28-57`, `src/nirip/execution/predicates.py:10-20`] Instead of lowering to `niri_pypc.actions.*` or `ActionRequest`, it invents a `StepAction` wrapper and an `ActionClient` protocol unrelated to the existing request surface. [`src/nirip/execution/actions.py:11-30`, `src/nirip/execution/executor.py:13-23`] This is the main architectural misalignment.

The cleanest fix is to give Nirip three explicit runtime ports:

- a **state port**, implemented by `niri-state`, responsible for snapshots, subscriptions, waiters, and selectors;
- a **command port**, implemented by `niri-pypc`, responsible for compositor actions;
- a **process port**, implemented by `asyncio.subprocess`, responsible for spawning applications from `SpawnSpec`.

Once you do that, most of Nirip’s current placeholder abstractions collapse naturally into concrete, testable adapters. The high-level library can still remain pure and dependency-injected, but the default adapters should be first-class and live by default.

For the dependencies themselves, I would make two targeted additions. In `niri-state`, add stronger lookup/selectors for Nirip-facing queries and re-export the waiter utilities more prominently. In `niri-pypc`, I would not do a large refactor, but I would treat its action builders as the canonical execution substrate for Nirip and resist building a competing command schema in Nirip.

## Nirip code review

### The main architectural blockers

The single biggest problem in Nirip is that its **default public API is not live**.

`AsyncNirip.open()` returns an instance with no bound snapshot and no connected state engine. [`src/nirip/facade/async_nirip.py:20-27`] `plan()`, `diff()`, `apply()`, `capture()`, and `inspect()` all call `_require_snapshot()`, which raises immediately unless an external caller has manually injected a snapshot. [`src/nirip/facade/async_nirip.py:34-42`, `src/nirip/facade/async_nirip.py:44-56`, `src/nirip/facade/async_nirip.py:69-72`] `SyncNirip` just wraps that same async facade, so the synchronous public surface has the same limitation. [`src/nirip/facade/sync_nirip.py:24-31`, `src/nirip/facade/sync_nirip.py:38-56`] The convenience API in `nirip.__init__` then exposes `apply_session(spec)` using `SyncNirip()` with no snapshot binding. [`src/nirip/__init__.py:16-19`] The CLI command handlers do the same thing. [`src/nirip/cli/commands.py:12-39`] As written, the out-of-the-box library/CLI path cannot fulfill the promise of a tmuxp-like session manager.

The second biggest problem is that **`apply()` does not actually apply anything**. `AsyncNirip` constructs `PlanExecutor(client=None)` in its initializer. [`src/nirip/facade/async_nirip.py:20-24`] Inside the executor, if a step is not already satisfied and `client` is `None`, the code does not fail; it simply records the step as `COMPLETED`. [`src/nirip/execution/executor.py:49-82`] That means the default executor is effectively a dry-run engine that reports success. This is fine for testing a planner, but it is not acceptable for a library whose central verb is “apply”.

The third major blocker is that **the plan is not actually executable**. `compile_plan()` emits `SPAWN_WINDOW` and `WAIT_FOR_WINDOW` steps, but it does not attach the actual `SpawnSpec`, command, environment, working directory, shell flag, match rule, or startup timeout to those steps. [`src/nirip/planning/compiler.py:50-70`, `src/nirip/spec/models.py:39-45`, `src/nirip/spec/models.py:65-75`, `src/nirip/resolve/models.py:11-21`] By the time execution begins, the data required to spawn the process or wait for the right window has been lost. That is the clearest sign that the current `PlanStep` shape is under-modeled.

### The modeling gaps

Nirip’s domain partitioning is conceptually good. `spec`, `resolve`, `planning`, `execution`, and `capture` are the right phases. [`src/nirip/spec/models.py:1-102`, `src/nirip/resolve/normalizer.py:9-51`, `src/nirip/resolve/resolver.py:36-144`, `src/nirip/planning/compiler.py:9-165`, `src/nirip/execution/executor.py:17-82`, `src/nirip/capture/capturer.py:28-57`] But the internal models are still too permissive and too flat.

The most important modeling issue is that **many user-facing models silently accept unknown keys**. In Pydantic, `extra` defaults to `'ignore'` unless configured otherwise. citeturn11view0turn11view2 In Nirip, only `MatchRule` sets `model_config`, and it uses that only for alias population. [`src/nirip/spec/models.py:10-36`] `SpawnSpec`, `PlacementSpec`, `AppSpec`, `WorkspaceSpec`, `SessionOptions`, `SessionSpec`, `Normalized*`, `PlanStep`, `Plan`, `SessionDiff`, `StepResult`, and `ApplyResult` all inherit the default behavior. [`src/nirip/spec/models.py:39-102`, `src/nirip/resolve/models.py:11-148`, `src/nirip/planning/models.py:28-85`, `src/nirip/execution/models.py:18-49`] That means typos in YAML or internal update dictionaries can be ignored instead of rejected. For a declarative session format, that is a serious correctness bug.

The next modeling issue is that `PlanStep` is a classic “string enum plus optional fields plus freeform metadata” design. [`src/nirip/planning/models.py:12-38`] It can represent invalid states very easily: a step may need `output` in metadata, or a `window_id`, or a timeout, or a command, but nothing in the type enforces that. This is exactly where a discriminated union of concrete step models would be cleaner. Pydantic supports tagged/discriminated unions and documents them as the preferred shape over generic unions in performance-sensitive cases as well. citeturn10view3

You are also carrying domain concepts that are validated or normalized but never actually executed. `depends_on` exists in `AppSpec`, is validated for existence and cycles, and is preserved through normalization, but it is never used in planning. [`src/nirip/spec/models.py:65-75`, `src/nirip/spec/validators.py:22-105`, `src/nirip/resolve/models.py:11-21`, `src/nirip/resolve/normalizer.py:17-30`, `src/nirip/planning/compiler.py:9-165`] Likewise, `PlacementSpec.focus`, `WorkspaceSpec.focus`, `PlacementSpec.column_width`, `PlacementSpec.window_height`, and session options like `match_existing`, `launch_missing`, `move_unmatched`, and `mode` are defined but not meaningfully consumed by resolver, planner, or executor. [`src/nirip/spec/models.py:48-102`, `src/nirip/resolve/resolver.py:36-144`, `src/nirip/planning/compiler.py:9-165`, `src/nirip/execution/executor.py:23-82`] Right now, the declarative surface promises more than the engine actually does.

One subtle but important bug is in resolution semantics when a desired workspace does not exist. `resolve()` only records `WRONG_WORKSPACE` drift if the target workspace already exists and `live_ws is not None`. [`src/nirip/resolve/resolver.py:45-79`] So if a matching window exists elsewhere and the desired workspace is missing, Nirip can classify the app as matched instead of “needs move after workspace creation”. The planner will then create the workspace but may never move the window into it. [`src/nirip/planning/compiler.py:21-40`, `src/nirip/planning/compiler.py:42-128`] That is a real correctness gap, not just a missing feature.

Another important correctness issue is that matching is **independent per declared app**, with no one-to-one assignment across the session. `resolve()` calls `match_app()` for each app against the full live window list. [`src/nirip/resolve/resolver.py:39-55`] `match_app()` sorts matches and picks the best candidate for that single app, but it never reserves windows already claimed by another app. [`src/nirip/resolve/matcher.py:113-145`] So one real window can satisfy multiple declared roles. For a tmuxp-like tool, you usually want a matching phase that produces a globally consistent assignment, not a set of independent local maxima.

### The validation and UX issues

The spec validator has good instincts. It checks duplicate workspace names, duplicate app names within a workspace, dangling dependencies, cyclic dependencies, invalid regex, weak matchers, inter-app conflicts, and empty spawn commands. [`src/nirip/spec/validators.py:22-184`] That is good work.

What is missing is **issue propagation**. `_validate_spec()` raises only on errors and drops warnings entirely. [`src/nirip/spec/loader.py:14-20`] So users never see warnings like fragile `title_regex`-only matching. [`src/nirip/spec/validators.py:132-140`] In a session management tool, warnings are extremely valuable, especially when the library is trying to prevent flaky matching. I would return a structured “loaded spec + validation report” or at minimum surface warnings through `doctor()` and the CLI.

The capture path is intentionally conservative and, for a scaffold generator, that is fine. It derives app names from `app_id` or title, infers a conservative `MatchRule`, skips unnamed workspaces, and emits a note telling the user to add spawn commands manually. [`src/nirip/capture/inference.py:8-27`, `src/nirip/capture/capturer.py:28-57`] I would keep this simple.

The packaging/storytelling layer needs work too. `README.md` in the Nirip archive is empty, the project description in `pyproject.toml` is generic, and project URLs are commented out. [`README.md`, `pyproject.toml`] For a library that aims to be “cleanest, most elegant,” that is worth fixing early, because it forces you to articulate the contract of the runtime layer that is currently missing.

## Pydantic v2 strategy for the final architecture

The best Pydantic move for Nirip is **not** “use more decorators everywhere.” It is to use Pydantic more deliberately at the architectural seams.

Start by introducing a shared Nirip base model. Use `ConfigDict(extra='forbid', frozen=True)` for almost every spec, normalization, resolution, planning, and execution model, with explicit exceptions only where mutability is intentional. Pydantic’s configuration layer is designed for exactly this kind of centralized policy, and `extra='forbid'` directly addresses the current typo-swallowing problem. citeturn2view0turn11view0turn11view2

Next, replace `PlanStep` and possibly parts of `StepAction` with **discriminated unions**. A `SpawnWindowStep` should require a concrete spawn payload. A `WaitForWindowStep` should require a timeout and a matching rule or app key. A `MoveWindowToWorkspaceStep` should require a window reference and a workspace reference. A `MoveWorkspaceToOutputStep` should require an output. This eliminates invalid intermediate states and removes the need for freeform `metadata` dictionaries in core planning/execution logic. Pydantic’s tagged-union support is a good fit here. citeturn10view3

Then, use `TypeAdapter` in the few places where Nirip does bulk or ad hoc validation. Pydantic positions `TypeAdapter` as the right tool for validating arbitrary types, lists of models, and other non-`BaseModel` shapes, and recommends creating adapters once and reusing them instead of instantiating them repeatedly in hot paths. citeturn9view0turn10view1 This is useful for things like cached adapters for exported capture documents, resolved plan lists, or any future bulk validation of window candidates.

You should also keep leaning into `computed_field`, but only for actual derived values, not business logic. Nirip is already using it well for convenience summaries like counts and booleans in `ApplyResult`, `Plan`, `SessionDiff`, `CapturedSession`, `MatchDecision`, and `Resolution`. [`src/nirip/execution/models.py:28-49`, `src/nirip/planning/models.py:41-85`, `src/nirip/capture/capturer.py:11-25`, `src/nirip/resolve/models.py:52-148`] Pydantic exposes `computed_field` as a first-class field API; the current use is sensible. citeturn8view0

For validators, prefer a small number of strong model-level invariants and field-level transformations, not scattershot validation. Pydantic’s `model_validator(mode='after')` is appropriate for cross-field rules such as your `MatchRule` emptiness check and `PlacementSpec` mutual exclusion, and `field_validator` is appropriate where validation depends on one field or needs access to already-validated sibling data. citeturn3view6turn3view7 Nirip is already using `model_validator` in the right spirit in `spec/models.py`; the next step is consistency, not novelty. [`src/nirip/spec/models.py:23-36`, `src/nirip/spec/models.py:58-62`]

Finally, for the runtime boundary, consider using separate validation and serialization aliases where the external YAML shape differs from the internal Python attribute names. Pydantic v2 exposes `validation_alias`, `serialization_alias`, and config options like `validate_by_alias`, `validate_by_name`, and `serialize_by_alias`, which gives you a cleaner alternative to relying on generic alias behavior everywhere. citeturn2view0 That is especially relevant if you keep `any` as the YAML spelling and `any_of` as the Python spelling.

## Recommended direction

If you want the cleanest possible codebase, I would make the following architectural move before almost anything else:

**Make `AsyncNirip` own real runtime adapters by default.**

At construction time, it should either:
- open `NiriState` and a `NiriClient`/`NiriConnectionBundle`, or
- accept explicit injected ports implementing those interfaces.

Then:
- `diff()` and `plan()` should read from `state.snapshot`;
- `apply()` should compile executable steps and lower them directly into `niri-pypc` action builders plus subprocess spawn calls;
- step completion should be verified through `niri-state` waiters/selectors rather than ad hoc snapshot predicates;
- `capture()` should read from `state.snapshot`;
- `doctor()` should include `niri-state` health and compatibility data.

That is the shortest path from your current design to a genuinely elegant library because it removes the fake “snapshot-only” mode from the center of the API and turns it into a test seam instead.

In parallel, I would make a second major change: **rebuild the plan layer as typed executable intent, not human-readable descriptions with optional fields**. Once you do that, `compile_plan()` becomes more honest, `PlanExecutor` becomes simpler, and features like `depends_on`, spawn command propagation, timeout handling, and focus semantics stop being awkward special cases.

## Open questions and limitations

This review focused on the handwritten architecture and public contracts, not a line-by-line audit of every generated protocol class in `niri-pypc`. I reviewed the generated protocol layer primarily through its handwritten integration points and metadata rather than exhaustively tracing every generated variant. [`src/niri_pypc/types/generated/_metadata.py:1-16`, `src/niri_pypc/types/base.py:41-103`, `src/niri_pypc/types/codec.py:19-141`]

There is also one upstream-semantics question that Nirip will need to settle explicitly in its design docs: **what exactly “ensure workspace exists” means in Niri terms**. `niri-pypc` gives you workspace focus, naming, and movement primitives, but Nirip should state clearly how it materializes a missing workspace in practice and how that interacts with named workspaces and output placement. [`src/niri_pypc/actions.py:653-667`, `src/niri_pypc/actions.py:1005-1054`] Without that decision, planning and execution will keep drifting apart.