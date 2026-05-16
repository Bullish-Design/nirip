"""YAML loading and validation pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from nirip.errors import SpecError, SpecValidationError
from nirip.spec.defaults import apply_defaults
from nirip.spec.models import SessionSpec
from nirip.spec.validators import ValidatedSpec, validate_session


def load_spec_from_file(path: str | Path) -> ValidatedSpec:
    p = Path(path)
    if not p.exists():
        raise SpecError(f"file not found: {p}")
    text = p.read_text(encoding="utf-8")
    return load_spec_from_string(text, source=str(p))


def load_spec_from_string(text: str, *, source: str = "<string>") -> ValidatedSpec:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SpecError(f"YAML parse error in {source}: {e}") from e
    if not isinstance(data, dict):
        raise SpecError(f"expected mapping in {source}, got {type(data).__name__}")
    return load_spec_from_dict(data, source=source)


def load_spec_from_dict(data: dict[str, Any], *, source: str = "<dict>") -> ValidatedSpec:
    try:
        spec = SessionSpec.model_validate(data)
    except Exception as e:
        raise SpecError(f"spec parse error in {source}: {e}") from e

    spec = apply_defaults(spec)
    validation = validate_session(spec)

    if not validation.valid:
        raise SpecValidationError(validation.errors, validation.warnings)

    return ValidatedSpec(spec=spec, validation=validation)
