"""持久化：用户快捷键覆盖与执行/撤销历史落盘，重启后可区分且不丢失。

- 每种状态一个独立 JSON 文件，加载时按类型区分来源；
  文件不存在返回 None（从未保存），与空状态 ``{}`` 可区分。
- 写入采用“临时文件 + fsync + 原子替换”，进程崩溃不会留下半个文件。
- 载荷带版本号，未来格式演进时可识别。
"""

from __future__ import annotations

import enum
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_FORMAT_VERSION = 1


class StateKind(enum.Enum):
    USER_KEYBINDINGS = "user_keybindings"
    HISTORY = "history"


class StateStore:
    """基于 JSON 文件的状态存储（线程安全）。"""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self._lock = threading.Lock()

    def _path(self, kind: StateKind) -> Path:
        return self.directory / f"{kind.value}.json"

    def save(self, kind: StateKind, payload: dict) -> None:
        envelope = {"version": _FORMAT_VERSION, "kind": kind.value, "payload": payload}
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(envelope, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._path(kind))  # 原子替换
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def load(self, kind: StateKind) -> dict | None:
        """加载状态；从未保存过返回 None，与空状态可区分。"""
        path = self._path(kind)
        with self._lock:
            if not path.exists():
                return None
            with open(path, encoding="utf-8") as f:
                envelope: dict[str, Any] = json.load(f)
        if envelope.get("kind") != kind.value:
            raise ValueError(f"状态文件类型不符: {path}")
        return envelope["payload"]
