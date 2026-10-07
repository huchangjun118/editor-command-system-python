"""需求 2/4/5：可见性、可用性、参数校验、重入、失败不留半成品。"""
from __future__ import annotations

import pytest

from editor_command_system.executor import ExecutionRequest
from editor_command_system.registry import Command, CommandParameter


def test_invisible_command_not_listed_but_gettable(registry, context):
    registry.register(Command("hidden.cmd", "Hidden", lambda: None,
                              when="editorFocused"))
    assert all(c.id != "hidden.cmd" for c in registry.list_commands())
    assert registry.get("hidden.cmd").id == "hidden.cmd"
    context.set("editorFocused", True)
    assert any(c.id == "hidden.cmd" for c in registry.list_commands())


def test_disabled_command_execution_rejected(registry, executor, context):
    registry.register(Command("save.dirty", "Save", lambda: "ok",
                              enablement="dirty"))
    result = executor.execute(ExecutionRequest("save.dirty"))
    assert result.success is False
    assert result.error_code == "command_disabled"
    assert "dirty" in result.error_message


def test_enabled_command_runs(registry, executor, context):
    registry.register(Command("save.dirty", "Save", lambda: "ok",
                              enablement="dirty"))
    context.set("dirty", True)
    assert executor.execute(ExecutionRequest("save.dirty")).success


def test_missing_required_parameter_rejected(registry, executor):
    registry.register(Command(
        "greet", "Greet", lambda name: name,
        parameters=[CommandParameter("name", "string", required=True)],
    ))
    result = executor.execute(ExecutionRequest("greet", {}))
    assert not result.success and result.error_code == "invalid_parameter"


def test_undeclared_parameter_rejected(registry, executor):
    registry.register(Command("greet", "Greet", lambda: "x"))
    result = executor.execute(ExecutionRequest("greet", {"bogus": 1}))
    assert result.error_code == "invalid_parameter"
    assert "未声明" in result.error_message


@pytest.mark.parametrize("ptype,raw,ok", [
    ("int", "12", True), ("int", "abc", False),
    ("float", "1.5", True), ("float", "x", False),
    ("bool", "true", True), ("bool", "maybe", False),
])
def test_parameter_type_conversion(registry, executor, ptype, raw, ok):
    registry.register(Command(
        "typed", "Typed", lambda v: v,
        parameters=[CommandParameter("v", ptype, required=True)],
    ))
    result = executor.execute(ExecutionRequest("typed", {"v": raw}))
    assert result.success is ok
    if ok:
        expected = {"int": int, "float": float, "bool": lambda x: x in ("true",)}[ptype](raw)
        assert result.value == expected


def test_default_parameter_value(registry, executor):
    registry.register(Command(
        "withdef", "Def", lambda level: level,
        parameters=[CommandParameter("level", "string", default="info")],
    ))
    assert executor.execute(ExecutionRequest("withdef")).value == "info"


def test_handler_failure_leaves_no_history(registry, executor, history):
    def boom():
        raise RuntimeError("kaboom")
    registry.register(Command("boom", "Boom", boom,
                              undo_handler=lambda r, a: None))
    result = executor.execute(ExecutionRequest("boom"))
    assert not result.success and result.error_code == "command_execution_failed"
    assert len(history) == 0


def test_successful_undoable_command_pushed_and_undone(registry, executor, history):
    undone = []
    registry.register(Command(
        "edit", "Edit", lambda: "changed",
        undo_handler=lambda r, a: undone.append(r),
    ))
    assert executor.execute(ExecutionRequest("edit")).success
    assert len(history) == 1
    assert executor.undo_last() is True
    assert undone == ["changed"]
    assert len(history) == 0


def test_recursion_same_command_rejected(registry, executor):
    def handler(cancellation_token=None):
        inner = executor.execute(ExecutionRequest("rec.cmd"))
        assert inner.error_code == "command_recursion"
        return "outer"
    registry.register(Command("rec.cmd", "Rec", handler))
    result = executor.execute(ExecutionRequest("rec.cmd"))
    assert result.success and result.value == "outer"
    # 递归防护不影响后续独立调用
    assert executor.execute(ExecutionRequest("rec.cmd")).success
