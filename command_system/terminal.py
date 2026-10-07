"""开发者终端：在工具内查找、解释与执行命令。

- ``search``：按 id/标题模糊查找，附带可见性、可用性与原因说明。
- ``explain``：展示某个命令为何不可用或被禁用。
- ``run``：以 TERMINAL 作用域执行命令，结果与快捷键触发走同一链路。
"""

from __future__ import annotations

from dataclasses import dataclass

from .execution import CancellationToken, ExecutionEngine, ExecutionResult, Scope


@dataclass(frozen=True)
class CommandInfo:
    id: str
    title: str
    source: str
    visible: bool
    enabled: bool
    reasons: tuple[str, ...]    # 不可用/被禁用的原因说明


class DeveloperTerminal:
    """面向开发者的命令终端（无状态，可多实例并发使用同一引擎）。"""

    def __init__(self, engine: ExecutionEngine):
        self.engine = engine

    def _info(self, command_id: str, title: str, source: str) -> CommandInfo:
        visible = self.engine.is_visible(command_id)
        enabled = self.engine.is_enabled(command_id)
        reasons: tuple[str, ...] = ()
        if not (visible and enabled):
            reasons = tuple(self.engine.explain(command_id, Scope.TERMINAL))
        return CommandInfo(id=command_id, title=title, source=source,
                           visible=visible, enabled=enabled, reasons=reasons)

    def search(self, query: str = "") -> list[CommandInfo]:
        """按 id/标题模糊查找命令（大小写不敏感），结果按 id 排序、稳定。"""
        q = query.strip().lower()
        result = []
        for d in self.engine.registry.all():
            if q and q not in d.id.lower() and q not in d.title.lower():
                continue
            result.append(self._info(d.id, d.title, d.source.value))
        return result

    def explain(self, command_id: str) -> list[str]:
        return self.engine.explain(command_id, Scope.TERMINAL)

    def run(
        self,
        command_id: str,
        args: dict | None = None,
        *,
        permissions: frozenset[str] = frozenset(),
        token: CancellationToken | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        return self.engine.execute(
            command_id, args,
            scope=Scope.TERMINAL, permissions=permissions,
            token=token, timeout=timeout,
        )
