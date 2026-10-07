"""进程内开发者终端。

可在工具内部调用，用于：

* ``help(query)`` 按标题/id/分类模糊查找当前**可见**的命令；
* ``explain(command_id)`` 解释某条命令为什么不可见 / 被禁用 / 需要什么权限，
  以及它当前的快捷键绑定来自用户覆盖还是扩展默认值；
* ``run(command_id, args, caller_scope)`` 执行命令并返回执行结果。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import CommandSystemError
from .executor import CommandExecutor, ExecutionRequest, ExecutionResult
from .keybindings import KeybindingRegistry, Platform
from .registry import CommandRegistry


@dataclass
class BindingInfo:
    chord: str
    command_id: str
    layer: str
    source: str
    platform: str
    when: str | None = None


@dataclass
class CommandExplanation:
    command_id: str
    title: str
    exists: bool
    visible: bool
    enabled: bool
    reasons: list[str] = field(default_factory=list)
    required_permission: str | None = None
    extension_id: str | None = None
    bindings: list[BindingInfo] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.exists and self.visible and self.enabled

    def render(self) -> str:
        if not self.exists:
            return f"{self.command_id}: 不存在（或其扩展已停用/移除）"
        lines = [f"{self.command_id} - {self.title}"]
        if not self.visible:
            lines.append("  状态: 不可见")
        elif not self.enabled:
            lines.append("  状态: 可见但当前被禁用")
        else:
            lines.append("  状态: 可用")
        for reason in self.reasons:
            lines.append(f"  - {reason}")
        if self.required_permission:
            lines.append(f"  - 需要权限: {self.required_permission}")
        if self.extension_id:
            lines.append(f"  - 贡献扩展: {self.extension_id}")
        for b in self.bindings:
            layer_text = "用户覆盖" if b.layer == "user" else "扩展默认值"
            lines.append(f"  - 快捷键 {b.chord}（{layer_text}，来源 {b.source}）")
        return "\n".join(lines)


class DeveloperTerminal:
    def __init__(
        self,
        registry: CommandRegistry,
        executor: CommandExecutor,
        keybindings: KeybindingRegistry | None = None,
        platform: Platform = Platform.ANY,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._keybindings = keybindings
        self.platform = platform

    # -- 查找 --------------------------------------------------------------
    def help(self, query: str = "") -> list[CommandExplanation]:
        q = query.strip().lower()
        out: list[CommandExplanation] = []
        for cmd in self._registry.list_commands(include_invisible=False):
            if q and q not in cmd.id.lower() and q not in cmd.title.lower() \
                    and q not in cmd.category.lower():
                continue
            out.append(self.explain(cmd.id))
        return out

    # -- 解释 --------------------------------------------------------------
    def explain(self, command_id: str) -> CommandExplanation:
        cmd = self._registry.get_if_active(command_id)
        if cmd is None:
            return CommandExplanation(
                command_id=command_id, title="", exists=False,
                visible=False, enabled=False,
                reasons=["命令不存在，或其所属扩展已被停用/移除"],
            )
        ctx = self._executor._context
        reasons: list[str] = []
        visible, v_reason = ctx.check(cmd.when)
        if not visible:
            enabled = False
            if v_reason:
                reasons.append("可见性: " + v_reason)
        else:
            enabled, e_reason = ctx.check(cmd.enablement)
            if not enabled and e_reason:
                reasons.append("可用性: " + e_reason)
        if cmd.required_permission:
            reasons.append(f"需要 {cmd.required_permission!r} 或更高权限")
        bindings: list[BindingInfo] = []
        if self._keybindings is not None:
            for kb in self._keybindings.bindings_for_command(command_id):
                bindings.append(
                    BindingInfo(
                        chord=kb.chord,
                        command_id=kb.command_id,
                        layer=kb.layer.value,
                        source=kb.source,
                        platform=kb.platform.value,
                        when=kb.when,
                    )
                )
        return CommandExplanation(
            command_id=cmd.id,
            title=cmd.title,
            exists=True,
            visible=visible,
            enabled=enabled,
            reasons=reasons,
            required_permission=cmd.required_permission,
            extension_id=cmd.extension_id,
            bindings=bindings,
        )

    # -- 执行 --------------------------------------------------------------
    def run(
        self,
        command_id: str,
        args: dict[str, Any] | None = None,
        caller_scope: str = "user",
        timeout: float | None = None,
    ) -> ExecutionResult:
        return self._executor.execute(
            ExecutionRequest(
                command_id=command_id,
                args=dict(args or {}),
                caller_scope=caller_scope,
                timeout=timeout,
            )
        )

    def run_async(
        self,
        command_id: str,
        args: dict[str, Any] | None = None,
        caller_scope: str = "user",
    ) -> Any:
        return self._executor.execute_async(
            ExecutionRequest(
                command_id=command_id,
                args=dict(args or {}),
                caller_scope=caller_scope,
            )
        )

    # -- 便捷文本接口 ------------------------------------------------------
    def execute_line(self, line: str, caller_scope: str = "user") -> str:
        """供交互式终端使用的简易入口：``command.id key=value flag=true``。"""
        parts = line.strip().split()
        if not parts:
            return ""
        command_id = parts[0]
        args: dict[str, Any] = {}
        for token in parts[1:]:
            if "=" not in token:
                raise CommandSystemError(f"无法解析参数片段 {token!r}，应为 key=value")
            key, value = token.split("=", 1)
            args[key] = value
        result = self.run(command_id, args, caller_scope=caller_scope)
        if result.success:
            return f"OK {result.command_id}: {result.value!r}"
        return f"FAIL {result.command_id} [{result.error_code}]: {result.error_message}"
