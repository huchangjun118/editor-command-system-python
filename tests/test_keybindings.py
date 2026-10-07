"""需求 3：分层覆盖、多段组合键、平台区分、冲突检测、来源可解释。"""
from __future__ import annotations

import pytest

from editor_command_system.errors import (
    InvalidKeybindingError,
    KeybindingConflictError,
)
from editor_command_system.keybindings import (
    BindingLayer,
    KeyBinding,
    Platform,
    normalize_chord,
)


def test_normalize_chord():
    assert normalize_chord("Ctrl+K  Ctrl+S") == "ctrl+k ctrl+s"
    assert normalize_chord("CMD+C") == "meta+c"
    with pytest.raises(InvalidKeybindingError):
        normalize_chord("")
    with pytest.raises(InvalidKeybindingError):
        normalize_chord("ctrl+")


def test_chord_binding_resolves(keybindings):
    keybindings.add_default(KeyBinding("a.chord", "ctrl+k ctrl+s", source="builtin"))
    resolved = keybindings.resolve("Ctrl+K Ctrl+S", platform=Platform.LINUX)
    assert resolved is not None
    assert resolved.command_id == "a.chord"
    assert resolved.layer == BindingLayer.EXTENSION_DEFAULT
    assert resolved.source == "builtin"


def test_platform_specific_overrides_any(keybindings):
    keybindings.add_default(KeyBinding("a.save", "ctrl+s", source="builtin"))
    keybindings.add_default(
        KeyBinding("a.saveMac", "ctrl+s", platform=Platform.MACOS, source="ext")
    )
    assert keybindings.resolve("ctrl+s", platform=Platform.LINUX).command_id == "a.save"
    assert keybindings.resolve("ctrl+s", platform=Platform.MACOS).command_id == "a.saveMac"


def test_user_binding_overrides_default(keybindings):
    keybindings.add_default(KeyBinding("a.save", "ctrl+s", source="builtin"))
    keybindings.set_user_binding("ctrl+s", "a.format")
    resolved = keybindings.resolve("ctrl+s", platform=Platform.LINUX)
    assert resolved.command_id == "a.format"
    assert resolved.layer == BindingLayer.USER
    # 被覆盖的默认绑定保留在解释信息中
    assert any(b.command_id == "a.save" for b in resolved.overridden)
    assert "用户覆盖" in resolved.describe_origin()


def test_user_binding_is_rewritten_not_duplicated(keybindings):
    keybindings.set_user_binding("ctrl+s", "a.one")
    keybindings.set_user_binding("ctrl+s", "a.two")
    resolved = keybindings.resolve("ctrl+s", platform=Platform.LINUX)
    assert resolved.command_id == "a.two"
    user_bindings = [b for b in keybindings.all_bindings()
                     if b.layer == BindingLayer.USER]
    assert len(user_bindings) == 1


def test_conflict_is_detected_with_distinguishable_commands(keybindings):
    keybindings.add_default(KeyBinding("a.x", "ctrl+x", source="ext1"))
    keybindings.add_default(KeyBinding("a.y", "ctrl+x", source="ext2"))
    with pytest.raises(KeybindingConflictError) as exc:
        keybindings.resolve("ctrl+x", platform=Platform.LINUX)
    assert exc.value.code == "keybinding_conflict"
    assert set(exc.value.command_ids) == {"a.x", "a.y"}
    assert exc.value.chord == "ctrl+x"
    conflicts = keybindings.detect_conflicts()
    assert len(conflicts) == 1
    assert "a.x" in conflicts[0].message() and "a.y" in conflicts[0].message()


def test_when_guarded_bindings_do_not_conflict_when_inactive(context, keybindings):
    keybindings.add_default(
        KeyBinding("a.x", "ctrl+e", source="ext1", when="editorFocused")
    )
    keybindings.add_default(
        KeyBinding("a.y", "ctrl+e", source="ext2", when="!editorFocused")
    )
    # editorFocused=False：只有 a.y 生效，无冲突
    resolved = keybindings.resolve("ctrl+e", platform=Platform.LINUX)
    assert resolved.command_id == "a.y"
    context.set("editorFocused", True)
    resolved = keybindings.resolve("ctrl+e", platform=Platform.LINUX)
    assert resolved.command_id == "a.x"


def test_conflicting_when_guarded_bindings_detected_when_both_active(keybindings):
    keybindings.add_default(KeyBinding("a.x", "ctrl+e", when="editorFocused"))
    keybindings.add_default(KeyBinding("a.y", "ctrl+e", when="editorFocused"))
    from editor_command_system.context import ContextKey
    keybindings._context.define_key(ContextKey("editorFocused", False))
    keybindings._context.set("editorFocused", True)
    conflicts = keybindings.detect_conflicts()
    assert any(c.chord == "ctrl+e" for c in conflicts)
