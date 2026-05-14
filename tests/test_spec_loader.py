import pytest

from nirip.errors import SpecError
from nirip.spec.loader import load_spec_from_string


def test_load_valid_yaml() -> None:
    spec = load_spec_from_string(
        """
name: test-session
workspaces:
  - name: code
    apps:
      - name: editor
        match:
          app_id: nvim
        spawn:
          command: ["nvim"]
"""
    )
    assert spec.name == "test-session"


def test_load_non_mapping() -> None:
    with pytest.raises(SpecError):
        load_spec_from_string("- just a list")
