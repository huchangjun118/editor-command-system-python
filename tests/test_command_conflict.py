"""需求 1：命令注册、重复拒绝、扩展停用/移除。"""
from __future__ import annotations

import pytest

from editor_command_system.errors import (
    CommandAlreadyExistsError,
    CommandNotFoundError,
)
from editor_command_system.registry import Command


def _cmd(cid, source="builtin", ext=None):
    return Command(id=cid, title=cid, handler=lambda: None,
                   source=source, extension_id=ext)


def test_duplicate_command_id_is_rejected(registry):
    registry.register(_cmd("x.save"))
    with pytest.raises(CommandAlreadyExistsError) as exc:
        registry.register(_cmd("x.save", source="ext-b", ext="ext-b"))
    assert exc.value.code == "command_already_exists"
    assert exc.value.command_id == "x.save"
    # 原因可区分：错误中携带先注册者来源
    assert exc.value.existing_source == "builtin"


def test_duplicate_from_two_extensions(registry):
    registry.register(_cmd("shared.cmd", source="ext-a", ext="ext-a"))
    with pytest.raises(CommandAlreadyExistsError) as exc:
        registry.register(_cmd("shared.cmd", source="ext-b", ext="ext-b"))
    assert exc.value.existing_source == "ext-a"


def test_deactivated_extension_commands_immediately_invalid(registry):
    registry.register(_cmd("ext.a", "ext-a", "ext-a"))
    registry.register(_cmd("builtin.b"))
    registry.deactivate_extension("ext-a")
    with pytest.raises(CommandNotFoundError):
        registry.get("ext.a")
    # 其他命令不受影响
    assert registry.get("builtin.b").id == "builtin.b"
    # 列表中也不再出现
    assert all(c.id != "ext.a" for c in registry.list_commands())


def test_reactivate_extension(registry):
    registry.register(_cmd("ext.a", "ext-a", "ext-a"))
    registry.deactivate_extension("ext-a")
    registry.activate_extension("ext-a")
    assert registry.get("ext.a").id == "ext.a"


def test_remove_extension_deletes_commands(registry):
    registry.register(_cmd("ext.a", "ext-a", "ext-a"))
    registry.register(_cmd("ext.a2", "ext-a", "ext-a"))
    removed = registry.remove_extension("ext-a")
    assert set(removed) == {"ext.a", "ext.a2"}
    registry.activate_extension("ext-a")  # 不应有任何作用
    with pytest.raises(CommandNotFoundError):
        registry.get("ext.a")


def test_deactivating_one_extension_keeps_others(registry):
    registry.register(_cmd("a.one", "ext-a", "ext-a"))
    registry.register(_cmd("b.one", "ext-b", "ext-b"))
    registry.deactivate_extension("ext-a")
    with pytest.raises(CommandNotFoundError):
        registry.get("a.one")
    assert registry.get("b.one").id == "b.one"
