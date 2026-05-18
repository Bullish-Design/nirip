from __future__ import annotations

import pytest

from nirip.spec import (
    MatchRule,
    NiripError,
    SessionSpec,
    SpecValidationError,
    load_from_dict,
    load_from_string,
    validate_session,
)


def test_match_rule_requires_criteria() -> None:
    with pytest.raises(ValueError, match="at least one criterion"):
        MatchRule()


def test_validate_detects_duplicate_workspace_and_app() -> None:
    spec = SessionSpec.model_validate(
        {
            "name": "s",
            "workspaces": [
                {"name": "ws", "apps": [{"name": "a", "match": {"app_id": "x"}}]},
                {
                    "name": "ws",
                    "apps": [
                        {"name": "a", "match": {"app_id": "x"}},
                        {"name": "a", "match": {"app_id": "y"}},
                    ],
                },
            ],
        }
    )
    result = validate_session(spec)
    assert result.valid is False
    assert any("duplicate workspace name" in e for e in result.errors)
    assert any("duplicate app name" in e for e in result.errors)


def test_load_from_string_rejects_bad_yaml_shape() -> None:
    with pytest.raises(NiripError, match="expected mapping"):
        load_from_string("- not\n- a\n- mapping")


def test_load_from_dict_raises_validation_error() -> None:
    with pytest.raises(SpecValidationError) as exc:
        load_from_dict(
            {
                "name": "s",
                "workspaces": [{"name": "ws", "apps": [{"name": "a", "match": {"title_regex": "("}}]}],
            }
        )
    assert exc.value.errors


def test_validate_detects_dependency_cycle() -> None:
    spec = SessionSpec.model_validate(
        {
            "name": "s",
            "workspaces": [
                {
                    "name": "ws",
                    "apps": [
                        {"name": "a", "match": {"app_id": "a"}, "depends_on": ["b"]},
                        {"name": "b", "match": {"app_id": "b"}, "depends_on": ["a"]},
                    ],
                }
            ],
        }
    )
    result = validate_session(spec)
    assert any("dependency cycle" in e for e in result.errors)


def test_load_from_dict_success_tuple() -> None:
    spec, report = load_from_dict(
        {
            "name": "s",
            "workspaces": [{"name": "ws", "apps": [{"name": "firefox", "match": {"app_id": "org.mozilla.firefox"}}]}],
        }
    )
    assert isinstance(spec, SessionSpec)
    assert report.valid is True
