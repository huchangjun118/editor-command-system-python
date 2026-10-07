"""快捷键解析与用户覆盖。

分层规则（优先级从高到低）：

1. ``user``：用户覆盖，始终优先于扩展默认值；
2. ``extension_default``：内置/扩展声明的默认绑定。

其他规则：

* 绑定按平台区分：``Platform.ANY`` 适用于所有平台，
  当前平台的专属绑定优先于 ``ANY``；
* 支持多段组合键（chord），如 ``"ctrl+k ctrl+s"``，段间以空格分隔；
* 同一层、同一平台、同一 ``when`` 上下文成立时，多个命令绑定到同一按键
  即为冲突，:meth:`detect_conflicts` 会检出并给出涉及的全部命令；
* :class:`ResolvedBinding` 会记录最终命中的绑定来自哪一层、哪个来源，
  以及被它覆盖掉的低优先级绑定，便于在终端里向用户解释。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum

from .context import ContextSnapshot, ContextStore
from .errors import InvalidKeybindingError


class BindingLayer(str, Enum):
    EXTENSION_DEFAULT = "extension_default"
    USER = "user"


class Platform(str, Enum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"
    ANY = "any"


_MODIFIERS = {"ctrl", "shift", "alt", "meta", "cmd", "super", "win"}
_NORMALIZED_MODIFIERS = {
    "control": "ctrl",
    "ctl": "ctrl",
    "cmd": "meta",
    "super": "meta",
    "win": "meta",
}


def normalize_chord(chord: str) -> str:
    """把组合键规范化，如 ``"Ctrl+K  Ctrl+S"`` -> ``"ctrl+k ctrl+s"``。"""
    if not isinstance(chord, str) or not chord.strip():
        raise InvalidKeybindingError("快捷键不能为空")
    parts: list[str] = []
    for raw_part in chord.split():
        mods: list[str] = []
        key = ""
        for token in raw_part.split("+"):
            t = token.strip().lower()
            if not t:
                raise InvalidKeybindingError(f"非法快捷键片段: {raw_part!r}")
            t = _NORMALIZED_MODIFIERS.get(t, t)
            if t in _MODIFIERS:
                mods.append(t)
            else:
                if key:
                    raise InvalidKeybindingError(f"快捷键片段含多个主键: {raw_part!r}")
                key = t
        if not key:
            raise InvalidKeybindingError(f"快捷键片段缺少主键: {raw_part!r}")
        if len(key) == 1:
            key = key.lower()
        # 修饰键去重并按固定顺序排列，保证可复现
        mods = sorted(set(mods))
        parts.append("+".join([*mods, key]))
    return " ".join(parts)


@dataclass
class KeyBinding:
    command_id: str
    chord: str
    layer: BindingLayer = BindingLayer.EXTENSION_DEFAULT
    platform: Platform = Platform.ANY
    when: str | None = None
    source: str = "builtin"

    def __post_init__(self) -> None:
        self.chord = normalize_chord(self.chord)


@dataclass
class ResolvedBinding:
    chord: str
    command_id: str
    layer: BindingLayer
    source: str
    platform: Platform
    when: str | None
    overridden: list[KeyBinding] = field(default_factory=list)

    def describe_origin(self) -> str:
        layer_text = {
            BindingLayer.USER: "用户覆盖",
            BindingLayer.EXTENSION_DEFAULT: "扩展默认值",
        }[self.layer]
        return f"{self.chord} -> {self.command_id}（{layer_text}，来源 {self.source}）"


@dataclass
class Conflict:
    chord: str
    command_ids: list[str]
    layer: BindingLayer
    platform: Platform
    when: str | None

    def message(self) -> str:
        return (
            f"快捷键 {self.chord!r} 在 {self.layer.value} 层/"
            f"{self.platform.value} 平台上冲突: {', '.join(self.command_ids)}"
        )


class KeybindingRegistry:
    def __init__(self, context: ContextStore | None = None) -> None:
        self._bindings: list[KeyBinding] = []
        self._context = context
        self._inactive_sources: set[str] = set()
        self._lock = threading.RLock()

    # -- 贡献绑定 ----------------------------------------------------------
    def add_default(self, binding: KeyBinding) -> None:
        if binding.layer != BindingLayer.EXTENSION_DEFAULT:
            raise InvalidKeybindingError("add_default 只接受扩展默认层绑定")
        with self._lock:
            self._bindings.append(binding)

    def set_user_binding(
        self,
        chord: str,
        command_id: str,
        platform: Platform = Platform.ANY,
        when: str | None = None,
    ) -> None:
        normalized = normalize_chord(chord)
        with self._lock:
            # 用户层同一 (chord, 平台, when) 只保留最新一条，即“用户覆盖”
            self._bindings = [
                b
                for b in self._bindings
                if not (
                    b.layer == BindingLayer.USER
                    and b.chord == normalized
                    and b.platform == platform
                    and (b.when or "") == (when or "")
                )
            ]
            self._bindings.append(
                KeyBinding(
                    command_id=command_id,
                    chord=normalized,
                    layer=BindingLayer.USER,
                    platform=platform,
                    when=when,
                    source="user",
                )
            )

    def clear_user_bindings(self) -> None:
        with self._lock:
            self._bindings = [b for b in self._bindings if b.layer != BindingLayer.USER]

    def remove_source(self, source: str) -> int:
        """移除某来源（通常为被卸载扩展）贡献的全部默认绑定。

        用户覆盖属于 ``user`` 来源，不会被此操作删除。
        """
        with self._lock:
            kept = [
                b
                for b in self._bindings
                if not (b.source == source and b.layer == BindingLayer.EXTENSION_DEFAULT)
            ]
            removed = len(self._bindings) - len(kept)
            self._bindings = kept
            self._inactive_sources.discard(source)
            return removed

    def set_source_active(self, source: str, active: bool) -> None:
        with self._lock:
            if active:
                self._inactive_sources.discard(source)
            else:
                self._inactive_sources.add(source)

    def all_bindings(self) -> list[KeyBinding]:
        with self._lock:
            return list(self._bindings)

    # -- 解析 --------------------------------------------------------------
    def _platform_matches(self, binding: KeyBinding, platform: Platform) -> bool:
        return binding.platform == Platform.ANY or binding.platform == platform

    def _when_matches(
        self, binding: KeyBinding, snapshot: ContextSnapshot | None
    ) -> bool:
        if binding.when is None:
            return True
        if self._context is None:
            return False
        return self._context.evaluate(binding.when, snapshot)

    def _candidates(
        self, chord: str, platform: Platform, snapshot: ContextSnapshot | None
    ) -> list[KeyBinding]:
        normalized = normalize_chord(chord)
        out: list[KeyBinding] = []
        with self._lock:
            for b in self._bindings:
                if (
                    b.chord == normalized
                    and b.source not in self._inactive_sources
                    and self._platform_matches(b, platform)
                    and self._when_matches(b, snapshot)
                ):
                    out.append(b)
        return out

    def resolve(
        self,
        chord: str,
        *,
        platform: Platform,
        snapshot: ContextSnapshot | None = None,
    ) -> ResolvedBinding | None:
        """返回优先级最高的绑定；同层同优先级出现多条时抛出冲突。"""
        if snapshot is None and self._context is not None:
            snapshot = self._context.snapshot()
        candidates = self._candidates(chord, platform, snapshot)
        if not candidates:
            return None

        def sort_key(b: KeyBinding) -> tuple[int, int]:
            # 用户层优先；平台专属优先于 ANY
            layer_rank = 1 if b.layer == BindingLayer.USER else 0
            platform_rank = 0 if b.platform == Platform.ANY else 1
            return (layer_rank, platform_rank)

        ranked = sorted(candidates, key=sort_key, reverse=True)
        best = ranked[0]
        tied = [
            b
            for b in ranked
            if sort_key(b) == sort_key(best) and b.command_id != best.command_id
        ]
        overridden = [b for b in ranked if b is not best]
        if tied:
            from .errors import KeybindingConflictError

            raise KeybindingConflictError(
                best.chord, sorted({best.command_id, *(b.command_id for b in tied)})
            )
        return ResolvedBinding(
            chord=best.chord,
            command_id=best.command_id,
            layer=best.layer,
            source=best.source,
            platform=best.platform,
            when=best.when,
            overridden=overridden,
        )

    def bindings_for_command(self, command_id: str) -> list[KeyBinding]:
        with self._lock:
            return [b for b in self._bindings if b.command_id == command_id]

    # -- 冲突检测 ----------------------------------------------------------
    def detect_conflicts(
        self, *, snapshot: ContextSnapshot | None = None
    ) -> list[Conflict]:
        """检测所有“同层/同平台键/同 when 成立”下指向不同命令的冲突。"""
        if snapshot is None and self._context is not None:
            snapshot = self._context.snapshot()
        groups: dict[tuple[str, BindingLayer, Platform, str], list[KeyBinding]] = {}
        with self._lock:
            bindings = list(self._bindings)
        for b in bindings:
            if not self._when_matches(b, snapshot):
                continue
            key = (b.chord, b.layer, b.platform, b.when or "")
            groups.setdefault(key, []).append(b)
        conflicts: list[Conflict] = []
        for (chord, layer, platform, when), items in groups.items():
            command_ids = sorted({b.command_id for b in items})
            if len(command_ids) > 1:
                conflicts.append(
                    Conflict(
                        chord=chord,
                        command_ids=command_ids,
                        layer=layer,
                        platform=platform,
                        when=when or None,
                    )
                )
        conflicts.sort(key=lambda c: (c.chord, c.layer.value, c.platform.value))
        return conflicts
