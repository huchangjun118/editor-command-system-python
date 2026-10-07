"""命令注册表。

内置命令与扩展贡献的命令共用同一份注册表：

* 标识（``id``）重复的注册请求一律拒绝，抛出
  :class:`~editor_command_system.errors.CommandAlreadyExistsError`，
  错误中携带先注册者来源，便于定位冲突方；
* 扩展被 :meth:`deactivate_extension` 停用后，其命令立即从可见集合消失，
  :meth:`get` 视为不存在；被 :meth:`remove_extension` 移除后彻底删除；
* 停用/移除只影响该扩展贡献的命令，其他命令不受影响。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .context import ContextStore
from .errors import (
    CommandAlreadyExistsError,
    CommandNotFoundError,
)

ExtensionListener = Callable[[str, str], None]


@dataclass
class CommandParameter:
    name: str
    type: str = "string"  # string|int|float|bool|json
    required: bool = False
    default: Any = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in {"string", "int", "float", "bool", "json"}:
            raise ValueError(f"不支持的参数类型: {self.type!r}")


@dataclass
class Command:
    id: str
    title: str
    handler: Callable[..., Any]
    source: str = "builtin"
    extension_id: str | None = None
    category: str = ""
    parameters: list[CommandParameter] = field(default_factory=list)
    when: str | None = None          # 可见性条件
    enablement: str | None = None    # 可用性条件
    required_permission: str | None = None
    undo_handler: Callable[..., Any] | None = None


@dataclass
class _Record:
    command: Command
    active: bool = True


class CommandRegistry:
    def __init__(self, context: ContextStore | None = None) -> None:
        self._commands: dict[str, _Record] = {}
        self._extensions: dict[str, set[str]] = {}
        self._context = context
        self._lock = threading.RLock()
        self._listeners: list[ExtensionListener] = []

    def add_extension_listener(self, listener: ExtensionListener) -> None:
        """注册回调；事件类型为 ``deactivated``/``activated``/``removed``。"""
        self._listeners.append(listener)

    # -- 注册 / 注销 -------------------------------------------------------
    def register(self, command: Command) -> None:
        with self._lock:
            existing = self._commands.get(command.id)
            if existing is not None:
                raise CommandAlreadyExistsError(
                    command.id, existing.command.source
                )
            self._commands[command.id] = _Record(command=command, active=True)
            if command.extension_id:
                self._extensions.setdefault(command.extension_id, set()).add(command.id)

    def unregister(self, command_id: str) -> None:
        with self._lock:
            record = self._commands.pop(command_id, None)
            if record is None:
                raise CommandNotFoundError(command_id)
            if record.command.extension_id:
                ids = self._extensions.get(record.command.extension_id)
                if ids is not None:
                    ids.discard(command_id)

    def deactivate_extension(self, extension_id: str) -> list[str]:
        """停用扩展：其命令立即失效，返回被停用的命令 id 列表。"""
        with self._lock:
            ids = self._extensions.get(extension_id, set())
            affected: list[str] = []
            for cid in ids:
                record = self._commands.get(cid)
                if record is not None and record.active:
                    record.active = False
                    affected.append(cid)
            if affected:
                self._emit(extension_id, "deactivated")
            return sorted(affected)

    def activate_extension(self, extension_id: str) -> None:
        changed = False
        with self._lock:
            for cid in self._extensions.get(extension_id, set()):
                record = self._commands.get(cid)
                if record is not None:
                    record.active = True
                    changed = True
        if changed:
            self._emit(extension_id, "activated")

    def remove_extension(self, extension_id: str) -> list[str]:
        """彻底移除扩展贡献的全部命令。"""
        with self._lock:
            ids = list(self._extensions.pop(extension_id, set()))
            for cid in ids:
                self._commands.pop(cid, None)
        if ids:
            self._emit(extension_id, "removed")
        return sorted(ids)

    def _emit(self, extension_id: str, event: str) -> None:
        for listener in list(self._listeners):
            listener(extension_id, event)

    def is_extension_active(self, extension_id: str) -> bool:
        with self._lock:
            ids = self._extensions.get(extension_id)
            if not ids:
                return False
            return all(
                (rec := self._commands.get(cid)) is not None and rec.active
                for cid in ids
            )

    # -- 查询 --------------------------------------------------------------
    def get(self, command_id: str) -> Command:
        with self._lock:
            record = self._commands.get(command_id)
            if record is None or not record.active:
                raise CommandNotFoundError(command_id)
            return record.command

    def get_if_active(self, command_id: str) -> Command | None:
        with self._lock:
            record = self._commands.get(command_id)
            if record is None or not record.active:
                return None
            return record.command

    def list_commands(self, include_invisible: bool = False) -> list[Command]:
        """列出命令。

        默认按当前上下文的 ``when`` 可见性条件过滤；
        ``include_invisible=True`` 时返回全部（含停用扩展之外的所有活动命令）。
        """
        with self._lock:
            records = [r for r in self._commands.values() if r.active]
        result: list[Command] = []
        for record in records:
            cmd = record.command
            if include_invisible or self._context is None:
                result.append(cmd)
                continue
            visible, _ = self._context.check(cmd.when)
            if visible:
                result.append(cmd)
        return sorted(result, key=lambda c: c.id)
