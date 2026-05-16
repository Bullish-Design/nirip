from pydantic import ValidationError

from nirip._base import NiripModel


class Example(NiripModel):
    value: int


def test_extra_forbid() -> None:
    try:
        Example(value=1, other=2)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        assert True


def test_frozen() -> None:
    x = Example(value=1)
    try:
        x.value = 2
        raise AssertionError("expected ValidationError")
    except ValidationError:
        assert True
