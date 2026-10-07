"""快捷键解析、分层覆盖与冲突检测。

层级（优先级从低到高）：内置默认 < 扩展默认 < 用户覆盖。
- 用户层可用 remove=True 的规则解除低层对同一命令/同一序列的绑定。
- 平台专属规则只在对应平台生效；全平台规则（platform=None）总是生效。
- 同一层内、同一按键序列绑定到多个不同命令即冲突，
  通过 ``conflicts`` 检出，reason 为 KEYBINDING_CONFLICT。
- 每条解析结果都携带 ``layer``，说明该绑定来自哪一层；
  被更高层覆盖的绑定标记 ``shadowed=True``。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .errors import KeybindingError, Reason


class Platform(enum.Enum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"


class Layer(enum.Enum):
    BUILTIN = "builtin"
    EXTENSION = "extension"
    USER = "user"


_LAYER_ORDER = {Layer.BUILTIN: 0, Layer.EXTENSION: 1, Layer.USER: 2}

_MODIFIERS = {"ctrl", "shift", "alt", "meta", "cmd", "win"}
# 平台修饰符别名归一化
_MODIFIER_ALIASES = {"cmd": "meta", "win": "meta"}


@dataclass(frozen=True)
class KeyChord:
    """单段按键，如 ctrl+shift+p。修饰符排序后存储，保证相等性稳定。"""

    modifiers: frozenset[str]
    key: str

    @staticmethod
    def parse(text: str) -> "KeyChord":
        parts = [p.strip().lower() for p in text.split("+") if p.strip()]
        if not parts:
            raise KeybindingError(
                Reason.INVALID_KEYBINDING,
                f"按键为空: {text!r}",
                detail={"text": text},
            )
        key = parts[-1]
        modifiers = parts[:-1]
        if key in _MODIFIERS:
            raise KeybindingError(
                Reason.INVALID_KEYBINDING,
                f"主键不能是修饰符: {text!r}",
                detail={"text": text},
            )
        norm: set[str] = set()
        for m in modifiers:
            if m not in _MODIFIERS:
                raise KeybindingError(
                    Reason.INVALID_KEYBINDING,
                    f"未知修饰符 {m!r}: {text!r}",
                    detail={"text": text, "modifier": m},
                )
            norm.add(_MODIFIER_ALIASES.get(m, m))
        return KeyChord(frozenset(norm), key)

    def __str__(self) -> str:
        mods = "+".join(sorted(self.modifiers))
        return f"{mods}+{self.key}" if mods else self.key


@dataclass(frozen=True)
class KeySequence:
    """多段组合键，如 "ctrl+k ctrl+s"。"""

    chords: tuple[KeyChord, ...]

    @staticmethod
    def parse(text: str) -> "KeySequence":
        segments = [seg.strip() for seg in text.split(" ") if seg.strip()]
        if not segments:
            raise KeybindingError(
                Reason.INVALID_KEYBINDING,
                f"按键序列为空: {text!r}",
                detail={"text": text},
            )
        return KeySequence(tuple(KeyChord.parse(seg) for seg in segments))

    def __str__(self) -> str:
        return " ".join(str(c) for c in self.chords)


@dataclass(frozen=True)
class KeybindingRule:
    sequence: KeySequence
    command_id: str
    layer: Layer
    when: str | None = None
    platform: Platform | None = None   # None 表示全平台
    extension_id: str | None = None
    remove: bool = False               # 用户层可用 remove 解除低层绑定


@dataclass(frozen=True)
class ResolvedKeybinding:
    sequence: KeySequence
    command_id: str
    layer: Layer                       # 该绑定来自哪一层
    shadowed: bool                     # 是否被更高层覆盖


@dataclass(frozen=True)
class KeybindingConflict:
    sequence: KeySequence
    command_ids: tuple[str, ...]
    layer: Layer


class KeybindingResolver:
    """汇总三层规则，产出最终绑定表并检出冲突。"""

    def __init__(self, platform: Platform):
        self.platform = platform

    def _applicable(self, rules: list[KeybindingRule]) -> list[KeybindingRule]:
        return [r for r in rules if r.platform is None or r.platform is self.platform]

    def resolve(self, rules: list[KeybindingRule]) -> list[ResolvedKeybinding]:
        """产出最终绑定表。

        处理顺序：按层从低到高；用户层 remove 规则删除低层中
        同序列同命令的绑定；高层同序列绑定使低层绑定标记为 shadowed。
        同层冲突的绑定全部保留在结果中（由 conflicts() 另行检出）。
        """
        applicable = self._applicable(rules)
        removals = [r for r in applicable if r.remove]
        bindings = [r for r in applicable if not r.remove]

        # 生效表：(sequence, command_id) -> 最高层规则
        effective: dict[tuple[KeySequence, str], KeybindingRule] = {}
        for r in sorted(bindings, key=lambda r: _LAYER_ORDER[r.layer]):
            effective[(r.sequence, r.command_id)] = r
        for rm in removals:
            for key in [k for k in effective if k[0] == rm.sequence]:
                if _LAYER_ORDER[effective[key].layer] < _LAYER_ORDER[rm.layer]:
                    if rm.command_id in ("*", effective[key].command_id):
                        del effective[key]

        # 每个序列的最高层，用于标记 shadowed
        top_layer: dict[KeySequence, Layer] = {}
        for (seq, _cid), r in effective.items():
            if seq not in top_layer or _LAYER_ORDER[r.layer] > _LAYER_ORDER[top_layer[seq]]:
                top_layer[seq] = r.layer

        result = [
            ResolvedKeybinding(
                sequence=seq,
                command_id=cid,
                layer=r.layer,
                shadowed=r.layer is not top_layer[seq],
            )
            for (seq, cid), r in effective.items()
        ]
        result.sort(key=lambda b: (str(b.sequence), _LAYER_ORDER[b.layer], b.command_id))
        return result

    def conflicts(self, rules: list[KeybindingRule]) -> list[KeybindingConflict]:
        """检出同层、同序列绑定到多个不同命令的冲突。"""
        resolved = [b for b in self.resolve(rules) if not b.shadowed]
        by_key: dict[tuple[KeySequence, Layer], set[str]] = {}
        for b in resolved:
            by_key.setdefault((b.sequence, b.layer), set()).add(b.command_id)
        return [
            KeybindingConflict(sequence=seq, command_ids=tuple(sorted(cids)), layer=layer)
            for (seq, layer), cids in sorted(by_key.items(), key=lambda kv: str(kv[0][0]))
            if len(cids) > 1
        ]

    def assert_no_conflicts(self, rules: list[KeybindingRule]) -> None:
        """存在冲突时抛出可区分错误。"""
        found = self.conflicts(rules)
        if found:
            c = found[0]
            raise KeybindingError(
                Reason.KEYBINDING_CONFLICT,
                f"快捷键冲突: {c.sequence} 在 {c.layer.value} 层同时绑定到 "
                f"{', '.join(c.command_ids)}",
                detail={
                    "sequence": str(c.sequence),
                    "layer": c.layer.value,
                    "command_ids": list(c.command_ids),
                },
            )

    def lookup(
        self, rules: list[KeybindingRule], sequence: KeySequence
    ) -> ResolvedKeybinding | None:
        """按键序列查找最终生效的绑定（取最高层、未被遮蔽者）。"""
        candidates = [
            b for b in self.resolve(rules) if b.sequence == sequence and not b.shadowed
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda b: _LAYER_ORDER[b.layer])
