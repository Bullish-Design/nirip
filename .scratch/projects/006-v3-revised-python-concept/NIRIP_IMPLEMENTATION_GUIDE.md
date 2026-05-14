# Nirip Implementation Guide

A step-by-step guide for implementing the nirip library from the ground up, following the architecture defined in NIRIP_CONCEPT.md.

---

## Prerequisites

- Python >= 3.13, managed via `devenv`
- `niri-pypc` v0.3.1 and `niri-state` v0.2.0 (already in pyproject.toml)
- `pydantic` >= 2.12.5
- `pyyaml` for YAML parsing
- `pytest` >= 7.0 for testing
- Familiarity with `asyncio`, Pydantic v2, and the niri compositor

### Development commands

All commands run through devenv:

```bash
devenv shell -- python -m pytest tests/ -x -q
devenv shell -- ruff check src/nirip/
devenv shell -- ruff format src/nirip/
```

### Dependency API quick reference

**Constructing a niri-pypc action request:**
```python
from niri_pypc.types.generated.request import ActionRequest
from niri_pypc.types.generated.action import Action, SpawnAction, FocusWorkspaceAction
from niri_pypc.types.generated.models import (
    WorkspaceReferenceArg, NameWorkspaceReferenceArg,
    SizeChange, SetProportionSizeChange,
)

# Every action must be wrapped: ActionRequest(payload=Action(root=<specific_action>))
req = ActionRequest(payload=Action(root=SpawnAction(command=["kitty"])))

# Workspace references use externally-tagged enums:
ws_ref = WorkspaceReferenceArg(root=NameWorkspaceReferenceArg(payload="code"))
req = ActionRequest(payload=Action(root=FocusWorkspaceAction(reference=ws_ref)))

# Size changes:
change = SizeChange(root=SetProportionSizeChange(payload=0.6))
```

**Key niri-pypc action signatures:**
```python
SpawnAction(command: list[str])
SpawnShAction(command: str)
FocusWindowAction(id: int)
FocusWorkspaceAction(reference: WorkspaceReferenceArg)
MoveWindowToWorkspaceAction(window_id: int | None, focus: bool, reference: WorkspaceReferenceArg)
MoveWindowToFloatingAction(id: int | None = None)
MoveWindowToTilingAction(id: int | None = None)
MoveWorkspaceToMonitorAction(output: str, reference: WorkspaceReferenceArg | None = None)
FullscreenWindowAction(id: int | None = None)
MaximizeWindowToEdgesAction(id: int | None = None)
SetColumnWidthAction(change: SizeChange)
SetWindowHeightAction(change: SizeChange, id: int | None = None)
SetWorkspaceNameAction(name: str, workspace: WorkspaceReferenceArg | None = None)
```

**Key niri-pypc model fields:**
```python
# Window (from niri_pypc.types.generated.models)
Window.id: int
Window.app_id: str | None
Window.title: str | None
Window.pid: int | None
Window.workspace_id: int | None
Window.is_floating: bool
Window.is_focused: bool

# Workspace
Workspace.id: int
Workspace.idx: int
Workspace.name: str | None
Workspace.output: str | None
Workspace.is_active: bool
Workspace.is_focused: bool
```

**Key niri-state APIs:**
```python
from niri_state import NiriState, NiriStateConfig
from niri_state.api.snapshot import Snapshot
from niri_state.api.selectors import windows, workspaces, outputs, focus
from niri_state.api.waiters import wait_until, wait_for_selector, watch
from niri_state.api.errors import WaitTimeoutError

# NiriState lifecycle:
state = await NiriState.open(config)  # or use as async context manager
snapshot = state.snapshot              # current Snapshot (frozen Pydantic model)

# Snapshot fields:
snapshot.windows    # MappingProxyType[int, Window]  (window_id -> Window)
snapshot.workspaces # MappingProxyType[int, Workspace]  (workspace_id -> Workspace)
snapshot.outputs    # MappingProxyType[str, Output]  (output_name -> Output)

# Selectors:
windows.list_windows(snapshot) -> tuple[Window, ...]
windows.list_windows_on_workspace(snapshot, workspace_id) -> tuple[Window, ...]
workspaces.list_workspaces(snapshot) -> tuple[Workspace, ...]
workspaces.get_workspace(snapshot, workspace_id) -> Workspace | None
focus.get_focused_window(snapshot) -> Window | None

# Waiters (note: config is REQUIRED):
await wait_until(state, predicate, config=state_config, timeout=20.0)
```

---

## Phase 1: Spec + Matching

**Goal:** Parse session YAML, validate aggressively, normalize, and evaluate match rules against mock windows.

**Packages to create:** `spec/`, `resolve/normalizer.py`, `resolve/matcher.py`, `resolve/models.py`

### Step 1.1: Create project skeleton

Create all `__init__.py` files and the package structure.

**Files to create:**
```
src/nirip/__init__.py
src/nirip/config.py
src/nirip/errors.py
src/nirip/spec/__init__.py
src/nirip/spec/models.py
src/nirip/spec/loader.py
src/nirip/spec/validators.py
src/nirip/spec/defaults.py
src/nirip/resolve/__init__.py
src/nirip/resolve/normalizer.py
src/nirip/resolve/matcher.py
src/nirip/resolve/models.py
src/nirip/resolve/resolver.py
src/nirip/planning/__init__.py
src/nirip/planning/compiler.py
src/nirip/planning/ordering.py
src/nirip/planning/models.py
src/nirip/execution/__init__.py
src/nirip/execution/executor.py
src/nirip/execution/actions.py
src/nirip/execution/predicates.py
src/nirip/execution/runtime.py
src/nirip/execution/models.py
src/nirip/capture/__init__.py
src/nirip/capture/capturer.py
src/nirip/capture/inference.py
src/nirip/facade/__init__.py
src/nirip/facade/async_nirip.py
src/nirip/facade/sync_nirip.py
src/nirip/cli/__init__.py
src/nirip/cli/main.py
src/nirip/cli/commands.py
tests/__init__.py
tests/conftest.py
```

For now, only the Phase 1 files need real content. All other files should contain just a docstring placeholder like `"""Module docstring."""`.

**Test to validate:**
```bash
devenv shell -- python -c "import nirip; print('nirip package loads')"
```

The import must succeed without errors.

---

### Step 1.2: Implement error hierarchy

**File:** `src/nirip/errors.py`

```python
"""Nirip error hierarchy.

Nirip does not wrap niri-pypc or niri-state errors — those propagate directly.
These errors cover only session-level semantics.
"""


class NiripError(Exception):
    """Base for all nirip errors."""


class SpecError(NiripError):
    """Invalid session spec (parse error, validation failure)."""


class SpecValidationError(SpecError):
    """Spec validation failed (empty match rules, conflicts, etc.)."""


class MatchError(NiripError):
    """Window matching failure."""


class AmbiguousMatchError(MatchError):
    """Multiple windows match with similar confidence."""


class PlanningError(NiripError):
    """Plan generation failed (unresolvable conflicts)."""


class ExecutionError(NiripError):
    """Step execution failed."""


class StepTimeoutError(ExecutionError):
    """Window didn't appear within timeout."""


class CaptureError(NiripError):
    """Capture failed."""


class NiripConnectionError(NiripError):
    """Cannot connect to niri compositor."""
```

**Test:** `tests/test_errors.py`
```python
def test_error_hierarchy():
    """All errors inherit from NiripError."""
    from nirip.errors import (
        NiripError, SpecError, SpecValidationError, MatchError,
        AmbiguousMatchError, PlanningError, ExecutionError,
        StepTimeoutError, CaptureError, NiripConnectionError,
    )
    assert issubclass(SpecValidationError, SpecError)
    assert issubclass(SpecError, NiripError)
    assert issubclass(AmbiguousMatchError, MatchError)
    assert issubclass(StepTimeoutError, ExecutionError)
    # Verify they can be raised and caught
    try:
        raise SpecValidationError("test")
    except NiripError:
        pass
```

---

### Step 1.3: Implement NiripConfig

**File:** `src/nirip/config.py`

```python
"""Nirip configuration."""
from pathlib import Path
from pydantic import BaseModel


class NiripConfig(BaseModel, frozen=True):
    """Nirip-level configuration."""
    session_dir: Path = Path("~/.config/nirip/sessions")
    state_dir: Path = Path("~/.local/state/nirip")
    default_timeout_s: float = 20.0
    confirm_before_apply: bool = True
```

Note: we do NOT store `NiriStateConfig` here yet — that comes in Phase 4 when we wire up live connections. Keep it simple.

**Test:** `tests/test_config.py`
```python
from nirip.config import NiripConfig

def test_default_config():
    cfg = NiripConfig()
    assert cfg.default_timeout_s == 20.0
    assert cfg.confirm_before_apply is True

def test_config_is_frozen():
    cfg = NiripConfig()
    import pytest
    with pytest.raises(Exception):
        cfg.default_timeout_s = 99.0
```

---

### Step 1.4: Implement spec models

**File:** `src/nirip/spec/models.py`

This is the largest single step. Implement every model from NIRIP_CONCEPT.md section 4.1 exactly.

**Models to implement (in order):**
1. `MatchRule` — with `@model_validator(mode="after")` that rejects zero-criteria rules
2. `SpawnSpec`
3. `PlacementSpec` — with `fullscreen`, `maximized`, `floating`, `focus`, `column_width`, `window_height`
4. `AppSpec`
5. `WorkspaceSpec`
6. `SessionOptions`
7. `SessionSpec`

**Critical details:**

For `MatchRule.validate_not_empty`: The validator uses Python's built-in `any()`, but the field `self.any` shadows it. Use a local reference or rename the check:

```python
@model_validator(mode="after")
def validate_not_empty(self) -> "MatchRule":
    criteria = [
        self.app_id is not None,
        self.app_id_regex is not None,
        self.title is not None,
        self.title_regex is not None,
        self.pid is not None,
        self.any_of is not None,   # see naming note below
        self.not_rule is not None,
    ]
    if not builtins.any(criteria):
        raise ValueError("MatchRule must have at least one matching criterion.")
    return self
```

**Naming issue:** The field name `any` in the concept doc shadows Python's built-in `any()`. You have two options:
- Name the field `any_of` in Python but alias it to `any` for YAML with `Field(alias="any")`.
- Or use `import builtins` and call `builtins.any()` in the validator.

**Recommended approach:** Use `any_of` with `Field(alias="any")` and set `model_config = ConfigDict(populate_by_name=True)` on the model.

For `PlacementSpec`: add a `@model_validator(mode="after")` that rejects `floating=True` and `fullscreen=True` together.

For `column_width` / `window_height`: accept `float` (proportion 0.0-1.0) or `str` matching pattern `"px:NNN"`. Use `float | str | None` as the type.

**Tests:** `tests/test_spec_models.py`

Write tests for each model. The critical tests are:

```python
import pytest
from nirip.spec.models import MatchRule, SpawnSpec, PlacementSpec, AppSpec, WorkspaceSpec, SessionSpec, SessionOptions

class TestMatchRule:
    def test_valid_app_id(self):
        rule = MatchRule(app_id="firefox")
        assert rule.app_id == "firefox"

    def test_valid_app_id_regex(self):
        rule = MatchRule(app_id_regex="fire.*")
        assert rule.app_id_regex == "fire.*"

    def test_valid_title(self):
        rule = MatchRule(title="My Window")
        assert rule.title == "My Window"

    def test_valid_pid(self):
        rule = MatchRule(pid=1234)
        assert rule.pid == 1234

    def test_valid_any_of(self):
        rule = MatchRule(any_of=[MatchRule(app_id="a"), MatchRule(app_id="b")])
        assert len(rule.any_of) == 2

    def test_valid_not_rule(self):
        rule = MatchRule(not_rule=MatchRule(app_id="unwanted"), app_id="firefox")
        assert rule.not_rule is not None

    def test_empty_match_rule_rejected(self):
        with pytest.raises(ValueError, match="at least one"):
            MatchRule()

    def test_all_none_rejected(self):
        with pytest.raises(ValueError):
            MatchRule(app_id=None, title=None)

    def test_and_composition(self):
        """Multiple flat fields are ANDed."""
        rule = MatchRule(app_id="firefox", title_regex="docs")
        assert rule.app_id == "firefox"
        assert rule.title_regex == "docs"

class TestPlacementSpec:
    def test_defaults(self):
        p = PlacementSpec()
        assert p.floating is False
        assert p.fullscreen is False
        assert p.maximized is False

    def test_floating_and_fullscreen_conflict(self):
        with pytest.raises(ValueError):
            PlacementSpec(floating=True, fullscreen=True)

    def test_column_width_proportion(self):
        p = PlacementSpec(column_width=0.6)
        assert p.column_width == 0.6

    def test_column_width_pixels(self):
        p = PlacementSpec(column_width="px:800")
        assert p.column_width == "px:800"

class TestSpawnSpec:
    def test_command_list(self):
        s = SpawnSpec(command=["kitty", "--class", "dev"])
        assert s.command == ["kitty", "--class", "dev"]

    def test_command_string(self):
        s = SpawnSpec(command="firefox")
        assert s.command == "firefox"

class TestAppSpec:
    def test_minimal(self):
        app = AppSpec(name="editor", match=MatchRule(app_id="nvim"))
        assert app.name == "editor"
        assert app.spawn is None
        assert app.optional is False

    def test_with_spawn_and_placement(self):
        app = AppSpec(
            name="editor",
            match=MatchRule(app_id="nvim"),
            spawn=SpawnSpec(command=["nvim"]),
            placement=PlacementSpec(focus=True),
        )
        assert app.spawn.command == ["nvim"]
        assert app.placement.focus is True

class TestSessionSpec:
    def test_minimal(self):
        spec = SessionSpec(
            name="test",
            workspaces=[WorkspaceSpec(name="ws1")],
        )
        assert spec.name == "test"
        assert len(spec.workspaces) == 1

    def test_full(self):
        spec = SessionSpec(
            name="dev",
            description="dev env",
            options=SessionOptions(mode="reconcile"),
            workspaces=[
                WorkspaceSpec(
                    name="code",
                    output="DP-1",
                    apps=[
                        AppSpec(
                            name="editor",
                            match=MatchRule(app_id="nvim"),
                            spawn=SpawnSpec(command=["nvim"]),
                        ),
                    ],
                ),
            ],
        )
        assert spec.workspaces[0].apps[0].name == "editor"
```

**Validation checkpoint:** All tests pass with `devenv shell -- python -m pytest tests/test_spec_models.py -v`.

---

### Step 1.5: Implement spec validators

**File:** `src/nirip/spec/validators.py`

This module performs **session-level** validation that goes beyond individual model validation. It runs after parsing and checks cross-cutting concerns.

```python
"""Aggressive session spec validation."""
from __future__ import annotations
import re
from nirip.spec.models import SessionSpec, MatchRule

class ValidationResult:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

def validate_session(spec: SessionSpec) -> ValidationResult:
    """Run all validation checks on a session spec."""
    result = ValidationResult()
    _check_unique_workspace_names(spec, result)
    _check_unique_app_names(spec, result)
    _check_depends_on_refs(spec, result)
    _check_regex_patterns(spec, result)
    _check_weak_matchers(spec, result)
    _check_inter_app_conflicts(spec, result)
    _check_spawn_commands(spec, result)
    return result
```

**Validation functions to implement:**

1. **`_check_unique_workspace_names`** — workspace names must be unique within the session. Add error if duplicated.

2. **`_check_unique_app_names`** — app names must be unique within each workspace. Add error if duplicated.

3. **`_check_depends_on_refs`** — each `depends_on` entry must name an app in the same workspace. Add error for dangling references. Also detect cycles (topological sort or DFS cycle detection).

4. **`_check_regex_patterns`** — compile all `app_id_regex` and `title_regex` patterns with `re.compile()`. Add error if a pattern is invalid.

5. **`_check_weak_matchers`** — if a MatchRule has only `title_regex` (no `app_id` or `app_id_regex`), add a warning unless the app is `optional: true`.

6. **`_check_inter_app_conflicts`** — if two apps in the session have identical `app_id` and no differentiating title/regex criteria, add an error. If on different workspaces with same criteria, add a warning.

7. **`_check_spawn_commands`** — if `spawn.command` is an empty list or empty string, add error.

**Tests:** `tests/test_spec_validators.py`

```python
from nirip.spec.models import SessionSpec, WorkspaceSpec, AppSpec, MatchRule, SpawnSpec
from nirip.spec.validators import validate_session

def _make_spec(**kwargs) -> SessionSpec:
    """Helper to build minimal specs for testing."""
    defaults = dict(name="test", workspaces=[WorkspaceSpec(name="ws1")])
    defaults.update(kwargs)
    return SessionSpec(**defaults)

class TestUniqueWorkspaceNames:
    def test_duplicate_workspace_names(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code"),
            WorkspaceSpec(name="code"),
        ])
        result = validate_session(spec)
        assert not result.valid
        assert any("workspace" in e.lower() and "duplicate" in e.lower() for e in result.errors)

    def test_unique_workspace_names_ok(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code"),
            WorkspaceSpec(name="comms"),
        ])
        result = validate_session(spec)
        assert result.valid

class TestUniqueAppNames:
    def test_duplicate_app_names_in_workspace(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code", apps=[
                AppSpec(name="editor", match=MatchRule(app_id="a")),
                AppSpec(name="editor", match=MatchRule(app_id="b")),
            ]),
        ])
        result = validate_session(spec)
        assert not result.valid

class TestDependsOnRefs:
    def test_dangling_depends_on(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code", apps=[
                AppSpec(name="term", match=MatchRule(app_id="t"), depends_on=["editor"]),
            ]),
        ])
        result = validate_session(spec)
        assert not result.valid
        assert any("depends_on" in e.lower() for e in result.errors)

    def test_valid_depends_on(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code", apps=[
                AppSpec(name="editor", match=MatchRule(app_id="e")),
                AppSpec(name="term", match=MatchRule(app_id="t"), depends_on=["editor"]),
            ]),
        ])
        result = validate_session(spec)
        assert result.valid

class TestRegexPatterns:
    def test_invalid_regex(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code", apps=[
                AppSpec(name="a", match=MatchRule(title_regex="[invalid")),
            ]),
        ])
        result = validate_session(spec)
        assert not result.valid

class TestWeakMatchers:
    def test_title_regex_only_warns(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code", apps=[
                AppSpec(name="a", match=MatchRule(title_regex="docs")),
            ]),
        ])
        result = validate_session(spec)
        assert result.valid  # warning, not error
        assert len(result.warnings) > 0

    def test_title_regex_optional_no_warn(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code", apps=[
                AppSpec(name="a", match=MatchRule(title_regex="docs"), optional=True),
            ]),
        ])
        result = validate_session(spec)
        assert len(result.warnings) == 0

class TestInterAppConflicts:
    def test_same_app_id_same_workspace_error(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code", apps=[
                AppSpec(name="a", match=MatchRule(app_id="firefox")),
                AppSpec(name="b", match=MatchRule(app_id="firefox")),
            ]),
        ])
        result = validate_session(spec)
        assert not result.valid

class TestSpawnCommands:
    def test_empty_command_list(self):
        spec = _make_spec(workspaces=[
            WorkspaceSpec(name="code", apps=[
                AppSpec(name="a", match=MatchRule(app_id="x"), spawn=SpawnSpec(command=[])),
            ]),
        ])
        result = validate_session(spec)
        assert not result.valid
```

**Validation checkpoint:** All tests pass.

---

### Step 1.6: Implement YAML loader

**File:** `src/nirip/spec/loader.py`

**Add `pyyaml` to dependencies** in `pyproject.toml`:
```toml
dependencies = [
    "pydantic>=2.12.5",
    "niri-pypc",
    "niri-state",
    "pyyaml>=6.0",
]
```

Then run `devenv shell -- uv sync` to install it.

```python
"""YAML session spec loader."""
from __future__ import annotations
from pathlib import Path
import yaml
from nirip.spec.models import SessionSpec
from nirip.spec.validators import validate_session, ValidationResult
from nirip.errors import SpecError, SpecValidationError


def load_spec_from_file(path: str | Path) -> SessionSpec:
    """Load and validate a session spec from a YAML file."""
    path = Path(path).expanduser()
    if not path.exists():
        raise SpecError(f"Session file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SpecError(f"Cannot read session file: {e}") from e
    return load_spec_from_string(text, source=str(path))


def load_spec_from_string(text: str, *, source: str = "<string>") -> SessionSpec:
    """Load and validate a session spec from a YAML string."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SpecError(f"Invalid YAML in {source}: {e}") from e

    if not isinstance(data, dict):
        raise SpecError(f"Expected a YAML mapping at top level in {source}, got {type(data).__name__}")

    try:
        spec = SessionSpec.model_validate(data)
    except Exception as e:
        raise SpecError(f"Invalid session spec in {source}: {e}") from e

    result = validate_session(spec)
    if not result.valid:
        raise SpecValidationError(
            f"Spec validation failed in {source}:\n" +
            "\n".join(f"  - {err}" for err in result.errors)
        )

    return spec


def load_spec_from_dict(data: dict) -> SessionSpec:
    """Load and validate a session spec from a dictionary."""
    try:
        spec = SessionSpec.model_validate(data)
    except Exception as e:
        raise SpecError(f"Invalid session spec: {e}") from e

    result = validate_session(spec)
    if not result.valid:
        raise SpecValidationError(
            "Spec validation failed:\n" +
            "\n".join(f"  - {err}" for err in result.errors)
        )
    return spec
```

**Tests:** `tests/test_spec_loader.py`

```python
import pytest
from nirip.spec.loader import load_spec_from_string, load_spec_from_file
from nirip.errors import SpecError, SpecValidationError

VALID_YAML = """
name: test-session
workspaces:
  - name: code
    output: DP-1
    apps:
      - name: editor
        match:
          app_id: nvim
        spawn:
          command: ["nvim"]
"""

MINIMAL_YAML = """
name: minimal
workspaces:
  - name: ws1
"""

def test_load_valid_yaml():
    spec = load_spec_from_string(VALID_YAML)
    assert spec.name == "test-session"
    assert len(spec.workspaces) == 1
    assert spec.workspaces[0].apps[0].name == "editor"

def test_load_minimal_yaml():
    spec = load_spec_from_string(MINIMAL_YAML)
    assert spec.name == "minimal"

def test_load_invalid_yaml():
    with pytest.raises(SpecError, match="Invalid YAML"):
        load_spec_from_string(":::not yaml:::")

def test_load_non_mapping():
    with pytest.raises(SpecError, match="mapping"):
        load_spec_from_string("- just a list")

def test_load_empty_match_rule():
    bad_yaml = """
name: bad
workspaces:
  - name: ws1
    apps:
      - name: app1
        match: {}
"""
    with pytest.raises(SpecError):
        load_spec_from_string(bad_yaml)

def test_load_missing_file():
    with pytest.raises(SpecError, match="not found"):
        load_spec_from_file("/nonexistent/path.yaml")

def test_yaml_alias_any():
    """Test that 'any' in YAML maps to 'any_of' field."""
    yaml_text = """
name: test
workspaces:
  - name: ws1
    apps:
      - name: browser
        match:
          any:
            - app_id: firefox
            - app_id: chromium
"""
    spec = load_spec_from_string(yaml_text)
    assert spec.workspaces[0].apps[0].match.any_of is not None
    assert len(spec.workspaces[0].apps[0].match.any_of) == 2
```

**Validation checkpoint:** All tests pass. Also test with the full example YAML from NIRIP_CONCEPT.md section 4.2 — create `tests/fixtures/dev-day.yaml` with that content and add a test that loads it.

---

### Step 1.7: Implement spec defaults

**File:** `src/nirip/spec/defaults.py`

This is a simple utility used by the normalizer (step 1.8). It applies session-level defaults to apps that don't override them.

```python
"""Default option merging for session specs."""
from __future__ import annotations
from nirip.spec.models import SessionSpec, AppSpec


def apply_defaults(spec: SessionSpec) -> SessionSpec:
    """Return a new SessionSpec with defaults applied to all apps.

    Currently applies:
    - SessionOptions.default_startup_timeout_s to apps that use the default 20.0
    """
    default_timeout = spec.options.default_startup_timeout_s
    new_workspaces = []
    for ws in spec.workspaces:
        new_apps = []
        for app in ws.apps:
            if app.startup_timeout_s == 20.0 and default_timeout != 20.0:
                app = app.model_copy(update={"startup_timeout_s": default_timeout})
            new_apps.append(app)
        new_workspaces.append(ws.model_copy(update={"apps": new_apps}))
    return spec.model_copy(update={"workspaces": new_workspaces})
```

**Test:** Add to `tests/test_spec_defaults.py`:
```python
from nirip.spec.models import SessionSpec, WorkspaceSpec, AppSpec, MatchRule, SessionOptions
from nirip.spec.defaults import apply_defaults

def test_default_timeout_applied():
    spec = SessionSpec(
        name="t",
        options=SessionOptions(default_startup_timeout_s=30.0),
        workspaces=[WorkspaceSpec(name="ws", apps=[
            AppSpec(name="a", match=MatchRule(app_id="x")),
        ])],
    )
    result = apply_defaults(spec)
    assert result.workspaces[0].apps[0].startup_timeout_s == 30.0

def test_explicit_timeout_not_overridden():
    spec = SessionSpec(
        name="t",
        options=SessionOptions(default_startup_timeout_s=30.0),
        workspaces=[WorkspaceSpec(name="ws", apps=[
            AppSpec(name="a", match=MatchRule(app_id="x"), startup_timeout_s=5.0),
        ])],
    )
    result = apply_defaults(spec)
    assert result.workspaces[0].apps[0].startup_timeout_s == 5.0
```

---

### Step 1.8: Implement normalizer

**File:** `src/nirip/resolve/normalizer.py`

The normalizer transforms `SessionSpec` -> `NormalizedSession` by:
1. Applying defaults
2. Flattening apps from nested workspaces into a flat list with `workspace_name`
3. Validating `depends_on` references
4. Building lookup indexes

**File:** `src/nirip/resolve/models.py` (normalization models only for now)

Implement these models first:

```python
"""Resolution and normalization models."""
from __future__ import annotations
from pydantic import BaseModel, Field, computed_field
from enum import StrEnum
from nirip.spec.models import MatchRule, SpawnSpec, PlacementSpec, SessionOptions


class NormalizedApp(BaseModel):
    """An app after default merging and reference resolution."""
    name: str
    workspace_name: str
    match: MatchRule
    spawn: SpawnSpec | None
    placement: PlacementSpec
    optional: bool
    startup_timeout_s: float
    depends_on: list[str]


class NormalizedWorkspace(BaseModel):
    """A workspace after default merging."""
    name: str
    output: str | None
    focus: bool
    app_names: list[str]


class NormalizedSession(BaseModel):
    """The session spec after all normalization passes."""
    name: str
    description: str
    options: SessionOptions
    workspaces: list[NormalizedWorkspace]
    apps: list[NormalizedApp]
    app_index: dict[str, NormalizedApp] = Field(default_factory=dict)
```

Then the normalizer:

```python
"""Spec normalization: SessionSpec -> NormalizedSession."""
from __future__ import annotations
from nirip.spec.models import SessionSpec
from nirip.spec.defaults import apply_defaults
from nirip.resolve.models import NormalizedApp, NormalizedWorkspace, NormalizedSession


def normalize(spec: SessionSpec) -> NormalizedSession:
    """Transform a validated SessionSpec into a NormalizedSession."""
    spec = apply_defaults(spec)

    workspaces: list[NormalizedWorkspace] = []
    all_apps: list[NormalizedApp] = []
    app_index: dict[str, NormalizedApp] = {}

    for ws in spec.workspaces:
        app_names: list[str] = []
        for app in ws.apps:
            key = f"{ws.name}/{app.name}"
            norm_app = NormalizedApp(
                name=app.name,
                workspace_name=ws.name,
                match=app.match,
                spawn=app.spawn,
                placement=app.placement,
                optional=app.optional,
                startup_timeout_s=app.startup_timeout_s,
                depends_on=app.depends_on,
            )
            all_apps.append(norm_app)
            app_index[key] = norm_app
            app_names.append(app.name)

        workspaces.append(NormalizedWorkspace(
            name=ws.name,
            output=ws.output,
            focus=ws.focus,
            app_names=app_names,
        ))

    return NormalizedSession(
        name=spec.name,
        description=spec.description,
        options=spec.options,
        workspaces=workspaces,
        apps=all_apps,
        app_index=app_index,
    )
```

**Tests:** `tests/test_normalizer.py`

```python
from nirip.spec.models import (
    SessionSpec, WorkspaceSpec, AppSpec, MatchRule, SpawnSpec, SessionOptions,
)
from nirip.resolve.normalizer import normalize

def test_basic_normalization():
    spec = SessionSpec(
        name="test",
        workspaces=[
            WorkspaceSpec(name="code", output="DP-1", apps=[
                AppSpec(name="editor", match=MatchRule(app_id="nvim")),
                AppSpec(name="term", match=MatchRule(app_id="kitty")),
            ]),
            WorkspaceSpec(name="comms", apps=[
                AppSpec(name="slack", match=MatchRule(app_id="Slack")),
            ]),
        ],
    )
    norm = normalize(spec)
    assert norm.name == "test"
    assert len(norm.workspaces) == 2
    assert len(norm.apps) == 3
    assert norm.apps[0].workspace_name == "code"
    assert norm.apps[2].workspace_name == "comms"
    assert "code/editor" in norm.app_index
    assert "comms/slack" in norm.app_index

def test_defaults_applied_during_normalization():
    spec = SessionSpec(
        name="test",
        options=SessionOptions(default_startup_timeout_s=30.0),
        workspaces=[WorkspaceSpec(name="ws", apps=[
            AppSpec(name="a", match=MatchRule(app_id="x")),
        ])],
    )
    norm = normalize(spec)
    assert norm.apps[0].startup_timeout_s == 30.0

def test_app_names_preserved_in_workspace():
    spec = SessionSpec(
        name="test",
        workspaces=[WorkspaceSpec(name="ws", apps=[
            AppSpec(name="a", match=MatchRule(app_id="x")),
            AppSpec(name="b", match=MatchRule(app_id="y")),
        ])],
    )
    norm = normalize(spec)
    assert norm.workspaces[0].app_names == ["a", "b"]
```

**Validation checkpoint:** All tests pass.

---

### Step 1.9: Implement matching engine

**File:** `src/nirip/resolve/matcher.py`

This is the most critical module. The matching engine evaluates a `MatchRule` against a single window and produces a confidence score. It also evaluates an app against all candidate windows to produce a `MatchDecision`.

Since the matcher needs to work against `Window` objects from `niri-pypc`, but we need to test without a running compositor, create a **protocol/structural type** for the window interface:

```python
"""Match rule evaluation against live windows."""
from __future__ import annotations
import re
from typing import Protocol
from nirip.resolve.models import MatchDecision, MatchCandidate
from nirip.spec.models import MatchRule


class WindowLike(Protocol):
    """Structural type for window objects (niri-pypc Window or test mocks)."""
    @property
    def id(self) -> int: ...
    @property
    def app_id(self) -> str | None: ...
    @property
    def title(self) -> str | None: ...
    @property
    def pid(self) -> int | None: ...
    @property
    def workspace_id(self) -> int | None: ...
    @property
    def is_floating(self) -> bool: ...


def evaluate_rule(rule: MatchRule, window: WindowLike) -> tuple[bool, float, list[str]]:
    """Evaluate a MatchRule against a single window.

    Returns (matched, confidence, reasons).
    """
    # ... implementation below


def match_app(
    app_name: str,
    workspace_name: str,
    rule: MatchRule,
    windows: list[WindowLike],
) -> MatchDecision:
    """Match an app's rule against all candidate windows.

    Returns a MatchDecision with the best match (if any) and all candidates.
    """
    # ... implementation below
```

**Implementation of `evaluate_rule`:**

The function checks each criterion in the rule and accumulates results:

```python
def evaluate_rule(rule: MatchRule, window: WindowLike) -> tuple[bool, float, list[str]]:
    scores: list[float] = []
    reasons: list[str] = []
    failed = False

    if rule.app_id is not None:
        if window.app_id == rule.app_id:
            scores.append(1.0)
            reasons.append(f"app_id exact match: {rule.app_id}")
        else:
            failed = True
            reasons.append(f"app_id mismatch: wanted {rule.app_id}, got {window.app_id}")

    if rule.app_id_regex is not None:
        if window.app_id and re.search(rule.app_id_regex, window.app_id):
            scores.append(0.9)
            reasons.append(f"app_id_regex match: {rule.app_id_regex}")
        else:
            failed = True
            reasons.append(f"app_id_regex no match: {rule.app_id_regex}")

    if rule.title is not None:
        if window.title == rule.title:
            scores.append(0.8)
            reasons.append(f"title exact match: {rule.title}")
        else:
            failed = True
            reasons.append(f"title mismatch: wanted {rule.title}, got {window.title}")

    if rule.title_regex is not None:
        if window.title and re.search(rule.title_regex, window.title):
            scores.append(0.7)
            reasons.append(f"title_regex match: {rule.title_regex}")
        else:
            failed = True
            reasons.append(f"title_regex no match: {rule.title_regex}")

    if rule.pid is not None:
        if window.pid == rule.pid:
            scores.append(1.0)
            reasons.append(f"pid match: {rule.pid}")
        else:
            failed = True
            reasons.append(f"pid mismatch: wanted {rule.pid}, got {window.pid}")

    # Handle any_of (OR): at least one sub-rule must match
    if rule.any_of is not None:
        best_sub_score = 0.0
        any_matched = False
        for sub in rule.any_of:
            sub_matched, sub_score, sub_reasons = evaluate_rule(sub, window)
            if sub_matched and sub_score > best_sub_score:
                best_sub_score = sub_score
                any_matched = True
        if any_matched:
            scores.append(best_sub_score)
            reasons.append(f"any_of: matched with confidence {best_sub_score:.1f}")
        else:
            failed = True
            reasons.append("any_of: no sub-rule matched")

    # Handle not_rule (negation)
    if rule.not_rule is not None:
        neg_matched, _, _ = evaluate_rule(rule.not_rule, window)
        if neg_matched:
            failed = True
            reasons.append("not_rule: excluded by negation")
        else:
            reasons.append("not_rule: passed (window does not match exclusion)")

    if failed:
        return (False, 0.0, reasons)

    if not scores:
        return (False, 0.0, ["no criteria evaluated"])

    confidence = min(scores)  # AND: take minimum
    return (True, confidence, reasons)
```

**Implementation of `match_app`:**

```python
def match_app(
    app_name: str,
    workspace_name: str,
    rule: MatchRule,
    windows: list[WindowLike],
) -> MatchDecision:
    candidates: list[MatchCandidate] = []

    for w in windows:
        matched, confidence, reasons = evaluate_rule(rule, w)
        if matched:
            candidates.append(MatchCandidate(
                window_id=w.id,
                confidence=confidence,
                reasons=reasons,
            ))

    # Sort by confidence descending, then window_id ascending (deterministic tie-break)
    candidates.sort(key=lambda c: (-c.confidence, c.window_id))

    best_id = candidates[0].window_id if candidates else None
    best_confidence = candidates[0].confidence if candidates else 0.0
    rationale = candidates[0].reasons if candidates else ["no matching window found"]

    return MatchDecision(
        app_name=app_name,
        workspace_name=workspace_name,
        best=best_id,
        candidates=candidates,
        confidence=best_confidence,
        rationale=rationale,
    )
```

**Add MatchDecision and MatchCandidate to `resolve/models.py`:**

```python
class MatchCandidate(BaseModel):
    """A single window evaluated against a MatchRule."""
    window_id: int
    confidence: float
    reasons: list[str]


class MatchDecision(BaseModel):
    """Result of matching an app against all live windows."""
    app_name: str
    workspace_name: str
    best: int | None = None
    candidates: list[MatchCandidate] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def is_ambiguous(self) -> bool:
        high_confidence = [c for c in self.candidates if c.confidence > 0.6]
        return len(high_confidence) > 1

    @computed_field
    @property
    def is_matched(self) -> bool:
        return self.best is not None
```

**Tests:** `tests/test_matcher.py`

Create a mock window class for testing:

```python
from dataclasses import dataclass
from nirip.resolve.matcher import evaluate_rule, match_app
from nirip.spec.models import MatchRule


@dataclass
class MockWindow:
    id: int
    app_id: str | None = None
    title: str | None = None
    pid: int | None = None
    workspace_id: int | None = None
    is_floating: bool = False


class TestEvaluateRule:
    def test_exact_app_id_match(self):
        w = MockWindow(id=1, app_id="firefox")
        matched, conf, reasons = evaluate_rule(MatchRule(app_id="firefox"), w)
        assert matched is True
        assert conf == 1.0

    def test_app_id_mismatch(self):
        w = MockWindow(id=1, app_id="chromium")
        matched, conf, reasons = evaluate_rule(MatchRule(app_id="firefox"), w)
        assert matched is False

    def test_app_id_regex(self):
        w = MockWindow(id=1, app_id="firefox-nightly")
        matched, conf, reasons = evaluate_rule(MatchRule(app_id_regex="firefox.*"), w)
        assert matched is True
        assert conf == 0.9

    def test_title_exact(self):
        w = MockWindow(id=1, title="My Editor")
        matched, conf, reasons = evaluate_rule(MatchRule(title="My Editor"), w)
        assert matched is True
        assert conf == 0.8

    def test_title_regex(self):
        w = MockWindow(id=1, title="docs.rs - Rust Documentation")
        matched, conf, reasons = evaluate_rule(MatchRule(title_regex=r"docs\.rs"), w)
        assert matched is True
        assert conf == 0.7

    def test_pid_match(self):
        w = MockWindow(id=1, pid=1234)
        matched, conf, reasons = evaluate_rule(MatchRule(pid=1234), w)
        assert matched is True
        assert conf == 1.0

    def test_and_composition(self):
        w = MockWindow(id=1, app_id="firefox", title="docs.rs")
        matched, conf, reasons = evaluate_rule(
            MatchRule(app_id="firefox", title_regex="docs"), w
        )
        assert matched is True
        assert conf == 0.7  # min of 1.0 and 0.7

    def test_and_partial_fail(self):
        w = MockWindow(id=1, app_id="firefox", title="reddit")
        matched, conf, reasons = evaluate_rule(
            MatchRule(app_id="firefox", title_regex="docs"), w
        )
        assert matched is False

    def test_any_of(self):
        w = MockWindow(id=1, app_id="chromium")
        rule = MatchRule(any_of=[
            MatchRule(app_id="firefox"),
            MatchRule(app_id="chromium"),
        ])
        matched, conf, reasons = evaluate_rule(rule, w)
        assert matched is True
        assert conf == 1.0

    def test_any_of_none_match(self):
        w = MockWindow(id=1, app_id="edge")
        rule = MatchRule(any_of=[
            MatchRule(app_id="firefox"),
            MatchRule(app_id="chromium"),
        ])
        matched, conf, reasons = evaluate_rule(rule, w)
        assert matched is False

    def test_not_rule(self):
        w = MockWindow(id=1, app_id="firefox", title="Private Browsing")
        rule = MatchRule(
            app_id="firefox",
            not_rule=MatchRule(title_regex="Private"),
        )
        matched, conf, reasons = evaluate_rule(rule, w)
        assert matched is False

    def test_not_rule_passes(self):
        w = MockWindow(id=1, app_id="firefox", title="docs.rs")
        rule = MatchRule(
            app_id="firefox",
            not_rule=MatchRule(title_regex="Private"),
        )
        matched, conf, reasons = evaluate_rule(rule, w)
        assert matched is True

    def test_none_app_id_on_window(self):
        w = MockWindow(id=1, app_id=None)
        matched, conf, reasons = evaluate_rule(MatchRule(app_id="firefox"), w)
        assert matched is False


class TestMatchApp:
    def test_single_match(self):
        windows = [
            MockWindow(id=1, app_id="firefox"),
            MockWindow(id=2, app_id="kitty"),
        ]
        decision = match_app("browser", "code", MatchRule(app_id="firefox"), windows)
        assert decision.is_matched
        assert decision.best == 1
        assert len(decision.candidates) == 1

    def test_no_match(self):
        windows = [MockWindow(id=1, app_id="kitty")]
        decision = match_app("browser", "code", MatchRule(app_id="firefox"), windows)
        assert not decision.is_matched
        assert decision.best is None

    def test_ambiguous(self):
        windows = [
            MockWindow(id=1, app_id="firefox"),
            MockWindow(id=2, app_id="firefox"),
        ]
        decision = match_app("browser", "code", MatchRule(app_id="firefox"), windows)
        assert decision.is_matched
        assert decision.is_ambiguous
        assert len(decision.candidates) == 2
        assert decision.best == 1  # first by window_id tiebreak

    def test_deterministic_tiebreak(self):
        """Same confidence -> lowest window_id wins."""
        windows = [
            MockWindow(id=99, app_id="firefox"),
            MockWindow(id=5, app_id="firefox"),
        ]
        decision = match_app("browser", "code", MatchRule(app_id="firefox"), windows)
        assert decision.best == 5

    def test_confidence_ranking(self):
        """Higher confidence wins over lower."""
        windows = [
            MockWindow(id=1, app_id="firefox", title="docs.rs"),
            MockWindow(id=2, app_id="firefox", title="reddit"),
        ]
        rule = MatchRule(app_id="firefox", title_regex="docs")
        decision = match_app("docs", "code", rule, windows)
        assert decision.best == 1
        assert decision.candidates[0].confidence > decision.candidates[1].confidence
```

**Validation checkpoint:** All 25+ matcher tests pass. This is the most important test suite — it validates the core matching logic. Do not proceed until every test passes.

---

### Step 1.10: Phase 1 integration test

Create `tests/test_phase1_integration.py` that exercises the full Phase 1 pipeline:

```python
"""Integration test: YAML -> parse -> validate -> normalize -> match."""
from dataclasses import dataclass
from nirip.spec.loader import load_spec_from_string
from nirip.resolve.normalizer import normalize
from nirip.resolve.matcher import match_app

FULL_YAML = """
name: dev-day
description: Full development environment
options:
  mode: reconcile
  match_existing: true
  launch_missing: true

workspaces:
  - name: code
    output: DP-1
    apps:
      - name: editor
        match:
          app_id: dev-editor
        spawn:
          command: ["kitty", "--class", "dev-editor", "-e", "nvim"]
        placement:
          focus: true
          column_width: 0.6

      - name: terminal
        match:
          app_id: dev-term
        spawn:
          command: ["kitty", "--class", "dev-term"]
        depends_on: [editor]

  - name: comms
    apps:
      - name: slack
        match:
          app_id: Slack
        spawn:
          command: ["slack"]

      - name: discord
        match:
          app_id: discord
        spawn:
          command: ["discord"]
        optional: true
"""

@dataclass
class MockWindow:
    id: int
    app_id: str | None = None
    title: str | None = None
    pid: int | None = None
    workspace_id: int | None = None
    is_floating: bool = False


def test_full_phase1_pipeline():
    # 1. Parse + validate
    spec = load_spec_from_string(FULL_YAML)
    assert spec.name == "dev-day"

    # 2. Normalize
    norm = normalize(spec)
    assert len(norm.apps) == 4
    assert norm.apps[0].workspace_name == "code"
    assert norm.apps[1].depends_on == ["editor"]

    # 3. Match against mock windows
    mock_windows = [
        MockWindow(id=10, app_id="dev-editor", title="nvim"),
        MockWindow(id=11, app_id="dev-term", title="zsh"),
        MockWindow(id=12, app_id="firefox", title="docs.rs"),
        MockWindow(id=13, app_id="Slack", title="Slack | #general"),
    ]

    # Editor should match
    editor_match = match_app("editor", "code", norm.apps[0].match, mock_windows)
    assert editor_match.is_matched
    assert editor_match.best == 10

    # Terminal should match
    term_match = match_app("terminal", "code", norm.apps[1].match, mock_windows)
    assert term_match.is_matched
    assert term_match.best == 11

    # Slack should match
    slack_match = match_app("slack", "comms", norm.apps[2].match, mock_windows)
    assert slack_match.is_matched
    assert slack_match.best == 13

    # Discord should not match (no discord window in mock)
    discord_match = match_app("discord", "comms", norm.apps[3].match, mock_windows)
    assert not discord_match.is_matched
```

**Phase 1 complete when:** All tests pass across all test files:
```bash
devenv shell -- python -m pytest tests/ -v
```

Expected: 40+ tests, all passing.

---

## Phase 2: Resolution + Diff

**Goal:** Resolve a normalized session against a live snapshot, detect drift, produce human-readable diff.

**Packages:** `resolve/resolver.py`, `planning/models.py` (SessionDiff only)

### Step 2.1: Add resolution models to resolve/models.py

Add the following to the existing `src/nirip/resolve/models.py`:

```python
class ResolutionStatus(StrEnum):
    MATCHED = "matched"
    DRIFTED = "drifted"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    OPTIONAL_MISSING = "optional_missing"


class DriftKind(StrEnum):
    WRONG_WORKSPACE = "wrong_workspace"
    WRONG_FLOATING = "wrong_floating"
    WRONG_FULLSCREEN = "wrong_fullscreen"
    WRONG_MAXIMIZED = "wrong_maximized"
    WRONG_COLUMN_WIDTH = "wrong_column_width"
    WRONG_WINDOW_HEIGHT = "wrong_window_height"


class DriftItem(BaseModel):
    kind: DriftKind
    current: str
    desired: str


class AppResolution(BaseModel):
    app_name: str
    workspace_name: str
    status: ResolutionStatus
    match_decision: MatchDecision
    drift: list[DriftItem] = Field(default_factory=list)
    action_required: bool

    @computed_field
    @property
    def needs_spawn(self) -> bool:
        return self.status == ResolutionStatus.MISSING and self.action_required

    @computed_field
    @property
    def needs_move(self) -> bool:
        return any(d.kind == DriftKind.WRONG_WORKSPACE for d in self.drift)


class WorkspaceResolution(BaseModel):
    name: str
    exists: bool
    output_correct: bool
    desired_output: str | None
    current_output: str | None
    app_resolutions: list[AppResolution]


class Resolution(BaseModel):
    session_name: str
    workspace_resolutions: list[WorkspaceResolution]
    unmatched_apps: list[AppResolution] = Field(default_factory=list)
    ambiguous_apps: list[AppResolution] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def has_drift(self) -> bool:
        return any(
            ar.action_required
            for wr in self.workspace_resolutions
            for ar in wr.app_resolutions
        ) or any(
            not wr.exists or not wr.output_correct
            for wr in self.workspace_resolutions
        )

    @computed_field
    @property
    def fully_converged(self) -> bool:
        return not self.has_drift and not self.unmatched_apps and not self.ambiguous_apps
```

**Test:** Verify models instantiate correctly:
```python
# tests/test_resolution_models.py
from nirip.resolve.models import (
    ResolutionStatus, DriftKind, DriftItem, AppResolution,
    WorkspaceResolution, Resolution, MatchDecision,
)

def test_app_resolution_needs_spawn():
    md = MatchDecision(app_name="a", workspace_name="ws")
    ar = AppResolution(
        app_name="a", workspace_name="ws",
        status=ResolutionStatus.MISSING,
        match_decision=md,
        action_required=True,
    )
    assert ar.needs_spawn is True

def test_resolution_fully_converged():
    md = MatchDecision(app_name="a", workspace_name="ws", best=1, confidence=1.0)
    ar = AppResolution(
        app_name="a", workspace_name="ws",
        status=ResolutionStatus.MATCHED,
        match_decision=md,
        action_required=False,
    )
    wr = WorkspaceResolution(
        name="ws", exists=True, output_correct=True,
        desired_output=None, current_output=None,
        app_resolutions=[ar],
    )
    res = Resolution(session_name="test", workspace_resolutions=[wr])
    assert res.fully_converged is True
```

---

### Step 2.2: Implement resolver

**File:** `src/nirip/resolve/resolver.py`

The resolver takes a `NormalizedSession` and a snapshot-like object and produces a `Resolution`.

For testability, use a protocol for the snapshot:

```python
"""Resolution: NormalizedSession + Snapshot -> Resolution."""
from __future__ import annotations
from typing import Protocol, Mapping
from nirip.resolve.models import (
    Resolution, WorkspaceResolution, AppResolution,
    ResolutionStatus, DriftItem, DriftKind, MatchDecision,
)
from nirip.resolve.normalizer import NormalizedSession, NormalizedApp, NormalizedWorkspace
from nirip.resolve.matcher import match_app, WindowLike


class WorkspaceLike(Protocol):
    @property
    def id(self) -> int: ...
    @property
    def name(self) -> str | None: ...
    @property
    def output(self) -> str | None: ...


class SnapshotLike(Protocol):
    @property
    def windows(self) -> Mapping[int, WindowLike]: ...
    @property
    def workspaces(self) -> Mapping[int, WorkspaceLike]: ...


def resolve(session: NormalizedSession, snapshot: SnapshotLike) -> Resolution:
    """Resolve a normalized session against live state."""
    all_windows = list(snapshot.windows.values())
    live_workspaces = {ws.name: ws for ws in snapshot.workspaces.values() if ws.name}

    workspace_resolutions: list[WorkspaceResolution] = []
    unmatched: list[AppResolution] = []
    ambiguous: list[AppResolution] = []
    warnings: list[str] = []

    for norm_ws in session.workspaces:
        live_ws = live_workspaces.get(norm_ws.name)
        exists = live_ws is not None
        output_correct = True
        current_output = None

        if live_ws:
            current_output = live_ws.output
            if norm_ws.output and live_ws.output != norm_ws.output:
                output_correct = False

        app_resolutions: list[AppResolution] = []
        for app_name in norm_ws.app_names:
            norm_app = session.app_index[f"{norm_ws.name}/{app_name}"]
            app_res = _resolve_app(norm_app, norm_ws, all_windows, live_ws, snapshot)
            app_resolutions.append(app_res)

            if app_res.status == ResolutionStatus.MISSING:
                unmatched.append(app_res)
            elif app_res.status == ResolutionStatus.AMBIGUOUS:
                ambiguous.append(app_res)

        workspace_resolutions.append(WorkspaceResolution(
            name=norm_ws.name,
            exists=exists,
            output_correct=output_correct,
            desired_output=norm_ws.output,
            current_output=current_output,
            app_resolutions=app_resolutions,
        ))

    return Resolution(
        session_name=session.name,
        workspace_resolutions=workspace_resolutions,
        unmatched_apps=unmatched,
        ambiguous_apps=ambiguous,
        warnings=warnings,
    )


def _resolve_app(
    app: NormalizedApp,
    ws: NormalizedWorkspace,
    all_windows: list[WindowLike],
    live_ws: WorkspaceLike | None,
    snapshot: SnapshotLike,
) -> AppResolution:
    decision = match_app(app.name, app.workspace_name, app.match, all_windows)

    if not decision.is_matched:
        status = ResolutionStatus.OPTIONAL_MISSING if app.optional else ResolutionStatus.MISSING
        action_required = not app.optional and app.spawn is not None
        if not app.optional and app.spawn is None:
            # Can't fix: no spawn and not optional — just mark missing
            action_required = False
        return AppResolution(
            app_name=app.name,
            workspace_name=app.workspace_name,
            status=status,
            match_decision=decision,
            action_required=action_required,
        )

    if decision.is_ambiguous:
        return AppResolution(
            app_name=app.name,
            workspace_name=app.workspace_name,
            status=ResolutionStatus.AMBIGUOUS,
            match_decision=decision,
            action_required=False,
        )

    # Matched — check for drift
    matched_window = snapshot.windows[decision.best]
    drift = _detect_drift(app, ws, matched_window, live_ws)

    status = ResolutionStatus.DRIFTED if drift else ResolutionStatus.MATCHED
    return AppResolution(
        app_name=app.name,
        workspace_name=app.workspace_name,
        status=status,
        match_decision=decision,
        drift=drift,
        action_required=bool(drift),
    )


def _detect_drift(
    app: NormalizedApp,
    ws: NormalizedWorkspace,
    window: WindowLike,
    live_ws: WorkspaceLike | None,
) -> list[DriftItem]:
    drift: list[DriftItem] = []

    # Check workspace
    if live_ws and window.workspace_id != live_ws.id:
        drift.append(DriftItem(
            kind=DriftKind.WRONG_WORKSPACE,
            current=f"workspace_id={window.workspace_id}",
            desired=f"workspace={ws.name}",
        ))

    # Check floating
    if app.placement.floating and not window.is_floating:
        drift.append(DriftItem(
            kind=DriftKind.WRONG_FLOATING,
            current="tiling",
            desired="floating",
        ))
    elif not app.placement.floating and window.is_floating:
        drift.append(DriftItem(
            kind=DriftKind.WRONG_FLOATING,
            current="floating",
            desired="tiling",
        ))

    return drift
```

**Tests:** `tests/test_resolver.py`

```python
from dataclasses import dataclass, field
from types import MappingProxyType
from nirip.spec.models import SessionSpec, WorkspaceSpec, AppSpec, MatchRule, SpawnSpec, PlacementSpec
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.resolve.models import ResolutionStatus


@dataclass
class MockWindow:
    id: int
    app_id: str | None = None
    title: str | None = None
    pid: int | None = None
    workspace_id: int | None = None
    is_floating: bool = False

@dataclass
class MockWorkspace:
    id: int
    name: str | None = None
    output: str | None = None

@dataclass
class MockSnapshot:
    windows: MappingProxyType  # int -> MockWindow
    workspaces: MappingProxyType  # int -> MockWorkspace

    @classmethod
    def create(cls, windows: list[MockWindow], workspaces: list[MockWorkspace]) -> "MockSnapshot":
        return cls(
            windows=MappingProxyType({w.id: w for w in windows}),
            workspaces=MappingProxyType({ws.id: ws for ws in workspaces}),
        )


def test_fully_converged():
    spec = SessionSpec(name="t", workspaces=[
        WorkspaceSpec(name="code", apps=[
            AppSpec(name="editor", match=MatchRule(app_id="nvim")),
        ]),
    ])
    norm = normalize(spec)
    snap = MockSnapshot.create(
        windows=[MockWindow(id=1, app_id="nvim", workspace_id=100)],
        workspaces=[MockWorkspace(id=100, name="code")],
    )
    res = resolve(norm, snap)
    assert res.fully_converged

def test_missing_window():
    spec = SessionSpec(name="t", workspaces=[
        WorkspaceSpec(name="code", apps=[
            AppSpec(name="editor", match=MatchRule(app_id="nvim"), spawn=SpawnSpec(command=["nvim"])),
        ]),
    ])
    norm = normalize(spec)
    snap = MockSnapshot.create(windows=[], workspaces=[MockWorkspace(id=100, name="code")])
    res = resolve(norm, snap)
    assert not res.fully_converged
    assert len(res.unmatched_apps) == 1
    assert res.unmatched_apps[0].needs_spawn

def test_optional_missing():
    spec = SessionSpec(name="t", workspaces=[
        WorkspaceSpec(name="code", apps=[
            AppSpec(name="discord", match=MatchRule(app_id="discord"), optional=True),
        ]),
    ])
    norm = normalize(spec)
    snap = MockSnapshot.create(windows=[], workspaces=[MockWorkspace(id=100, name="code")])
    res = resolve(norm, snap)
    wr = res.workspace_resolutions[0]
    assert wr.app_resolutions[0].status == ResolutionStatus.OPTIONAL_MISSING

def test_wrong_workspace_drift():
    spec = SessionSpec(name="t", workspaces=[
        WorkspaceSpec(name="code", apps=[
            AppSpec(name="editor", match=MatchRule(app_id="nvim")),
        ]),
    ])
    norm = normalize(spec)
    snap = MockSnapshot.create(
        windows=[MockWindow(id=1, app_id="nvim", workspace_id=200)],  # wrong workspace
        workspaces=[
            MockWorkspace(id=100, name="code"),
            MockWorkspace(id=200, name="comms"),
        ],
    )
    res = resolve(norm, snap)
    assert res.has_drift
    ar = res.workspace_resolutions[0].app_resolutions[0]
    assert ar.status == ResolutionStatus.DRIFTED
    assert ar.needs_move

def test_missing_workspace():
    spec = SessionSpec(name="t", workspaces=[
        WorkspaceSpec(name="newws", apps=[]),
    ])
    norm = normalize(spec)
    snap = MockSnapshot.create(windows=[], workspaces=[])
    res = resolve(norm, snap)
    assert not res.workspace_resolutions[0].exists
    assert res.has_drift
```

---

### Step 2.3: Implement SessionDiff

**File:** `src/nirip/planning/models.py` (just the `SessionDiff` class for now)

```python
"""Planning models: SessionDiff, Plan, PlanStep, StepKind."""
from __future__ import annotations
from pydantic import BaseModel, Field, computed_field


class SessionDiff(BaseModel):
    """Human-readable diff between desired and current state."""
    session_name: str
    already_matched: list[str] = Field(default_factory=list)
    will_spawn: list[str] = Field(default_factory=list)
    will_move: list[str] = Field(default_factory=list)
    will_adjust: list[str] = Field(default_factory=list)
    workspace_changes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def has_drift(self) -> bool:
        return bool(self.will_spawn or self.will_move or self.will_adjust or self.workspace_changes)

    @computed_field
    @property
    def has_errors(self) -> bool:
        return bool(self.errors)
```

**File:** `src/nirip/resolve/differ.py` — builds a `SessionDiff` from a `Resolution`:

```python
"""Build a SessionDiff from a Resolution."""
from __future__ import annotations
from nirip.resolve.models import Resolution, ResolutionStatus, AppResolution
from nirip.planning.models import SessionDiff


def build_diff(resolution: Resolution) -> SessionDiff:
    """Transform a Resolution into a human-readable SessionDiff."""
    diff = SessionDiff(session_name=resolution.session_name)

    for wr in resolution.workspace_resolutions:
        if not wr.exists:
            msg = f"{wr.name}: create workspace"
            if wr.desired_output:
                msg += f" on {wr.desired_output}"
            diff.workspace_changes.append(msg)
        elif not wr.output_correct:
            diff.workspace_changes.append(
                f"{wr.name}: move to output {wr.desired_output} (currently {wr.current_output})"
            )

        for ar in wr.app_resolutions:
            _classify_app(ar, diff)

    diff.warnings.extend(resolution.warnings)
    return diff


def _classify_app(ar: AppResolution, diff: SessionDiff) -> None:
    match ar.status:
        case ResolutionStatus.MATCHED:
            md = ar.match_decision
            diff.already_matched.append(
                f"{ar.app_name}: matched window {md.best} (confidence={md.confidence:.1f})"
            )
        case ResolutionStatus.DRIFTED:
            for d in ar.drift:
                diff.will_adjust.append(f"{ar.app_name}: {d.kind.value} ({d.current} -> {d.desired})")
            if ar.needs_move:
                diff.will_move.append(
                    f"{ar.app_name}: window {ar.match_decision.best} -> workspace {ar.workspace_name}"
                )
        case ResolutionStatus.MISSING:
            if ar.action_required:
                diff.will_spawn.append(f"{ar.app_name}: will spawn on {ar.workspace_name}")
            else:
                diff.errors.append(f"{ar.app_name}: no match and no spawn command")
        case ResolutionStatus.AMBIGUOUS:
            diff.warnings.append(
                f"{ar.app_name}: ambiguous match ({len(ar.match_decision.candidates)} candidates)"
            )
        case ResolutionStatus.OPTIONAL_MISSING:
            diff.warnings.append(f"{ar.app_name}: not found (optional, skipping)")
```

**Tests:** `tests/test_differ.py`

```python
from nirip.spec.models import SessionSpec, WorkspaceSpec, AppSpec, MatchRule, SpawnSpec
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.resolve.differ import build_diff
from tests.test_resolver import MockSnapshot, MockWindow, MockWorkspace


def test_diff_fully_converged():
    spec = SessionSpec(name="t", workspaces=[
        WorkspaceSpec(name="code", apps=[
            AppSpec(name="editor", match=MatchRule(app_id="nvim")),
        ]),
    ])
    snap = MockSnapshot.create(
        windows=[MockWindow(id=1, app_id="nvim", workspace_id=100)],
        workspaces=[MockWorkspace(id=100, name="code")],
    )
    res = resolve(normalize(spec), snap)
    diff = build_diff(res)
    assert not diff.has_drift
    assert len(diff.already_matched) == 1

def test_diff_will_spawn():
    spec = SessionSpec(name="t", workspaces=[
        WorkspaceSpec(name="code", apps=[
            AppSpec(name="editor", match=MatchRule(app_id="nvim"), spawn=SpawnSpec(command=["nvim"])),
        ]),
    ])
    snap = MockSnapshot.create(windows=[], workspaces=[MockWorkspace(id=100, name="code")])
    res = resolve(normalize(spec), snap)
    diff = build_diff(res)
    assert diff.has_drift
    assert len(diff.will_spawn) == 1

def test_diff_missing_workspace():
    spec = SessionSpec(name="t", workspaces=[WorkspaceSpec(name="new")])
    snap = MockSnapshot.create(windows=[], workspaces=[])
    res = resolve(normalize(spec), snap)
    diff = build_diff(res)
    assert len(diff.workspace_changes) == 1

def test_diff_optional_missing():
    spec = SessionSpec(name="t", workspaces=[
        WorkspaceSpec(name="ws", apps=[
            AppSpec(name="opt", match=MatchRule(app_id="x"), optional=True),
        ]),
    ])
    snap = MockSnapshot.create(windows=[], workspaces=[MockWorkspace(id=1, name="ws")])
    res = resolve(normalize(spec), snap)
    diff = build_diff(res)
    assert not diff.has_drift
    assert len(diff.warnings) == 1
```

**Phase 2 complete when:** All resolver, resolution model, and differ tests pass.

---

## Phase 3: Planning

**Goal:** Compile a Resolution into an ordered Plan with step dependencies.

### Step 3.1: Add Plan models to planning/models.py

Add `StepKind`, `PlanStep`, and `Plan` to the existing `src/nirip/planning/models.py` (which already has `SessionDiff`).

See NIRIP_CONCEPT.md section 10.1 for the exact model definitions. Key points:

- `StepKind` is a `StrEnum` with 13 values
- `PlanStep` has `id`, `kind`, `app_name`, `workspace_name`, `window_id`, `description`, `depends_on`, `metadata`
- `Plan` has `session_name`, `steps`, `resolution`, `warnings` and computed fields `requires_spawn`, `step_count`, `is_empty`

**Tests:** Verify models instantiate and computed fields work.

### Step 3.2: Implement ordering module

**File:** `src/nirip/planning/ordering.py`

Implement topological sort for step dependencies:

```python
"""Topological sort for plan step ordering."""
from __future__ import annotations
from nirip.errors import PlanningError


def topological_sort(deps: dict[str, list[str]]) -> list[str]:
    """Sort items topologically given a dependency map.

    Args:
        deps: mapping of item -> list of items it depends on.

    Returns:
        Items in execution order (dependencies first).

    Raises:
        PlanningError: if a cycle is detected.
    """
    # Kahn's algorithm
    ...
```

**Test:** `tests/test_ordering.py` — test cycle detection, simple chains, diamond dependencies.

### Step 3.3: Implement plan compiler

**File:** `src/nirip/planning/compiler.py`

```python
"""Compile a Resolution into a Plan."""
from __future__ import annotations
from nirip.resolve.models import Resolution, ResolutionStatus, DriftKind
from nirip.planning.models import Plan, PlanStep, StepKind
from nirip.planning.ordering import topological_sort
from nirip.resolve.normalizer import NormalizedSession


def compile_plan(resolution: Resolution, session: NormalizedSession) -> Plan:
    """Compile a Resolution into an ordered execution Plan."""
    steps: list[PlanStep] = []
    step_counter = 0

    def next_id() -> str:
        nonlocal step_counter
        step_counter += 1
        return f"step-{step_counter}"

    # 1. Workspace steps
    for wr in resolution.workspace_resolutions:
        if not wr.exists:
            steps.append(PlanStep(
                id=next_id(), kind=StepKind.ENSURE_WORKSPACE,
                workspace_name=wr.name,
                description=f"Create workspace '{wr.name}'",
            ))
        if not wr.output_correct and wr.desired_output:
            steps.append(PlanStep(
                id=next_id(), kind=StepKind.MOVE_WORKSPACE_TO_OUTPUT,
                workspace_name=wr.name,
                description=f"Move workspace '{wr.name}' to output {wr.desired_output}",
                metadata={"output": wr.desired_output},
            ))

    # 2. App steps (per workspace, respecting depends_on)
    # ... emit SPAWN_WINDOW, WAIT_FOR_WINDOW, MOVE_WINDOW_TO_WORKSPACE, etc.

    # 3. Focus steps last

    return Plan(
        session_name=resolution.session_name,
        steps=steps,
        resolution=resolution,
    )
```

Full implementation details: iterate each workspace's app resolutions. For each:
- **MATCHED**: skip
- **DRIFTED**: emit steps for each drift item
- **MISSING + spawn**: emit `SPAWN_WINDOW` + `WAIT_FOR_WINDOW` + placement steps
- **AMBIGUOUS**: add warning
- **OPTIONAL_MISSING**: skip

Wire up `depends_on` by tracking step IDs per app name and setting `depends_on` on dependent steps.

**Tests:** `tests/test_compiler.py`

Test that the compiler produces the expected steps for various scenarios:
- Fully converged -> empty plan
- Missing app with spawn -> SPAWN + WAIT steps
- Wrong workspace -> MOVE step
- Missing workspace -> ENSURE step
- Dependencies -> correct step ordering

**Phase 3 complete when:** All compiler and ordering tests pass.

---

## Phase 4: Execution

**Goal:** Execute plan steps against live niri state with event-verified confirmation.

### Step 4.1: Implement action helpers

**File:** `src/nirip/execution/actions.py`

Thin wrappers over the verbose niri-pypc action construction:

```python
"""Action helpers: thin ergonomic wrappers over niri-pypc generated types."""
from __future__ import annotations
from niri_pypc.types.generated.request import ActionRequest
from niri_pypc.types.generated.action import (
    Action, SpawnAction, SpawnShAction, FocusWorkspaceAction, FocusWindowAction,
    MoveWindowToWorkspaceAction, MoveWindowToFloatingAction, MoveWindowToTilingAction,
    MoveWorkspaceToMonitorAction, FullscreenWindowAction, MaximizeWindowToEdgesAction,
    SetColumnWidthAction, SetWindowHeightAction, SetWorkspaceNameAction,
)
from niri_pypc.types.generated.models import (
    WorkspaceReferenceArg, NameWorkspaceReferenceArg,
    SizeChange, SetProportionSizeChange, SetFixedSizeChange,
)


def spawn_action(command: list[str]) -> ActionRequest:
    return ActionRequest(payload=Action(root=SpawnAction(command=command)))

def spawn_sh_action(command: str) -> ActionRequest:
    return ActionRequest(payload=Action(root=SpawnShAction(command=command)))

def focus_workspace_action(name: str) -> ActionRequest:
    ref = WorkspaceReferenceArg(root=NameWorkspaceReferenceArg(payload=name))
    return ActionRequest(payload=Action(root=FocusWorkspaceAction(reference=ref)))

def focus_window_action(window_id: int) -> ActionRequest:
    return ActionRequest(payload=Action(root=FocusWindowAction(id=window_id)))

def move_window_to_workspace_action(window_id: int, workspace_name: str) -> ActionRequest:
    ref = WorkspaceReferenceArg(root=NameWorkspaceReferenceArg(payload=workspace_name))
    return ActionRequest(payload=Action(root=MoveWindowToWorkspaceAction(
        window_id=window_id, focus=False, reference=ref,
    )))

def move_workspace_to_output_action(output: str, workspace_name: str | None = None) -> ActionRequest:
    ref = None
    if workspace_name:
        ref = WorkspaceReferenceArg(root=NameWorkspaceReferenceArg(payload=workspace_name))
    return ActionRequest(payload=Action(root=MoveWorkspaceToMonitorAction(output=output, reference=ref)))

def set_floating_action(window_id: int) -> ActionRequest:
    return ActionRequest(payload=Action(root=MoveWindowToFloatingAction(id=window_id)))

def set_tiling_action(window_id: int) -> ActionRequest:
    return ActionRequest(payload=Action(root=MoveWindowToTilingAction(id=window_id)))

def fullscreen_action(window_id: int) -> ActionRequest:
    return ActionRequest(payload=Action(root=FullscreenWindowAction(id=window_id)))

def set_column_width_proportion(proportion: float) -> ActionRequest:
    change = SizeChange(root=SetProportionSizeChange(payload=proportion))
    return ActionRequest(payload=Action(root=SetColumnWidthAction(change=change)))

def set_column_width_fixed(pixels: int) -> ActionRequest:
    change = SizeChange(root=SetFixedSizeChange(payload=pixels))
    return ActionRequest(payload=Action(root=SetColumnWidthAction(change=change)))
```

**Test:** `tests/test_actions.py` — verify each helper constructs a valid `ActionRequest`:
```python
from nirip.execution.actions import spawn_action, focus_workspace_action, move_window_to_workspace_action

def test_spawn_action():
    req = spawn_action(["kitty"])
    assert req.payload.root.command == ["kitty"]

def test_focus_workspace():
    req = focus_workspace_action("code")
    assert req.payload.root.reference.root.payload == "code"

def test_move_window_to_workspace():
    req = move_window_to_workspace_action(42, "code")
    assert req.payload.root.window_id == 42
```

### Step 4.2: Implement verification predicates

**File:** `src/nirip/execution/predicates.py`

Each step kind maps to a predicate over `Snapshot` that verifies the step completed:

```python
"""Snapshot predicates for step verification."""
from __future__ import annotations
from collections.abc import Callable
from niri_state.api.snapshot import Snapshot
from niri_state.api.selectors import windows, workspaces
from nirip.planning.models import PlanStep, StepKind
from nirip.spec.models import MatchRule
from nirip.resolve.matcher import evaluate_rule


def make_verify_predicate(step: PlanStep, match_rule: MatchRule | None = None) -> Callable[[Snapshot], bool]:
    """Create a verification predicate for a plan step."""
    match step.kind:
        case StepKind.ENSURE_WORKSPACE:
            ws_name = step.workspace_name
            def verify(snap: Snapshot) -> bool:
                return any(ws.name == ws_name for ws in snap.workspaces.values())
            return verify

        case StepKind.SPAWN_WINDOW | StepKind.WAIT_FOR_WINDOW:
            if match_rule is None:
                raise ValueError("match_rule required for SPAWN/WAIT steps")
            def verify(snap: Snapshot) -> bool:
                for w in snap.windows.values():
                    matched, _, _ = evaluate_rule(match_rule, w)
                    if matched:
                        return True
                return False
            return verify

        case StepKind.MOVE_WINDOW_TO_WORKSPACE:
            wid = step.window_id
            ws_name = step.workspace_name
            def verify(snap: Snapshot) -> bool:
                w = snap.windows.get(wid)
                if w is None:
                    return False
                for ws in snap.workspaces.values():
                    if ws.name == ws_name and w.workspace_id == ws.id:
                        return True
                return False
            return verify

        case StepKind.FOCUS_WINDOW:
            wid = step.window_id
            def verify(snap: Snapshot) -> bool:
                return snap.focused_window_id == wid
            return verify

        case StepKind.FOCUS_WORKSPACE:
            ws_name = step.workspace_name
            def verify(snap: Snapshot) -> bool:
                fws_id = snap.focused_workspace_id
                if fws_id is None:
                    return False
                ws = snap.workspaces.get(fws_id)
                return ws is not None and ws.name == ws_name
            return verify

        case _:
            # For steps we can't verify (size changes etc), return always-true
            return lambda _: True
```

**Test:** Test each predicate with mock snapshots.

### Step 4.3: Implement execution runtime models

**File:** `src/nirip/execution/models.py` and `src/nirip/execution/runtime.py`

See NIRIP_CONCEPT.md sections 11.2 and 12.1 for the exact models (`StepOutcome`, `StepResult`, `ApplyResult`, `AppRuntimeState`, `SessionRuntime`).

### Step 4.4: Implement executor

**File:** `src/nirip/execution/executor.py`

The executor runs plan steps sequentially, using `niri-state` waiters for verification:

```python
"""Plan executor with event-verified step confirmation."""
from __future__ import annotations
import time
from niri_state import NiriState, NiriStateConfig
from niri_state.api.waiters import wait_until
from niri_state.api.errors import WaitTimeoutError
from niri_pypc import NiriClient
from nirip.planning.models import Plan, PlanStep, StepKind
from nirip.execution.models import ApplyResult, StepResult, StepOutcome
from nirip.execution.actions import (
    spawn_action, focus_workspace_action, focus_window_action,
    move_window_to_workspace_action, move_workspace_to_output_action,
    set_floating_action, set_tiling_action,
)
from nirip.execution.predicates import make_verify_predicate
from nirip.resolve.normalizer import NormalizedSession


async def execute_plan(
    plan: Plan,
    session: NormalizedSession,
    state: NiriState,
    client: NiriClient,
    state_config: NiriStateConfig,
) -> ApplyResult:
    results: list[StepResult] = []
    start = time.monotonic()

    for step in plan.steps:
        # Check dependencies
        if not _deps_satisfied(step, results):
            results.append(StepResult(
                step=step, outcome=StepOutcome.FAILED,
                message="dependency not met",
            ))
            continue

        result = await _execute_step(step, session, state, client, state_config)
        results.append(result)

        if result.outcome in (StepOutcome.FAILED, StepOutcome.TIMED_OUT):
            if session.options.stop_on_error:
                break

    elapsed = time.monotonic() - start
    success = all(r.outcome in (StepOutcome.COMPLETED, StepOutcome.SKIPPED) for r in results)

    return ApplyResult(
        session_name=plan.session_name,
        success=success,
        steps=results,
        total_duration_s=elapsed,
    )
```

For `_execute_step`: follow the 5-step pattern from NIRIP_CONCEPT.md section 11.3 (check preconditions, check if done, execute action, wait for verification, record result).

**Tests:** Use mock `NiriState` and `NiriClient` to test the executor without a live compositor. This requires creating mock implementations of the async interfaces.

### Step 4.5: Implement AsyncNirip and SyncNirip facades

**Files:** `src/nirip/facade/async_nirip.py`, `src/nirip/facade/sync_nirip.py`

Wire up the full pipeline: load spec -> normalize -> resolve -> compile -> execute.

See NIRIP_CONCEPT.md section 14 for the exact API surface.

**Phase 4 complete when:** Action helpers, predicates, executor, and facade tests all pass. Integration test with mock state passes an end-to-end apply.

---

## Phase 5: Capture + Polish

### Step 5.1: Implement capture

**Files:** `src/nirip/capture/capturer.py`, `src/nirip/capture/inference.py`

See NIRIP_CONCEPT.md section 13. Key logic:
- Iterate workspaces, skip unnamed
- For each window, infer app name from `app_id` and build `MatchRule`
- Generate notes about duplicate `app_id`s and missing spawn commands
- Output `CapturedSession` model

### Step 5.2: Implement CLI

**File:** `src/nirip/cli/main.py`, `src/nirip/cli/commands.py`

Implement the 7 commands from NIRIP_CONCEPT.md section 17.1. Use `click` or `typer` for argument parsing.

The apply flow (section 17.2) is the most important:
1. Load spec
2. Open AsyncNirip
3. Normalize, resolve, compile
4. Display diff, confirm
5. Execute
6. Report

### Step 5.3: Implement doctor

Add `DoctorReport` and `DoctorCheck` models (NIRIP_CONCEPT.md section 18).

Doctor checks:
- Connection: can we reach niri socket?
- niri-state health: is it LIVE?
- Protocol version: niri-ipc 25.11?
- Spec validation (if spec provided)
- Match check (if spec provided): run resolution and report ambiguities

### Step 5.4: Final integration tests

- `tests/test_integration_full.py`: Load real YAML, mock a full snapshot, run the complete pipeline end-to-end.
- Test idempotency: apply twice with same state should produce empty plan on second run.
- Test capture -> re-apply roundtrip: capture should produce a spec that resolves as fully converged against the same snapshot.

---

## Test coverage checklist

At the end of implementation, verify coverage across these areas:

| Area | Test file | Key scenarios |
|---|---|---|
| Error hierarchy | `test_errors.py` | Inheritance, raising, catching |
| Config | `test_config.py` | Defaults, frozen |
| Spec models | `test_spec_models.py` | All models, validators, edge cases |
| Spec validation | `test_spec_validators.py` | All 7 check functions |
| YAML loader | `test_spec_loader.py` | Valid, invalid, edge cases |
| Defaults | `test_spec_defaults.py` | Timeout merging |
| Normalizer | `test_normalizer.py` | Flattening, indexing, defaults |
| Matcher | `test_matcher.py` | Every criterion, AND/OR/NOT, confidence, tiebreak |
| Resolution models | `test_resolution_models.py` | Computed fields |
| Resolver | `test_resolver.py` | All ResolutionStatus cases, drift detection |
| Differ | `test_differ.py` | All diff categories |
| Ordering | `test_ordering.py` | Topological sort, cycles |
| Compiler | `test_compiler.py` | Step generation, dependencies |
| Actions | `test_actions.py` | All helper functions |
| Predicates | `test_predicates.py` | All step kinds |
| Executor | `test_executor.py` | Success, failure, timeout, stop_on_error |
| Capture | `test_capture.py` | Inference, notes, roundtrip |
| Phase 1 integration | `test_phase1_integration.py` | Full YAML -> match pipeline |
| Full integration | `test_integration_full.py` | End-to-end with mocks |

Run the full suite:
```bash
devenv shell -- python -m pytest tests/ -v --cov=nirip --cov-report=term-missing
```

Target: 90%+ line coverage on core modules (spec, resolve, planning). Execution and facade may be lower due to async/live integration code.
