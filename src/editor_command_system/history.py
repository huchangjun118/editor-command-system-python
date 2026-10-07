"""可撤销历史。

* 可撤销命令执行成功后压栈，:meth:`undo` 严格按 LIFO 顺序回退；
* push/undo 在同一把锁内完成，撤销与新的执行并发发生时，
  谁先拿到锁谁先生效，结果确定、不会回退到错误的条目；
* 撤销处理器抛出的异常会向上抛给执行器统一包装，
  已经出栈的条目不重新压回（撤销失败需要调用方显式处理）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class HistoryEntry:
    command_id: str
    args: dict[str, Any]
    undo_handler: Callable[..., Any]
    result: Any = None
    timestamp: float = field(default_factory=time.time)


class HistoryManager:
    def __init__(self, limit: int = 100) -> None:
        if limit < 1:
            raise ValueError("history limit 必须 >= 1")
        self._limit = limit
        self._entries: list[HistoryEntry] = []
        self._lock = threading.RLock()

    def push(self, entry: HistoryEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._limit:
                del self._entries[: len(self._entries) - self._limit]

    def pop(self) -> HistoryEntry | None:
        with self._lock:
            return self._entries.pop() if self._entries else None

    def undo(self) -> bool:
        """弹出并执行最近一条撤销处理器；栈空返回 False。"""
        with self._lock:
            entry = self._entries.pop() if self._entries else None
        if entry is None:
            return False
        entry.undo_handler(entry.result, entry.args)
        return True

    def entries(self) -> list[HistoryEntry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def lock(self) -> threading.RLock:
        """系统级串行锁。

        执行器在“处理器执行 + 入栈”以及“出栈 + 撤销”期间持有这把锁，
        从而保证撤销与新的执行并发发生时结果确定。
        """
        return self._lock
