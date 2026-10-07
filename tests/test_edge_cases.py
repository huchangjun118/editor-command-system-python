"""额外边界：历史容量、用户覆盖清除、扩展移除后快捷键不可解析。"""
from __future__ import annotations

from editor_command_system.history import HistoryEntry, HistoryManager
from editor_command_system.keybindings import BindingLayer, KeyBinding, Platform
from editor_command_system.registry import Command


def _entry(cid):
    return HistoryEntry(cid, {}, lambda r, a: None)


def test_history_limit_evicts_oldest():
    history = HistoryManager(limit=3)
    for i in range(5):
        history.push(_entry(f"cmd.{i}"))
    assert [e.command_id for e in history.entries()] == ["cmd.2", "cmd.3", "cmd.4"]


def test_clear_user_bindings_restores_default_resolution(keybindings):
    keybindings.add_default(KeyBinding("a.save", "ctrl+s", source="builtin"))
    keybindings.set_user_binding("ctrl+s", "a.other")
    assert keybindings.resolve("ctrl+s", platform=Platform.LINUX).command_id == "a.other"
    keybindings.clear_user_bindings()
    resolved = keybindings.resolve("ctrl+s", platform=Platform.LINUX)
    assert resolved.command_id == "a.save"
    assert resolved.layer == BindingLayer.EXTENSION_DEFAULT


def test_removed_extension_command_resolution_and_execution(tmp_path):
    from editor_command_system import CommandSystem

    system = CommandSystem(str(tmp_path / "state.json"))
    system.register(Command(
        "ext.ping", "Ping", lambda: "pong", source="ext-x", extension_id="ext-x"
    ))
    system.keybindings.add_default(KeyBinding(
        "ext.ping", "ctrl+p", source="ext-x"
    ))
    assert system.keybindings.resolve("ctrl+p", platform=Platform.LINUX).command_id == "ext.ping"
    # 停用：绑定立即不可解析
    system.registry.deactivate_extension("ext-x")
    assert system.keybindings.resolve("ctrl+p", platform=Platform.LINUX) is None
    # 恢复：绑定重新可用
    system.registry.activate_extension("ext-x")
    assert system.keybindings.resolve("ctrl+p", platform=Platform.LINUX).command_id == "ext.ping"
    # 移除：命令与默认绑定一起消失，执行被“命令不存在”拒绝
    system.registry.remove_extension("ext-x")
    assert system.registry.get_if_active("ext.ping") is None
    assert system.keybindings.resolve("ctrl+p", platform=Platform.LINUX) is None
    result = system.execute("ext.ping")
    assert not result.success
    assert result.error_code == "command_not_found"
    system.shutdown()
