"""命令注册表：内置命令与扩展命令共用同一份注册表。

规则：
- 命令 ID 全局唯一，重复注册（无论来自内置还是扩展）一律被拒绝，
  错误 reason 为 DUPLICATE_COMMAND_ID，并携带冲突双方来源信息。
- 扩展命令按批原子注册：同一批中任一命令冲突，整批不生效。
- 扩展停用/移除时其命令立即从注册表删除，其他命令不受影响。
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import Reason, RegistrationError


class SourceKind(enum.Enum):
    BUILTIN = "builtin"
    EXTENSION = "extension"


@dataclass(frozen=True)
class ArgumentSpec:
    """单个参数的声明：名称、类型、是否必填、默认值、可选枚举值。"""

    name: str
    type: type = str
    required: bool = True
    default: Any = None
    choices: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class CommandDescriptor:
    id: str
    title: str
    handler: Callable[..., Any]
    source: SourceKind
    extension_id: str | None = None
    when: str | None = None            # 可见性条件
    enablement: str | None = None      # 可用性条件
    args: tuple[ArgumentSpec, ...] = ()
    permission: str | None = None      # 需要的权限，None 表示公开
    undoable: bool = False
    undo_handler: Callable[[Any], None] | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source is SourceKind.EXTENSION and not self.extension_id:
            raise RegistrationError(
                Reason.UNKNOWN_EXTENSION,
                f"扩展命令 {self.id!r} 缺少 extension_id",
            )
        if self.source is SourceKind.BUILTIN and self.extension_id is not None:
            raise RegistrationError(
                Reason.UNKNOWN_EXTENSION,
                f"内置命令 {self.id!r} 不应携带 extension_id",
            )


class CommandRegistry:
    """线程安全的命令注册表。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._commands: dict[str, CommandDescriptor] = {}
        self._by_extension: dict[str, set[str]] = {}

    def _check_absent(self, descriptor: CommandDescriptor) -> None:
        existing = self._commands.get(descriptor.id)
        if existing is not None:
            raise RegistrationError(
                Reason.DUPLICATE_COMMAND_ID,
                f"命令 ID 重复: {descriptor.id!r}"
                f"（已注册来源={existing.source.value}"
                f"{':' + existing.extension_id if existing.extension_id else ''}，"
                f"新来源={descriptor.source.value}"
                f"{':' + descriptor.extension_id if descriptor.extension_id else ''}）",
                detail={
                    "command_id": descriptor.id,
                    "existing_source": existing.source.value,
                    "existing_extension": existing.extension_id,
                    "new_source": descriptor.source.value,
                    "new_extension": descriptor.extension_id,
                },
            )

    def register_builtin(self, descriptor: CommandDescriptor) -> None:
        if descriptor.source is not SourceKind.BUILTIN:
            raise RegistrationError(
                Reason.UNKNOWN_EXTENSION,
                f"register_builtin 只接受内置命令: {descriptor.id!r}",
            )
        with self._lock:
            self._check_absent(descriptor)
            self._commands[descriptor.id] = descriptor

    def register_extension_commands(
        self, extension_id: str, descriptors: list[CommandDescriptor]
    ) -> None:
        """原子注册：任一命令冲突或与批内重复，整批拒绝。"""
        if not extension_id:
            raise RegistrationError(Reason.UNKNOWN_EXTENSION, "extension_id 不能为空")
        with self._lock:
            if extension_id in self._by_extension:
                raise RegistrationError(
                    Reason.UNKNOWN_EXTENSION,
                    f"扩展已注册，需先停用再重新注册: {extension_id!r}",
                    detail={"extension_id": extension_id},
                )
            seen: set[str] = set()
            for d in descriptors:
                if d.source is not SourceKind.EXTENSION or d.extension_id != extension_id:
                    raise RegistrationError(
                        Reason.UNKNOWN_EXTENSION,
                        f"命令 {d.id!r} 的来源与扩展 {extension_id!r} 不一致",
                        detail={"extension_id": extension_id, "command_id": d.id},
                    )
                if d.id in seen:
                    raise RegistrationError(
                        Reason.DUPLICATE_COMMAND_ID,
                        f"扩展 {extension_id!r} 内部命令 ID 重复: {d.id!r}",
                        detail={"extension_id": extension_id, "command_id": d.id},
                    )
                seen.add(d.id)
                self._check_absent(d)
            # 全部校验通过才落注册表，保证原子性
            for d in descriptors:
                self._commands[d.id] = d
            self._by_extension[extension_id] = seen

    def unregister_extension(self, extension_id: str) -> None:
        """扩展停用/移除：其命令立即失效，不影响其他命令。"""
        with self._lock:
            ids = self._by_extension.pop(extension_id, None)
            if ids is None:
                raise RegistrationError(
                    Reason.UNKNOWN_EXTENSION,
                    f"扩展未注册: {extension_id!r}",
                    detail={"extension_id": extension_id},
                )
            for cid in ids:
                self._commands.pop(cid, None)

    def get(self, command_id: str) -> CommandDescriptor:
        with self._lock:
            try:
                return self._commands[command_id]
            except KeyError:
                raise RegistrationError(
                    Reason.COMMAND_NOT_FOUND,
                    f"命令不存在: {command_id!r}",
                    detail={"command_id": command_id},
                ) from None

    def get_or_none(self, command_id: str) -> CommandDescriptor | None:
        with self._lock:
            return self._commands.get(command_id)

    def has(self, command_id: str) -> bool:
        with self._lock:
            return command_id in self._commands

    def all(self) -> list[CommandDescriptor]:
        with self._lock:
            return sorted(self._commands.values(), key=lambda d: d.id)
