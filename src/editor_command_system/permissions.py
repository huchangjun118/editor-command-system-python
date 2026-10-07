"""权限与作用域限制。

作用域是一个从低到高的等级序列，调用方等级必须不低于命令声明的
``required_permission`` 才允许执行。每次校验——无论允许还是拒绝——
都会留下一条可追溯的审计记录。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# 等级数值越大，权限越高。
SCOPE_LEVELS: dict[str, int] = {
    "guest": 0,
    "user": 10,
    "developer": 20,
    "admin": 30,
}


@dataclass
class AuditRecord:
    command_id: str
    scope: str
    required: str
    allowed: bool
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


class PermissionManager:
    def __init__(self, levels: dict[str, int] | None = None) -> None:
        self.levels = dict(levels or SCOPE_LEVELS)
        self._records: list[AuditRecord] = []
        self._lock = threading.RLock()

    def _level(self, scope: str) -> int:
        if scope not in self.levels:
            raise ValueError(f"未知作用域: {scope!r}")
        return self.levels[scope]

    def check(
        self, command_id: str, caller_scope: str, required: str | None
    ) -> bool:
        """校验并写入审计记录。命令未声明权限要求时默认允许。"""
        with self._lock:
            if required is None:
                self._records.append(
                    AuditRecord(command_id, caller_scope, "(none)", True, "命令未声明权限要求")
                )
                return True
            if caller_scope not in self.levels:
                self._records.append(
                    AuditRecord(command_id, caller_scope, required, False, "调用方作用域未知")
                )
                return False
            if required not in self.levels:
                self._records.append(
                    AuditRecord(command_id, caller_scope, required, False, "命令要求的作用域未知")
                )
                return False
            allowed = self._level(caller_scope) >= self._level(required)
            reason = "权限足够" if allowed else (
                f"调用方等级 {self._level(caller_scope)} < 要求等级 {self._level(required)}"
            )
            self._records.append(
                AuditRecord(command_id, caller_scope, required, allowed, reason)
            )
            return allowed

    def records(self) -> list[AuditRecord]:
        with self._lock:
            return list(self._records)

    def denied_records(self) -> list[AuditRecord]:
        with self._lock:
            return [r for r in self._records if not r.allowed]
