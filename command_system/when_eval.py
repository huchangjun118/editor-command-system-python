"""when 表达式求值辅助：None 表达式视为恒真。"""

from __future__ import annotations

from .context import ContextKeys, WhenClause


def evaluate_optional(expression: str | None, keys: ContextKeys) -> bool:
    if expression is None:
        return True
    return WhenClause.parse(expression).evaluate(keys)
