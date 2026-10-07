"""需求 5：权限/作用域限制与可追溯审计。"""
from __future__ import annotations

from editor_command_system.executor import ExecutionRequest
from editor_command_system.registry import Command


def test_unauthorized_call_is_rejected_and_audited(registry, executor, permissions):
    registry.register(Command("sys.wipe", "Wipe", lambda: "wiped",
                              required_permission="admin"))
    result = executor.execute(ExecutionRequest("sys.wipe", caller_scope="guest"))
    assert result.success is False
    assert result.error_code == "permission_denied"

    denied = permissions.denied_records()
    assert len(denied) == 1
    rec = denied[0]
    assert rec.command_id == "sys.wipe"
    assert rec.scope == "guest"
    assert rec.required == "admin"
    assert rec.allowed is False
    assert rec.reason  # 可追溯的原因


def test_authorized_call_succeeds(registry, executor):
    registry.register(Command("sys.wipe", "Wipe", lambda: "wiped",
                              required_permission="admin"))
    result = executor.execute(ExecutionRequest("sys.wipe", caller_scope="admin"))
    assert result.success and result.value == "wiped"


def test_equal_level_is_allowed(registry, executor):
    registry.register(Command("dev.build", "Build", lambda: 1,
                              required_permission="developer"))
    result = executor.execute(ExecutionRequest("dev.build", caller_scope="developer"))
    assert result.success


def test_terminal_explains_required_permission(registry, executor):
    from editor_command_system.terminal import DeveloperTerminal
    registry.register(Command("sys.wipe", "Wipe", lambda: None,
                              required_permission="admin"))
    term = DeveloperTerminal(registry, executor)
    explanation = term.explain("sys.wipe")
    assert explanation.required_permission == "admin"
    assert any("admin" in r for r in explanation.reasons)
