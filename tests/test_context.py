"""需求 2：上下文键默认值、未定义键拒绝、判定稳定可复现。"""
from __future__ import annotations

import pytest

from editor_command_system.context import ContextKey, ContextStore
from editor_command_system.errors import (
    ContextEvaluationError,
    UndefinedContextKeyError,
)


def test_declared_default_is_used(context):
    assert context.get("mode") == "normal"
    assert context.evaluate('mode == "normal"') is True


def test_undefined_key_is_not_silently_allowed(context):
    # 表达式里出现未声明的键：不得静默放行
    with pytest.raises(UndefinedContextKeyError) as exc:
        context.evaluate("neverDeclared")
    assert exc.value.key == "neverDeclared"


def test_setting_undefined_key_rejected(context):
    with pytest.raises(UndefinedContextKeyError):
        context.set("typoKey", True)


def test_check_returns_failure_reason(context):
    ok, reason = context.check("editorFocused")
    assert ok is False and "不成立" in reason
    ok, reason = context.check("missingKey")
    assert ok is False and "未定义" in reason
    ok, reason = context.check(None)
    assert ok is True and reason == ""


def test_snapshot_is_stable_and_reproducible(context):
    context.set("editorFocused", False)
    snap = context.snapshot()
    results = {context.evaluate("!editorFocused && mode == \"normal\"", snap)
               for _ in range(20)}
    assert results == {True}
    # 修改实时状态不影响既有快照
    context.set("editorFocused", True)
    assert context.evaluate("editorFocused", snap) is False
    assert context.evaluate("editorFocused") is True


@pytest.mark.parametrize("expr,expected", [
    ("editorFocused || mode == \"normal\"", True),
    ("editorFocused && mode == \"normal\"", False),
    ("!editorFocused", True),
    ("not editorFocused and mode == \"normal\"", True),
    ("(editorFocused or dirty) or mode == \"normal\"", True),
    ("mode != \"insert\"", True),
    ("dirty == false", True),
])
def test_boolean_expressions(context, expr, expected):
    assert context.evaluate(expr) is expected


def test_invalid_expression_raises(context):
    with pytest.raises(ContextEvaluationError):
        context.evaluate("mode ==")
    with pytest.raises(ContextEvaluationError):
        context.evaluate("mode &&& x")
