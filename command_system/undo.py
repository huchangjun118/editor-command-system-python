"""撤销栈与执行历史：可撤销命令按顺序回退。

确定性保证：
- 所有结构性操作（push/pop/clear）在同一把互斥锁下完成，
  撤销与新执行并发时，结果等同于某种串行顺序，不会出现中间态。
- 每个条目携带全局单调序号，回退严格按 LIFO 顺序进行。
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from typing import Any

from .errors import ExecutionError, Reason


@dataclass(frozen=True)
class UndoEntry:
    command_id: str
    undo_payload: Any          # 执行时产出、供撤销处理器使用的数据
    sequence: int              # 全局单调序号，保证回退顺序确定


class UndoStack:
    """线程安全的撤销栈。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[UndoEntry] = []
        self._counter = itertools.count()

    def next_sequence(self) -> int:
        with self._lock:
            return next(self._counter)

    def push(self, entry: UndoEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def pop(self) -> UndoEntry:
        with self._lock:
            if not self._entries:
                raise ExecutionError(Reason.NOTHING_TO_UNDO, "没有可撤销的操作")
            return self._entries.pop()

    def peek(self) -> UndoEntry | None:
        with self._lock:
            return self._entries[-1] if self._entries else None

    def entries(self) -> list[UndoEntry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
