def test_smoke():
    import editor_command_system
    assert editor_command_system.__version__


def test_errors_importable():
    from editor_command_system.errors import CommandSystemError
    assert CommandSystemError.code == "command_system_error"
