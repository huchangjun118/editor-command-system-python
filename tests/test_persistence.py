"""需求 7：重启后用户覆盖与历史状态可区分且不丢失。"""
from __future__ import annotations

from editor_command_system import CommandSystem, Command, Platform, BindingLayer


def test_user_binding_survives_restart(tmp_path):
    path = str(tmp_path / "state.json")
    system = CommandSystem(path)
    system.register(Command("a.save", "Save", lambda: None))
    system.set_user_binding("ctrl+s", "a.save", Platform.LINUX)
    system.shutdown()

    reloaded = CommandSystem(path)
    resolved = reloaded.keybindings.resolve("ctrl+s", platform=Platform.LINUX)
    assert resolved is not None
    assert resolved.command_id == "a.save"
    assert resolved.layer == BindingLayer.USER
    reloaded.shutdown()


def test_history_and_bindings_are_distinct_partitions(tmp_path):
    import json
    path = str(tmp_path / "state.json")
    system = CommandSystem(path)
    system.register(Command("a.edit", "Edit", lambda: "v",
                            undo_handler=lambda r, a: None))
    system.set_user_binding("ctrl+e", "a.edit")
    assert system.execute("a.edit").success
    system.shutdown()

    raw = json.load(open(path, encoding="utf-8"))
    assert raw["user_bindings"][0]["chord"] == "ctrl+e"
    assert raw["history"][0]["command_id"] == "a.edit"
    # 两个分区互不重叠
    assert "command_id" in raw["user_bindings"][0]
    assert "chord" not in raw["history"][0]


def test_restored_history_is_traceable_but_not_undoable(tmp_path):
    path = str(tmp_path / "state.json")
    system = CommandSystem(path)
    system.register(Command("a.edit", "Edit", lambda: "v",
                            undo_handler=lambda r, a: None))
    system.execute("a.edit")
    system.save()

    reloaded = CommandSystem(path)
    # 历史元数据可追溯
    restored = reloaded.restored_history()
    assert restored and restored[0]["command_id"] == "a.edit"
    # 但内存撤销栈为空：重启后撤销处理器无法恢复，不参与撤销
    assert len(reloaded.history) == 0
    assert reloaded.executor.undo_last() is False
    reloaded.shutdown()
