"""错误类型定义。

所有错误都带稳定的 ``code``，调用方可以据此区分失败原因，
而不是依赖错误消息文本做判断。
"""
from __future__ import annotations


class CommandSystemError(Exception):
    """命令系统错误基类。"""

    code: str = "command_system_error"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.code)
        if code is not None:
            self.code = code


class CommandAlreadyExistsError(CommandSystemError):
    """命令标识重复。"""

    code = "command_already_exists"

    def __init__(self, command_id: str, existing_source: str) -> None:
        super().__init__(
            f"命令 {command_id!r} 已由 {existing_source!r} 注册，拒绝重复注册"
        )
        self.command_id = command_id
        self.existing_source = existing_source


class CommandNotFoundError(CommandSystemError):
    """命令不存在或其所属扩展已停用/移除。"""

    code = "command_not_found"

    def __init__(self, command_id: str) -> None:
        super().__init__(f"命令 {command_id!r} 不存在或当前不可用")
        self.command_id = command_id


class UndefinedContextKeyError(CommandSystemError):
    """上下文键未定义，且不允许静默放行。"""

    code = "undefined_context_key"

    def __init__(self, key: str) -> None:
        super().__init__(
            f"上下文键 {key!r} 未定义；未定义键不得静默放行，请声明键或默认值"
        )
        self.key = key


class ContextEvaluationError(CommandSystemError):
    """上下文条件求值失败。"""

    code = "context_evaluation_error"


class KeybindingConflictError(CommandSystemError):
    """快捷键冲突（同一上下文下多个命令绑定同一按键）。"""

    code = "keybinding_conflict"

    def __init__(self, chord: str, command_ids: list[str]) -> None:
        super().__init__(
            f"快捷键 {chord!r} 存在冲突，涉及命令: {', '.join(command_ids)}"
        )
        self.chord = chord
        self.command_ids = command_ids


class InvalidKeybindingError(CommandSystemError):
    """快捷键声明非法。"""

    code = "invalid_keybinding"


class InvalidParameterError(CommandSystemError):
    """命令参数未通过声明的解析与校验。"""

    code = "invalid_parameter"

    def __init__(self, parameter: str, reason: str, value: object = None) -> None:
        super().__init__(f"参数 {parameter!r} 非法: {reason}")
        self.parameter = parameter
        self.reason = reason
        self.value = value


class CommandExecutionError(CommandSystemError):
    """命令处理器执行失败。"""

    code = "command_execution_failed"

    def __init__(self, command_id: str, cause: BaseException | None = None) -> None:
        super().__init__(f"命令 {command_id!r} 执行失败: {cause!r}")
        self.command_id = command_id
        self.__cause__ = cause


class CommandRecursionError(CommandSystemError):
    """命令在自身执行期间再次触发自身（重入被拒绝）。"""

    code = "command_recursion"

    def __init__(self, command_id: str) -> None:
        super().__init__(f"命令 {command_id!r} 重入触发被拒绝，避免无限递归")
        self.command_id = command_id


class CommandDisabledError(CommandSystemError):
    """命令当前被上下文判定为不可用。"""

    code = "command_disabled"

    def __init__(self, command_id: str, reason: str = "") -> None:
        super().__init__(f"命令 {command_id!r} 当前不可用: {reason or '未满足启用条件'}")
        self.command_id = command_id
        self.reason = reason


class PermissionDeniedError(CommandSystemError):
    """调用方权限不足，越权调用受限命令被拒绝。"""

    code = "permission_denied"

    def __init__(self, command_id: str, scope: str, required: str) -> None:
        super().__init__(
            f"越权调用被拒绝: 命令 {command_id!r} 需要 {required!r}，"
            f"当前作用域为 {scope!r}"
        )
        self.command_id = command_id
        self.scope = scope
        self.required = required


class CommandCancelledError(CommandSystemError):
    """命令执行被取消。"""

    code = "command_cancelled"

    def __init__(self, command_id: str, *, timed_out: bool = False) -> None:
        super().__init__(
            f"命令 {command_id!r} 因{'超时' if timed_out else '取消'}而终止"
        )
        self.command_id = command_id
        self.timed_out = timed_out
