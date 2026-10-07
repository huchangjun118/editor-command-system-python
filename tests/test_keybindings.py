import pytest

from command_system import (
    KeybindingError,
    KeybindingResolver,
    KeybindingRule,
    KeyChord,
    KeySequence,
    Layer,
    Platform,
    Reason,
)
from command_system.keybindings import KeybindingConflict


def rule(seq, cmd, layer, **kw):
    return KeybindingRule(sequence=KeySequence.parse(seq), command_id=cmd, layer=layer, **kw)


RESOLVER = KeybindingResolver(Platform.LINUX)


def test_chord_parse_normalizes_modifiers():
    a = KeyChord.parse("Ctrl+Shift+P")
    b = KeyChord.parse("shift+ctrl+p")
    assert a == b
    assert a.modifiers == frozenset({"ctrl", "shift"})
    assert a.key == "p"


def test_chord_parse_rejects_invalid():
    with pytest.raises(KeybindingError) as e1:
        KeyChord.parse("ctrl+")
    with pytest.raises(KeybindingError) as e2:
        KeyChord.parse("ctrl+shift")  # 主键是修饰符
    with pytest.raises(KeybindingError) as e3:
        KeyChord.parse("hyper+x")     # 未知修饰符
    for e in (e1, e2, e3):
        assert e.value.reason is Reason.INVALID_KEYBINDING


def test_multi_chord_sequence():
    seq = KeySequence.parse("ctrl+k ctrl+s")
    assert len(seq.chords) == 2
    assert seq.chords[0] == KeyChord.parse("ctrl+k")
    assert KeySequence.parse("ctrl+k   ctrl+s") == seq  # 空白容错


def test_user_override_wins_and_layer_is_reported():
    rules = [
        rule("ctrl+s", "file.save", Layer.BUILTIN),
        rule("ctrl+s", "file.saveAll", Layer.USER),
    ]
    resolved = RESOLVER.resolve(rules)
    by_cmd = {b.command_id: b for b in resolved}
    assert by_cmd["file.save"].shadowed is True
    assert by_cmd["file.saveAll"].shadowed is False
    assert by_cmd["file.saveAll"].layer is Layer.USER
    assert RESOLVER.lookup(rules, KeySequence.parse("ctrl+s")).command_id == "file.saveAll"


def test_user_remove_unbinds_lower_layer():
    rules = [
        rule("ctrl+s", "file.save", Layer.BUILTIN),
        rule("ctrl+s", "file.save", Layer.USER, remove=True),
    ]
    assert RESOLVER.lookup(rules, KeySequence.parse("ctrl+s")) is None


def test_extension_default_beats_builtin_but_loses_to_user():
    rules = [
        rule("ctrl+p", "nav.quickOpen", Layer.BUILTIN),
        rule("ctrl+p", "ext.palette", Layer.EXTENSION),
        rule("ctrl+p", "my.palette", Layer.USER),
    ]
    hit = RESOLVER.lookup(rules, KeySequence.parse("ctrl+p"))
    assert hit.command_id == "my.palette" and hit.layer is Layer.USER


def test_platform_specific_rules():
    rules = [
        rule("ctrl+q", "app.quit", Layer.BUILTIN, platform=Platform.LINUX),
        rule("meta+q", "app.quit", Layer.BUILTIN, platform=Platform.MACOS),
    ]
    linux = KeybindingResolver(Platform.LINUX)
    mac = KeybindingResolver(Platform.MACOS)
    assert linux.lookup(rules, KeySequence.parse("ctrl+q")) is not None
    assert linux.lookup(rules, KeySequence.parse("meta+q")) is None
    assert mac.lookup(rules, KeySequence.parse("meta+q")) is not None
    # 全平台规则两边都生效
    rules.append(rule("f5", "app.refresh", Layer.BUILTIN))
    assert linux.lookup(rules, KeySequence.parse("f5")) is not None
    assert mac.lookup(rules, KeySequence.parse("f5")) is not None


def test_same_layer_conflict_detected_and_distinguishable():
    rules = [
        rule("ctrl+t", "a.one", Layer.USER),
        rule("ctrl+t", "a.two", Layer.USER),
    ]
    conflicts = RESOLVER.conflicts(rules)
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], KeybindingConflict)
    assert set(conflicts[0].command_ids) == {"a.one", "a.two"}
    with pytest.raises(KeybindingError) as exc:
        RESOLVER.assert_no_conflicts(rules)
    assert exc.value.reason is Reason.KEYBINDING_CONFLICT
    assert exc.value.detail["layer"] == "user"


def test_cross_layer_same_sequence_is_override_not_conflict():
    rules = [
        rule("ctrl+t", "a.one", Layer.BUILTIN),
        rule("ctrl+t", "a.two", Layer.USER),
    ]
    assert RESOLVER.conflicts(rules) == []


def test_different_sequences_no_conflict():
    rules = [
        rule("ctrl+a", "x", Layer.USER),
        rule("ctrl+b", "y", Layer.USER),
    ]
    assert RESOLVER.conflicts(rules) == []
