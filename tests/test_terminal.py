"""需求 5：开发者终端展示命令为何不可用/被禁用。"""
from __future__ import annotations

from editor_command_system.executor import ExecutionRequest
from editor_command_system.keybindings import KeyBinding
from editor_command_system.registry import Command
from editor_command_system.terminal import DeveloperTerminal


def test_explain_disabled_reasons(registry, executor, keybindings, context):
    registry.register(Command("save.x", "Save X", lambda: None,
                              category="file", enablement="dirty"))
    keybindings.add_default(KeyBinding("save.x", "ctrl+s", source="builtin"))
    term = DeveloperTerminal(registry, executor, keybindings)
    exp = term.explain("save.x")
    assert exp.exists and exp.visible and not exp.enabled
    text = exp.render()
    assert "禁用" in text and "dirty" in text and "ctrl+s" in text
    context.set("dirty", True)
    assert term.explain("save.x").enabled is True


def test_help_filters_invisible(registry, executor, context):
    registry.register(Command("visible.cmd", "Visible", lambda: None))
    registry.register(Command("hidden.cmd", "Hidden", lambda: None,
                              when="editorFocused"))
    term = DeveloperTerminal(registry, executor)
    ids = [e.command_id for e in term.help()]
    assert "visible.cmd" in ids and "hidden.cmd" not in ids
    ids = [e.command_id for e in term.help("visible")]
    assert ids == ["visible.cmd"]


def test_explain_missing_command(registry, executor):
    term = DeveloperTerminal(registry, executor)
    exp = term.explain("nope")
    assert not exp.exists and not exp.usable
    assert "不存在" in exp.render()


def test_terminal_run_reports_error_code(registry, executor):
    registry.register(Command("only.dev", "Dev", lambda: 1,
                              required_permission="developer"))
    term = DeveloperTerminal(registry, executor)
    result = term.run("only.dev", caller_scope="guest")
    assert result.error_code == "permission_denied"
