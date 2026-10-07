"""可区分的错误类型与原因码。

所有系统抛出的错误都携带 ``reason`` 字段，调用方可以据此区分失败原因，
而不是依赖错误消息文本。
"""

from __future__ import annotations

import enum


class Reason(enum.Enum):
    # 注册相关
    DUPLICATE_COMMAND_ID = "duplicate_command_id"
    UNKNOWN_EXTENSION = "unknown_extension"
    COMMAND_NOT_FOUND = "command_not_found"
    # 上下文相关
    UNDEFINED_CONTEXT_KEY = "undefined_context_key"
    INVALID_WHEN_EXPRESSION = "invalid_when_expression"
    # 快捷键相关
    INVALID_KEYBINDING = "invalid_keybinding"
    KEYBINDING_CONFLICT = "keybinding_conflict"
    # 参数相关
    MISSING_ARGUMENT = "missing_argument"
    UNKNOWN_ARGUMENT = "unknown_argument"
    INVALID_ARGUMENT_TYPE = "invalid_argument_type"
    INVALID_ARGUMENT_VALUE = "invalid_argument_value"
    # 执行相关
    COMMAND_NOT_ENABLED = "command_not_enabled"
    COMMAND_NOT_VISIBLE = "command_not_visible"
    PERMISSION_DENIED = "permission_denied"
    SCOPE_VIOLATION = "scope_violation"
    RECURSION_LIMIT = "recursion_limit"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    EXECUTION_FAILED = "execution_failed"
    # 撤销相关
    NOTHING_TO_UNDO = "nothing_to_undo"
    NOT_UNDOABLE = "not_undoable"


class CommandSystemError(Exception):
    """系统内所有错误的基类，携带可区分的 reason。"""

    def __init__(self, reason: Reason, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.detail = detail or {}

    def __repr__(self) -> str:  # pragma: no cover
        return f"{type(self).__name__}(reason={self.reason.value!r}, message={self.message!r})"


class RegistrationError(CommandSystemError):
    """命令注册阶段的错误（重复 ID、未知扩展等）。"""


class ContextError(CommandSystemError):
    """上下文键 / when 表达式相关错误。"""


class KeybindingError(CommandSystemError):
    """快捷键解析与冲突相关错误。"""


class ArgumentError(CommandSystemError):
    """参数解析与校验错误。"""


class ExecutionError(CommandSystemError):
    """命令执行链路错误（未启用、越权、递归、取消、超时等）。"""
