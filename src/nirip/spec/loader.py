"""YAML session spec loader."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from nirip.errors import SpecError, SpecValidationError
from nirip.spec.models import SessionSpec
from nirip.spec.validators import validate_session


def _validate_spec(spec: SessionSpec, source: str) -> SessionSpec:
    result = validate_session(spec)
    if not result.valid:
        raise SpecValidationError(
            f"Spec validation failed in {source}:\n" + "\n".join(f"  - {err}" for err in result.errors)
        )
    return spec


def load_spec_from_file(path: str | Path) -> SessionSpec:
    """Load and validate a session spec from a YAML file."""

    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise SpecError(f"Session file not found: {resolved}")
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"Cannot read session file: {exc}") from exc
    return load_spec_from_string(text, source=str(resolved))


def load_spec_from_string(text: str, *, source: str = "<string>") -> SessionSpec:
    """Load and validate a session spec from a YAML string."""

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"Invalid YAML in {source}: {exc}") from exc

    if not isinstance(data, dict):
        raise SpecError(f"Expected a YAML mapping at top level in {source}, got {type(data).__name__}")
    return load_spec_from_dict(data, source=source)


def load_spec_from_dict(data: dict[str, Any], *, source: str = "<dict>") -> SessionSpec:
    """Load and validate a session spec from a dictionary."""

    try:
        spec = SessionSpec.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise SpecError(f"Invalid session spec in {source}: {exc}") from exc
    return _validate_spec(spec, source)
