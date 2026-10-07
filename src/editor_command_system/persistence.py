"""持久化存储。

用户键位覆盖（``user_bindings``）与历史状态（``history``）存放在同一份
JSON 文件的**不同分区**中，互不覆盖、重启后可明确区分。

* 写入采用临时文件 + ``os.replace`` 原子替换，进程崩溃不会留下半截文件；
* 历史条目只持久化元数据（命令 id、参数、时间戳、执行 id）。
  撤销处理器是进程内可调用对象，无法跨重启恢复，因此重启后载入的历史
  条目标记 ``restored=True``，仅供追溯，不再参与撤销。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any

SCHEMA_VERSION = 1


class PersistenceError(Exception):
    pass


class PersistenceStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "version": SCHEMA_VERSION,
            "user_bindings": [],
            "history": [],
        }
        if path and os.path.exists(path):
            self._load()

    # -- 低层读写 ----------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise PersistenceError(f"无法读取持久化文件 {self._path!r}: {exc}") from exc
        if not isinstance(raw, dict) or "version" not in raw:
            raise PersistenceError("持久化文件格式无法识别")
        self._data = {
            "version": raw.get("version", SCHEMA_VERSION),
            "user_bindings": list(raw.get("user_bindings", [])),
            "history": list(raw.get("history", [])),
        }

    def flush(self) -> None:
        if not self._path:
            return
        with self._lock:
            directory = os.path.dirname(os.path.abspath(self._path))
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".ecs-", suffix=".json.tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, ensure_ascii=False, indent=2, sort_keys=True)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self._path)
            except OSError as exc:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise PersistenceError(f"写入持久化文件失败: {exc}") from exc

    # -- 用户键位覆盖 ------------------------------------------------------
    def save_user_bindings(self, bindings: list[dict[str, Any]]) -> None:
        with self._lock:
            self._data["user_bindings"] = list(bindings)
        self.flush()

    def load_user_bindings(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(b) for b in self._data["user_bindings"]]

    # -- 历史元数据 --------------------------------------------------------
    def save_history(self, entries: list[dict[str, Any]]) -> None:
        with self._lock:
            self._data["history"] = list(entries)
        self.flush()

    def load_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._data["history"]]
