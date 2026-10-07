"""命令执行链路。

执行顺序（任一环节失败都在该环节被拒绝，且不会写入撤销历史）：

1. 命令存在且其扩展处于活动状态；
2. 可见性 ``when`` 与可用性 ``enablement`` 上下文判定；
3. 权限/作用域校验（拒绝会留审计记录）；
4. 参数按声明解析与校验（必填缺失、类型非法、未声明参数都被拒绝）；
5. 同一线程内的同命令重入检测，避免无限递归；
6. 在工作线程中调用处理器，支持协作式取消与超时；
7. 成功后，若命令声明了撤销处理器，才压入撤销栈。

取消与超时：系统通过 :class:`CancellationToken` 通知长时间运行的命令，
被取消的执行不会写入历史；处理器应周期性调用 ``raise_if_cancelled()``。
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import inspect
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from .context import ContextStore
from .errors import (
    CommandCancelledError,
    CommandDisabledError,
    CommandExecutionError,
    CommandNotFoundError,
    CommandRecursionError,
    InvalidParameterError,
    PermissionDeniedError,
)
from .history import HistoryEntry, HistoryManager
from .permissions import PermissionManager
from .registry import Command, CommandParameter, CommandRegistry


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.timed_out = False

    def cancel(self, *, timed_out: bool = False) -> None:
        if timed_out:
            self.timed_out = True
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CommandCancelledError("", timed_out=self.timed_out)


@dataclass
class ExecutionRequest:
    command_id: str
    args: dict[str, Any] = field(default_factory=dict)
    caller_scope: str = "user"
    timeout: float | None = None


@dataclass
class ExecutionResult:
    command_id: str
    success: bool
    value: Any = None
    error_code: str | None = None
    error_message: str | None = None
    undoable: bool = False
    execution_id: str = ""

    @classmethod
    def failure(cls, command_id: str, exc: Exception, execution_id: str = "") -> "ExecutionResult":
        code = getattr(exc, "code", exc.__class__.__name__)
        return cls(
            command_id=command_id,
            success=False,
            error_code=code,
            error_message=str(exc),
            execution_id=execution_id,
        )


@dataclass
class ExecutionHandle:
    execution_id: str
    command_id: str
    future: concurrent.futures.Future
    token: CancellationToken

    def cancel(self, *, timed_out: bool = False) -> None:
        self.token.cancel(timed_out=timed_out)

    def result(self, timeout: float | None = None) -> ExecutionResult:
        return self.future.result(timeout=timeout)


_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}


def _convert_parameter(param: CommandParameter, raw: Any) -> Any:
    if param.type == "string":
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise InvalidParameterError(param.name, "期望字符串", raw)
        return str(raw)
    if param.type == "int":
        if isinstance(raw, bool) or (
            not isinstance(raw, int)
            and not (isinstance(raw, str) and raw.strip().lstrip("-").isdigit())
        ):
            raise InvalidParameterError(param.name, "期望整数", raw)
        return int(raw)
    if param.type == "float":
        try:
            if isinstance(raw, bool):
                raise ValueError
            return float(raw)
        except (TypeError, ValueError):
            raise InvalidParameterError(param.name, "期望数字", raw) from None
    if param.type == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.lower() in _TRUE_VALUES | _FALSE_VALUES:
            return raw.lower() in _TRUE_VALUES
        raise InvalidParameterError(param.name, "期望布尔值(true/false)", raw)
    # json：原样透传，由命令自行处理
    return raw


class CommandExecutor:
    def __init__(
        self,
        registry: CommandRegistry,
        permissions: PermissionManager,
        history: HistoryManager,
        context: ContextStore,
        max_workers: int = 8,
    ) -> None:
        self._registry = registry
        self._permissions = permissions
        self._history = history
        self._context = context
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="cmd-exec"
        )
        # 正在执行中的命令 id 集合（随 contextvar 跨线程传播），用于重入检测
        self._active_stack: contextvars.ContextVar[tuple[str, ...]] = (
            contextvars.ContextVar("active_command_stack", default=())
        )
        self._active: dict[str, ExecutionHandle] = {}
        self._active_lock = threading.RLock()

    # -- 前置校验 ----------------------------------------------------------
    def _validate_args(self, command: Command, args: dict[str, Any]) -> dict[str, Any]:
        declared = {p.name: p for p in command.parameters}
        unknown = set(args) - set(declared) - {"cancellation_token"}
        if unknown:
            name = sorted(unknown)[0]
            raise InvalidParameterError(name, "命令未声明该参数")
        parsed: dict[str, Any] = {}
        for pname, param in declared.items():
            if pname in args:
                parsed[pname] = _convert_parameter(param, args[pname])
            elif param.required:
                raise InvalidParameterError(pname, "缺少必填参数")
            else:
                parsed[pname] = param.default
        return parsed

    def _guard_reentry_enter(self, command_id: str) -> Any:
        """若同一调用链中该命令已在执行则拒绝重入，否则标记并返回 reset token。"""
        stack = self._active_stack.get()
        if command_id in stack:
            raise CommandRecursionError(command_id)
        return self._active_stack.set((*stack, command_id))

    def _guard_reentry_exit(self, reset_token: Any) -> None:
        self._active_stack.reset(reset_token)

    def _prepare(self, request: ExecutionRequest) -> tuple[Command, dict[str, Any], str]:
        command = self._registry.get(request.command_id)
        visible, v_reason = self._context.check(command.when)
        if not visible:
            raise CommandDisabledError(command.id, "可见性条件不满足: " + v_reason)
        enabled, e_reason = self._context.check(command.enablement)
        if not enabled:
            raise CommandDisabledError(command.id, "可用性条件不满足: " + e_reason)
        if not self._permissions.check(
            command.id, request.caller_scope, command.required_permission
        ):
            raise PermissionDeniedError(
                command.id, request.caller_scope, command.required_permission or ""
            )
        parsed = self._validate_args(command, request.args)
        # 重入检查：在提交到线程池之前判定，避免线程池排队死锁。
        # 直接抛出异常（execute/execute_async 外层统一转成失败结果），
        # 使正在执行的外层命令也能立即感知，不会静默返回 None 后继续递归。
        stack = self._active_stack.get()
        if command.id in stack:
            raise CommandRecursionError(command.id)
        execution_id = uuid.uuid4().hex
        return command, parsed, execution_id

    # -- 实际执行 ----------------------------------------------------------
    def _invoke(
        self,
        command: Command,
        parsed: dict[str, Any],
        token: CancellationToken,
    ) -> Any:
        kwargs = dict(parsed)
        try:
            sig = inspect.signature(command.handler)
            if "cancellation_token" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            ):
                kwargs.setdefault("cancellation_token", token)
            return command.handler(**kwargs)
        except TypeError:
            # 处理器不接受 cancellation_token 时，去掉后重试一次
            kwargs.pop("cancellation_token", None)
            return command.handler(**kwargs)

    def _run_safely(
        self, command: Command, parsed: dict[str, Any], token: CancellationToken
    ) -> Any:
        """调用处理器；仅在成功时写历史，取消/失败/超时绝不写历史。"""
        token.raise_if_cancelled()
        reset_token = self._guard_reentry_enter(command.id)
        try:
            # 与撤销共用同一把锁：处理器执行+入栈 与 出栈+撤销 互斥，
            # 保证两者并发时结果确定。
            with self._history.lock:
                result = self._invoke(command, parsed, token)
                # 入栈前再次检查取消，避免“已报告取消/超时却写入历史”的竞态
                token.raise_if_cancelled()
                if command.undo_handler is not None:
                    self._history.push(
                        HistoryEntry(
                            command_id=command.id,
                            args={k: v for k, v in parsed.items()},
                            undo_handler=command.undo_handler,
                            result=result,
                        )
                    )
        finally:
            self._guard_reentry_exit(reset_token)
        return result

    def _run_to_result(
        self,
        command: Command,
        parsed: dict[str, Any],
        token: CancellationToken,
        execution_id: str,
    ) -> ExecutionResult:
        """工作线程入口：把所有异常统一翻译成 ExecutionResult。"""
        try:
            value = self._run_safely(command, parsed, token)
        except CommandCancelledError as exc:
            return ExecutionResult.failure(command.id, exc, execution_id)
        except (CommandDisabledError, PermissionDeniedError,
                InvalidParameterError, CommandRecursionError) as exc:
            return ExecutionResult.failure(command.id, exc, execution_id)
        except Exception as exc:
            return ExecutionResult.failure(
                command.id, CommandExecutionError(command.id, exc), execution_id
            )
        return ExecutionResult(
            command_id=command.id,
            success=True,
            value=value,
            undoable=command.undo_handler is not None,
            execution_id=execution_id,
        )

    # -- 对外入口 ----------------------------------------------------------
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        try:
            command, parsed, execution_id = self._prepare(request)
        except Exception as exc:
            if isinstance(exc, (CommandNotFoundError, CommandDisabledError, PermissionDeniedError,
                                InvalidParameterError, CommandRecursionError)):
                return ExecutionResult.failure(request.command_id, exc)
            raise
        token = CancellationToken()
        future = self._pool.submit(
            self._run_to_result, command, parsed, token, execution_id
        )
        try:
            return future.result(timeout=request.timeout)
        except concurrent.futures.TimeoutError:
            token.cancel(timed_out=True)
            exc = CommandCancelledError(command.id, timed_out=True)
            return ExecutionResult.failure(command.id, exc, execution_id)

    def execute_async(self, request: ExecutionRequest) -> ExecutionHandle:
        try:
            command, parsed, execution_id = self._prepare(request)
        except Exception as exc:
            if isinstance(exc, (CommandNotFoundError, CommandDisabledError, PermissionDeniedError,
                                InvalidParameterError, CommandRecursionError)):
                failed = ExecutionResult.failure(request.command_id, exc)
                future: concurrent.futures.Future = concurrent.futures.Future()
                future.set_result(failed)
                return ExecutionHandle("rejected", request.command_id, future,
                                       CancellationToken())
            raise
        token = CancellationToken()
        future = self._pool.submit(
            self._run_to_result, command, parsed, token, execution_id
        )
        handle = ExecutionHandle(execution_id, command.id, future, token)
        with self._active_lock:
            self._active[execution_id] = handle
        future.add_done_callback(
            lambda _f: self._active.pop(execution_id, None)
        )
        return handle

    def cancel(self, execution_id: str) -> bool:
        with self._active_lock:
            handle = self._active.get(execution_id)
        if handle is None:
            return False
        handle.cancel()
        return True

    def active_executions(self) -> list[str]:
        with self._active_lock:
            return list(self._active)

    def undo_last(self) -> bool:
        return self._history.undo()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
