"""命令执行链路。

链路顺序（任一环节失败即拒绝并留下审计记录，不会继续向下执行）：
    存在性 → 可用性(enablement) → 权限 → 作用域 → 递归深度 → 参数校验 → 执行

保证：
- 参数按 ArgumentSpec 声明校验，非法参数以可区分的 reason 拒绝。
- 处理器抛异常时：不写入撤销栈、不记录成功，状态保持执行前一致。
- 同一命令在调用链上重复进入超过 max_recursion 次即被拒绝，
  杜绝无限递归与不可恢复的卡死。
- 取消与超时是终态：不会写入撤销栈，历史中的状态为 cancelled/timeout
  而非 succeeded。
"""

from __future__ import annotations

import enum
import inspect
import threading
from dataclasses import dataclass, field
from typing import Any

from .context import ContextKeys
from .errors import ArgumentError, CommandSystemError, ExecutionError, Reason
from .registry import CommandDescriptor, CommandRegistry
from .undo import UndoEntry, UndoStack
from .when_eval import evaluate_optional


class Scope(enum.Enum):
    USER = "user"            # 普通用户触发（快捷键/菜单）
    TERMINAL = "terminal"    # 开发者终端
    INTERNAL = "internal"    # 命令内部再次触发


class Status(enum.Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class CancellationToken:
    """协作式取消令牌：处理器需自行检查或调用 throw_if_cancelled。"""

    _event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def throw_if_cancelled(self) -> None:
        if self.cancelled:
            raise ExecutionError(Reason.CANCELLED, "操作已取消")


@dataclass(frozen=True)
class ExecutionRecord:
    """一次执行的审计记录（含越权、失败、取消、超时、撤销）。"""

    command_id: str
    scope: Scope
    status: Status
    reason: Reason | None = None
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    status: Status
    value: Any = None
    reason: Reason | None = None
    message: str | None = None
    record: ExecutionRecord | None = None

    @property
    def ok(self) -> bool:
        return self.status is Status.SUCCEEDED


def _validate_args(
    descriptor: CommandDescriptor, raw: dict
) -> dict:
    """按声明解析与校验参数，返回规范化后的参数字典。"""
    if not isinstance(raw, dict):
        raise ArgumentError(
            Reason.INVALID_ARGUMENT_TYPE,
            f"参数必须是字典，得到 {type(raw).__name__}",
            detail={"command_id": descriptor.id},
        )
    specs = {s.name: s for s in descriptor.args}
    for key in raw:
        if key not in specs:
            raise ArgumentError(
                Reason.UNKNOWN_ARGUMENT,
                f"命令 {descriptor.id!r} 未声明参数 {key!r}",
                detail={"command_id": descriptor.id, "argument": key},
            )
    parsed: dict[str, Any] = {}
    for spec in descriptor.args:
        if spec.name in raw:
            value = raw[spec.name]
            if not isinstance(value, spec.type):
                raise ArgumentError(
                    Reason.INVALID_ARGUMENT_TYPE,
                    f"参数 {spec.name!r} 应为 {spec.type.__name__}，"
                    f"得到 {type(value).__name__}",
                    detail={
                        "command_id": descriptor.id,
                        "argument": spec.name,
                        "expected": spec.type.__name__,
                        "actual": type(value).__name__,
                    },
                )
            if spec.choices is not None and value not in spec.choices:
                raise ArgumentError(
                    Reason.INVALID_ARGUMENT_VALUE,
                    f"参数 {spec.name!r} 取值 {value!r} 不在允许范围 "
                    f"{list(spec.choices)!r} 内",
                    detail={
                        "command_id": descriptor.id,
                        "argument": spec.name,
                        "value": value,
                        "choices": list(spec.choices),
                    },
                )
            parsed[spec.name] = value
        elif spec.required:
            raise ArgumentError(
                Reason.MISSING_ARGUMENT,
                f"命令 {descriptor.id!r} 缺少必填参数 {spec.name!r}",
                detail={"command_id": descriptor.id, "argument": spec.name},
            )
        else:
            parsed[spec.name] = spec.default
    return parsed


def _accepts_token(handler) -> bool:
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):  # pragma: no cover - 内置函数等
        return False
    return "token" in sig.parameters


class ExecutionEngine:
    """负责命令的完整执行链路（线程安全，可多终端/面板并发使用）。"""

    def __init__(
        self,
        registry: CommandRegistry,
        context: ContextKeys,
        *,
        undo_stack: UndoStack | None = None,
        max_recursion: int = 8,
        default_timeout: float | None = None,
    ):
        self.registry = registry
        self.context = context
        self.undo_stack = undo_stack
        self.max_recursion = max_recursion
        self.default_timeout = default_timeout
        self._history: list[ExecutionRecord] = []
        self._history_lock = threading.Lock()
        self._local = threading.local()  # 每线程的命令调用栈（递归检测）

    # ------------------------------------------------------------------
    # 可见性 / 可用性
    # ------------------------------------------------------------------

    def _descriptor_or_none(self, command_id: str) -> CommandDescriptor | None:
        return self.registry.get_or_none(command_id)

    def is_visible(self, command_id: str) -> bool:
        d = self._descriptor_or_none(command_id)
        if d is None:
            return False
        return evaluate_optional(d.when, self.context)

    def is_enabled(self, command_id: str) -> bool:
        d = self._descriptor_or_none(command_id)
        if d is None:
            return False
        return evaluate_optional(d.enablement, self.context)

    def explain(self, command_id: str, scope: Scope = Scope.TERMINAL) -> list[str]:
        """说明命令为何不可见/不可用/被禁用（供开发者终端展示）。"""
        d = self._descriptor_or_none(command_id)
        if d is None:
            return [f"命令不存在: {command_id}"]
        reasons: list[str] = []
        if not evaluate_optional(d.when, self.context):
            reasons.append(f"不可见: when 条件不满足 ({d.when})")
        if not evaluate_optional(d.enablement, self.context):
            reasons.append(f"不可用: enablement 条件不满足 ({d.enablement})")
        if d.permission:
            reasons.append(f"受限命令: 需要权限 {d.permission!r}")
        allowed = d.metadata.get("allowed_scopes")
        if allowed and scope.value not in allowed:
            reasons.append(
                f"作用域限制: 当前 {scope.value}，仅允许 {sorted(allowed)}"
            )
        if not reasons:
            reasons.append("命令可用")
        return reasons

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def _stack(self) -> list[str]:
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = []
            self._local.stack = stack
        return stack

    def _record(
        self,
        command_id: str,
        scope: Scope,
        status: Status,
        reason: Reason | None,
        args: dict,
    ) -> ExecutionRecord:
        record = ExecutionRecord(
            command_id=command_id, scope=scope, status=status, reason=reason, args=dict(args)
        )
        with self._history_lock:
            self._history.append(record)
        return record

    def _finish(
        self,
        command_id: str,
        scope: Scope,
        status: Status,
        reason: Reason | None,
        args: dict,
        *,
        value: Any = None,
        message: str | None = None,
    ) -> ExecutionResult:
        record = self._record(command_id, scope, status, reason, args)
        return ExecutionResult(status=status, value=value, reason=reason,
                               message=message, record=record)

    def execute(
        self,
        command_id: str,
        args: dict | None = None,
        *,
        scope: Scope = Scope.USER,
        permissions: frozenset[str] = frozenset(),
        token: CancellationToken | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        raw_args = dict(args or {})
        token = token or CancellationToken()

        # 1. 存在性
        descriptor = self._descriptor_or_none(command_id)
        if descriptor is None:
            return self._finish(command_id, scope, Status.FAILED,
                                Reason.COMMAND_NOT_FOUND, raw_args,
                                message=f"命令不存在: {command_id}")

        # 2. 可用性（enablement）
        if not evaluate_optional(descriptor.enablement, self.context):
            return self._finish(command_id, scope, Status.FAILED,
                                Reason.COMMAND_NOT_ENABLED, raw_args,
                                message="命令当前不可用（enablement 不满足）")

        # 3. 权限（留审计记录，可追溯）
        if descriptor.permission and descriptor.permission not in permissions:
            return self._finish(command_id, scope, Status.DENIED,
                                Reason.PERMISSION_DENIED, raw_args,
                                message=f"缺少权限: {descriptor.permission}")

        # 4. 作用域
        allowed = descriptor.metadata.get("allowed_scopes")
        if allowed and scope.value not in allowed:
            return self._finish(command_id, scope, Status.DENIED,
                                Reason.SCOPE_VIOLATION, raw_args,
                                message=f"作用域 {scope.value} 不允许调用该命令")

        # 5. 递归深度
        stack = self._stack()
        if stack.count(command_id) >= self.max_recursion:
            return self._finish(command_id, scope, Status.FAILED,
                                Reason.RECURSION_LIMIT, raw_args,
                                message=f"命令 {command_id} 递归超过上限 "
                                        f"{self.max_recursion}")

        # 6. 参数校验
        try:
            parsed = _validate_args(descriptor, raw_args)
        except ArgumentError as exc:
            return self._finish(command_id, scope, Status.FAILED, exc.reason,
                                raw_args, message=exc.message)

        # 7. 取消前置检查：已取消则不进入执行
        if token.cancelled:
            return self._finish(command_id, scope, Status.CANCELLED,
                                Reason.CANCELLED, parsed, message="执行前已取消")

        effective_timeout = timeout if timeout is not None else self.default_timeout
        return self._invoke(descriptor, parsed, scope, token, effective_timeout, stack)

    def _invoke(
        self,
        descriptor: CommandDescriptor,
        parsed: dict,
        scope: Scope,
        token: CancellationToken,
        timeout: float | None,
        parent_stack: list[str],
    ) -> ExecutionResult:
        """在线程中运行处理器以支持超时；失败不留下半成品状态。"""
        outcome: dict[str, Any] = {}

        def run() -> None:
            # 把父线程的调用栈带入工作线程，保证跨线程的递归检测生效
            self._local.stack = [*parent_stack, descriptor.id]
            try:
                kwargs = dict(parsed)
                if _accepts_token(descriptor.handler):
                    kwargs["token"] = token
                outcome["value"] = descriptor.handler(**kwargs)
            except ExecutionError as exc:
                outcome["error"] = exc
            except Exception as exc:  # noqa: BLE001 - 统一包装为 EXECUTION_FAILED
                outcome["error"] = ExecutionError(
                    Reason.EXECUTION_FAILED, f"处理器异常: {exc}"
                )

        worker = threading.Thread(target=run, daemon=True,
                                  name=f"cmd-{descriptor.id}")
        worker.start()
        worker.join(timeout)

        if worker.is_alive():
            # 超时：请求协作式取消，记录终态，不写撤销栈
            token.cancel()
            return self._finish(descriptor.id, scope, Status.TIMEOUT,
                                Reason.TIMEOUT, parsed,
                                message=f"执行超过 {timeout}s 超时")

        error = outcome.get("error")
        if error is not None:
            if error.reason is Reason.CANCELLED:
                return self._finish(descriptor.id, scope, Status.CANCELLED,
                                    Reason.CANCELLED, parsed, message=error.message)
            return self._finish(descriptor.id, scope, Status.FAILED,
                                error.reason, parsed, message=error.message)

        if token.cancelled:
            # 处理器在取消后返回：按取消处理，不写撤销栈
            return self._finish(descriptor.id, scope, Status.CANCELLED,
                                Reason.CANCELLED, parsed, message="执行已取消")

        value = outcome.get("value")
        if descriptor.undoable and self.undo_stack is not None:
            # 只有成功完成才进入撤销栈
            self.undo_stack.push(
                UndoEntry(command_id=descriptor.id, undo_payload=value,
                          sequence=self.undo_stack.next_sequence())
            )
        return self._finish(descriptor.id, scope, Status.SUCCEEDED, None,
                            parsed, value=value)

    # ------------------------------------------------------------------
    # 撤销
    # ------------------------------------------------------------------

    def undo(self, *, scope: Scope = Scope.USER) -> ExecutionResult:
        """按 LIFO 顺序回退最近一个可撤销命令。

        与并发执行的确定性由 UndoStack 的互斥锁保证：
        pop 是原子操作，撤销与新执行的结果等同于某种串行顺序。
        """
        if self.undo_stack is None:
            raise ExecutionError(Reason.NOT_UNDOABLE, "系统未启用撤销")
        entry = self.undo_stack.pop()  # 原子；空栈抛 NOTHING_TO_UNDO
        descriptor = self._descriptor_or_none(entry.command_id)
        if descriptor is None or descriptor.undo_handler is None:
            # 命令已随扩展移除：该条目被丢弃，但不影响栈中其他条目
            return self._finish(entry.command_id, scope, Status.FAILED,
                                Reason.COMMAND_NOT_FOUND, {},
                                message="命令已不可用，无法撤销")
        try:
            descriptor.undo_handler(entry.undo_payload)
        except Exception as exc:  # noqa: BLE001
            return self._finish(entry.command_id, scope, Status.FAILED,
                                Reason.EXECUTION_FAILED, {},
                                message=f"撤销失败: {exc}")
        return self._finish(entry.command_id, scope, Status.SUCCEEDED, None, {})

    # ------------------------------------------------------------------
    # 审计
    # ------------------------------------------------------------------

    def history(self) -> list[ExecutionRecord]:
        with self._history_lock:
            return list(self._history)
