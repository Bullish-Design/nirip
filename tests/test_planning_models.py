import pytest

from nirip.planning.models import CreateWorkspaceStep, MoveWindowToWorkspaceStep, ResizeAxis, ResizeWindowStep


def test_plan_step_discriminator_roundtrip() -> None:
    step = CreateWorkspaceStep(id="1", description="d", workspace_name="w")
    data = step.model_dump()
    parsed = CreateWorkspaceStep.model_validate(data)
    assert parsed.kind == "create_workspace"


def test_typed_fields_present() -> None:
    step = MoveWindowToWorkspaceStep(
        id="m",
        description="move",
        app_name="a",
        workspace_name="w",
        window_id=1,
    )
    assert step.window_id == 1


def test_resize_window_step_requires_exactly_one_size() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ResizeWindowStep(id="r1", description="resize", axis=ResizeAxis.WIDTH)
    with pytest.raises(ValueError, match="exactly one"):
        ResizeWindowStep(id="r2", description="resize", axis=ResizeAxis.WIDTH, proportion=0.5, pixels=100)
    step = ResizeWindowStep(id="r3", description="resize", axis=ResizeAxis.WIDTH, proportion=0.5)
    assert step.proportion == 0.5
