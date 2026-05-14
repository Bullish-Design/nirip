"""nirip public API."""

from nirip.config import NiripConfig
from nirip.facade.async_nirip import AsyncNirip
from nirip.facade.sync_nirip import SyncNirip
from nirip.spec.loader import load_spec_from_dict, load_spec_from_file, load_spec_from_string


def load_session(path: str) -> object:
    """Convenience loader wrapper."""
    return load_spec_from_file(path)


def apply_session(spec: object) -> object:
    """Convenience sync apply wrapper."""
    with SyncNirip() as nirip:
        return nirip.apply(spec)


__all__ = [
    "AsyncNirip",
    "NiripConfig",
    "SyncNirip",
    "apply_session",
    "load_session",
    "load_spec_from_dict",
    "load_spec_from_file",
    "load_spec_from_string",
]
