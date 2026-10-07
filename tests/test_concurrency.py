"""需求 6：并发查找/执行自洽，长时间命令可取消，取消/超时不写历史。"""
from __future__ import annotations

import threading
import time

from editor_command_system.executor import ExecutionRequest
from editor_command_system.registry import Command
from editor_command_system.terminal import DeveloperTerminal


def test_concurrent_listing_is_consistent(registry, executor):
    for i in range(50):
        registry.register(Command(f"cmd.{i}", f"Cmd {i}", lambda i=i: i))
    terminals = [DeveloperTerminal(registry, executor) for _ in range(6)]
    errors = []

    def worker(term):
        try:
            for _ in range(20):
                ids = [e.command_id for e in term.help()]
                assert ids == sorted(ids)
                assert len(ids) == 50
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in terminals]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_concurrent_execution_results_are_isolated(registry, executor):
    registry.register(Command(
        "echo.n", "Echo", lambda n: n * 2,
        parameters=[__import__("editor_command_system", fromlist=["CommandParameter"])
                    .CommandParameter("n", "int", required=True)],
    ))
    results = []
    lock = threading.Lock()

    def worker(n):
        r = executor.execute(ExecutionRequest("echo.n", {"n": n}))
        with lock:
            results.append((n, r.value if r.success else None))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [(i, i * 2) for i in range(20)]


def _long_command(registry, started=None, release=None):
    def handler(cancellation_token):
        if started is not None:
            started.set()
        for _ in range(200):
            cancellation_token.raise_if_cancelled()
            if release is not None and release.is_set():
                return "finished"
            time.sleep(0.01)
        return "finished"
    registry.register(Command("long.run", "Long", handler,
                              undo_handler=lambda r, a: None))
    return handler


def test_cancel_long_running_command(registry, executor, history):
    started = threading.Event()
    _long_command(registry, started=started)
    handle = executor.execute_async(ExecutionRequest("long.run"))
    assert started.wait(1.0)
    assert executor.cancel(handle.execution_id) is True
    result = handle.future.result(timeout=2.0)
    assert result.success is False
    assert result.error_code == "command_cancelled"
    assert "取消" in result.error_message
    # 取消不得写入撤销历史
    time.sleep(0.05)
    assert len(history) == 0


def test_cancel_unknown_execution_returns_false(executor):
    assert executor.cancel("does-not-exist") is False


def test_timeout_does_not_write_history(registry, executor, history):
    _long_command(registry)
    result = executor.execute(ExecutionRequest("long.run", timeout=0.05))
    assert result.success is False
    assert result.error_code == "command_cancelled"
    time.sleep(0.05)
    assert len(history) == 0


def test_successful_async_still_writes_history(registry, executor, history):
    release = threading.Event()
    started = threading.Event()
    _long_command(registry, started=started, release=release)
    handle = executor.execute_async(ExecutionRequest("long.run"))
    started.wait(1.0)
    release.set()
    result = handle.future.result(timeout=2.0)
    assert result.success and result.value == "finished"
    assert len(history) == 1


def test_concurrent_undo_and_execute_is_deterministic(registry, context, permissions):
    from editor_command_system.history import HistoryManager
    from editor_command_system.executor import CommandExecutor

    # 大上限，避免容量淘汰干扰“执行/撤销计数自洽”的不变量
    history = HistoryManager(limit=10000)
    executor = CommandExecutor(registry, permissions, history, context)
    state = {"value": 0}

    def inc():
        state["value"] += 1
        return state["value"]

    def undo(r, a):
        state["value"] -= 1

    registry.register(Command("inc", "Inc", inc, undo_handler=undo))
    barrier = threading.Barrier(8)

    def producer():
        barrier.wait()
        for _ in range(50):
            executor.execute(ExecutionRequest("inc"))

    def undoer():
        barrier.wait()
        for _ in range(50):
            executor.undo_last()

    threads = [threading.Thread(target=producer) for _ in range(4)]
    threads += [threading.Thread(target=undoer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 最终状态与历史栈长度必须自洽：每执行 +1，每成功撤销 -1
    assert state["value"] == len(history)
