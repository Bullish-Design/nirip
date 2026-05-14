"""nirip public API."""

from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.facade.sync_nirip import SyncNirip
from nirip.spec.loader import load_spec_from_dict, load_spec_from_file, load_spec_from_string
from nirip.spec.models import SessionSpec


def load_session(path: str) -> SessionSpec:
    """Convenience loader wrapper."""
    return load_spec_from_file(path)


def apply_session(spec: SessionSpec) -> ApplyResult:
    """Convenience sync apply wrapper."""
    with SyncNirip() as nirip:
        return nirip.apply(spec)


__all__ = [
    "ApplyResult",
    "AsyncNirip",
    "NiripConfig",
    "SessionSpec",
    "SyncNirip",
    "apply_session",
    "load_session",
    "load_spec_from_dict",
    "load_spec_from_file",
    "load_spec_from_string",
]
