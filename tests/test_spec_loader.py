import pytest

from nirip.errors import SpecError
from nirip.spec.loader import load_spec_from_dict


def test_load_spec_validated() -> None:
    validated = load_spec_from_dict({"name": "s", "workspaces": [{"name": "w"}]})
    assert validated.spec.name == "s"


def test_load_spec_invalid_type() -> None:
    with pytest.raises(SpecError):
        load_spec_from_dict({"name": "s", "workspaces": "bad"})
