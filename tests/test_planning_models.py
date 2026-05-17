from nirip.planning.models import CreateWorkspaceStep, MoveWindowToWorkspaceStep


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
        target_workspace="w",
    )
    assert step.window_id == 1
