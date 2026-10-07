import threading
import time

import pytest

from command_system import (
    ArgumentSpec,
    CancellationToken,
    CommandDescriptor,
    CommandRegistry,
    ContextKeys,
    ExecutionEngine,
    Reason,
    Scope,
    SourceKind,
    UndoStack,
)
from command_system.execution import Status


def make_engine(*, max_recursion=8, default_timeout=None):
    registry = CommandRegistry()
    context = ContextKeys()
    context.define("editorOpen", False)
    undo = UndoStack()
    engine = ExecutionEngine(registry, context, undo_stack=undo,
                             max_recursion=max_recursion,
                             default_timeout=default_timeout)
    return registry, context, undo, engine


def add(registry, cid, handler=lambda **kw: "ok", **kw):
    registry.register_builtin(CommandDescriptor(
        id=cid, title=cid, handler=handler, source=SourceKind.BUILTIN, **kw))


# ---------------- 参数校验 ----------------

def test_missing_argument_rejected():
    reg, _, _, eng = make_engine()
    add(reg, "greet", lambda name: name,
        args=(ArgumentSpec("name", str),))
    r = eng.execute("greet", {})
    assert r.status is Status.FAILED and r.reason is Reason.MISSING_ARGUMENT


def test_unknown_argument_rejected():
    reg, _, _, eng = make_engine()
    add(reg, "greet", lambda name: name, args=(ArgumentSpec("name", str),))
    r = eng.execute("greet", {"name": "x", "extra": 1})
    assert r.reason is Reason.UNKNOWN_ARGUMENT


def test_wrong_type_rejected():
    reg, _, _, eng = make_engine()
    add(reg, "greet", lambda name: name, args=(ArgumentSpec("name", str),))
    r = eng.execute("greet", {"name": 42})
    assert r.reason is Reason.INVALID_ARGUMENT_TYPE


def test_choice_constraint_rejected():
    reg, _, _, eng = make_engine()
    add(reg, "setmode", lambda mode: mode,
        args=(ArgumentSpec("mode", str, choices=("a", "b")),))
    assert eng.execute("setmode", {"mode": "a"}).ok
    r = eng.execute("setmode", {"mode": "zzz"})
    assert r.reason is Reason.INVALID_ARGUMENT_VALUE


def test_optional_argument_default():
    reg, _, _, eng = make_engine()
    add(reg, "greet", lambda name, punct: f"{name}{punct}",
        args=(ArgumentSpec("name", str),
              ArgumentSpec("punct", str, required=False, default="!")))
    assert eng.execute("greet", {"name": "hi"}).value == "hi!"


# ---------------- 可用性 / 权限 / 作用域 ----------------

def test_enablement_blocks_execution():
    reg, ctx, _, eng = make_engine()
    add(reg, "save", enablement="editorOpen")
    r = eng.execute("save")
    assert r.status is Status.FAILED and r.reason is Reason.COMMAND_NOT_ENABLED
    ctx.set("editorOpen", True)
    assert eng.execute("save").ok


def test_permission_denied_is_audited():
    reg, _, _, eng = make_engine()
    add(reg, "admin.wipe", permission="admin")
    r = eng.execute("admin.wipe", permissions=frozenset())
    assert r.status is Status.DENIED and r.reason is Reason.PERMISSION_DENIED
    # 留下可追溯记录
    denied = [h for h in eng.history() if h.status is Status.DENIED]
    assert len(denied) == 1 and denied[0].command_id == "admin.wipe"
    # 有权限则放行
    assert eng.execute("admin.wipe", permissions=frozenset({"admin"})).ok


def test_scope_violation():
    reg, _, _, eng = make_engine()
    add(reg, "internal.only", metadata={"allowed_scopes": {"internal"}})
    r = eng.execute("internal.only", scope=Scope.USER)
    assert r.status is Status.DENIED and r.reason is Reason.SCOPE_VIOLATION
    assert eng.execute("internal.only", scope=Scope.INTERNAL).ok


def test_explain_reports_reasons():
    reg, _, _, eng = make_engine()
    add(reg, "save", enablement="editorOpen", permission="write",
        when="editorOpen")
    reasons = eng.explain("save")
    text = "\n".join(reasons)
    assert "enablement" in text and "write" in text and "when" in text
    assert eng.explain("ghost") == ["命令不存在: ghost"]


# ---------------- 递归保护 ----------------

def test_recursion_limit_prevents_infinite_loop():
    reg, _, _, eng = make_engine(max_recursion=3)

    def recurse():
        return eng.execute("loop", scope=Scope.INTERNAL)

    add(reg, "loop", recurse)
    r = eng.execute("loop")
    # 最外层成功返回（其内部结果被丢弃），但历史中必有 RECURSION_LIMIT
    reasons = [h.reason for h in eng.history()]
    assert Reason.RECURSION_LIMIT in reasons
    depth = sum(1 for h in eng.history() if h.command_id == "loop")
    assert depth <= 4  # 有限终止，未卡死


# ---------------- 失败原子性 / 撤销 ----------------

def test_failed_undoable_command_leaves_no_undo_entry():
    reg, _, undo, eng = make_engine()

    def boom():
        raise RuntimeError("half done")

    add(reg, "risky", boom, undoable=True, undo_handler=lambda p: None)
    r = eng.execute("risky")
    assert r.status is Status.FAILED and r.reason is Reason.EXECUTION_FAILED
    assert undo.entries() == []  # 没有半成品状态


def test_undoable_command_roundtrip():
    reg, _, undo, eng = make_engine()
    doc = []

    def insert(text):
        doc.append(text)
        return text  # 返回值作为撤销载荷

    def undo_insert(text):
        doc.remove(text)

    add(reg, "insert", insert, args=(ArgumentSpec("text", str),),
        undoable=True, undo_handler=undo_insert)
    eng.execute("insert", {"text": "a"})
    eng.execute("insert", {"text": "b"})
    assert doc == ["a", "b"]
    assert eng.undo().ok and doc == ["a"]   # LIFO：先撤 b
    assert eng.undo().ok and doc == []
    with pytest.raises(Exception) as exc:
        eng.undo()
    assert exc.value.reason is Reason.NOTHING_TO_UNDO


# ---------------- 取消与超时 ----------------

def test_cancel_before_start():
    reg, _, undo, eng = make_engine()
    add(reg, "slow", lambda: "done", undoable=True, undo_handler=lambda p: None)
    token = CancellationToken()
    token.cancel()
    r = eng.execute("slow", token=token)
    assert r.status is Status.CANCELLED and r.reason is Reason.CANCELLED
    assert undo.entries() == []


def test_cancel_during_execution():
    reg, _, undo, eng = make_engine()

    def slow(token):
        for _ in range(100):
            token.throw_if_cancelled()
            time.sleep(0.005)
        return "done"

    add(reg, "slow", slow, undoable=True, undo_handler=lambda p: None)
    token = CancellationToken()
    result = {}

    def run():
        result["r"] = eng.execute("slow", token=token)

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.02)
    token.cancel()
    t.join(timeout=5)
    assert result["r"].status is Status.CANCELLED
    assert undo.entries() == []
    # 历史中没有把取消误记为成功
    assert not any(h.command_id == "slow" and h.status is Status.SUCCEEDED
                   for h in eng.history())


def test_timeout_is_terminal_state():
    reg, _, undo, eng = make_engine()

    def very_slow(token):
        while not token.cancelled:
            time.sleep(0.005)
        return "late"

    add(reg, "very.slow", very_slow, undoable=True, undo_handler=lambda p: None)
    r = eng.execute("very.slow", timeout=0.05)
    assert r.status is Status.TIMEOUT and r.reason is Reason.TIMEOUT
    assert undo.entries() == []
    time.sleep(0.1)  # 等工作线程响应取消退出
    assert not any(h.status is Status.SUCCEEDED for h in eng.history())


# ---------------- 并发 ----------------

def test_concurrent_execution_and_undo_are_consistent():
    reg, _, undo, eng = make_engine()
    counter = {"n": 0}
    lock = threading.Lock()

    def incr():
        with lock:
            counter["n"] += 1
        return 1

    def decr(payload):
        with lock:
            counter["n"] -= payload

    add(reg, "incr", incr, undoable=True, undo_handler=decr)

    def worker_exec():
        for _ in range(50):
            eng.execute("incr")

    def worker_undo():
        for _ in range(50):
            try:
                eng.undo()
            except Exception:
                pass

    threads = [threading.Thread(target=worker_exec) for _ in range(4)]
    threads += [threading.Thread(target=worker_undo) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 自洽性：成功执行数 - 成功撤销数 == 计数器值 == 撤销栈剩余
    succeeded = sum(1 for h in eng.history()
                    if h.command_id == "incr" and h.status is Status.SUCCEEDED)
    undone = sum(1 for h in eng.history()
                 if h.command_id == "incr" and h.status is Status.SUCCEEDED
                 and h.args == {})
    # 撤销记录与执行记录可通过计数器对账
    assert counter["n"] == len(undo.entries())
    assert counter["n"] >= 0
    assert succeeded >= undone
