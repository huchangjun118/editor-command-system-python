"""上下文键定义与上下文条件判定。

语义约定（既定默认处理）：

* 上下文键必须先通过 :meth:`ContextStore.define_key` 声明，声明时给出默认值；
* 条件表达式中出现**未声明**的键时，一律抛出
  :class:`~editor_command_system.errors.UndefinedContextKeyError`，
  绝不按 ``True`` 静默放行；
* 所有判定都基于 :class:`ContextSnapshot`（不可变快照），
  同一份快照对同一表达式的判定结果稳定且可复现。

表达式支持：标识符、``true/false``、数字、单/双引号字符串、
``!`` / ``not``、``&&`` / ``and``、``||`` / ``or``、
``== != > >= < <=`` 与括号。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ContextEvaluationError, UndefinedContextKeyError


@dataclass(frozen=True)
class ContextKey:
    name: str
    default: Any = None
    description: str = ""


@dataclass(frozen=True)
class ContextSnapshot:
    """某一时刻的上下文取值（含声明键的默认值回填）。"""

    values: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 极简词法分析
# ---------------------------------------------------------------------------
_TOKEN_PUNCT = ("==", "!=", ">=", "<=", "&&", "||", "(", ")", "!", ">", "<")


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            j = i + 1
            buf: list[str] = []
            while j < n and expr[j] != quote:
                if expr[j] == "\\" and j + 1 < n:
                    buf.append(expr[j + 1])
                    j += 2
                else:
                    buf.append(expr[j])
                    j += 1
            if j >= n:
                raise ContextEvaluationError(f"字符串字面量未闭合: {expr!r}")
            tokens.append(("string", "".join(buf)))
            i = j + 1
            continue
        two = expr[i : i + 2]
        if two in ("==", "!=", ">=", "<=", "&&", "||"):
            tokens.append((two, two))
            i += 2
            continue
        if ch in "()!><":
            tokens.append((ch, ch))
            i += 1
            continue
        if ch.isdigit() or (ch == "-" and i + 1 < n and expr[i + 1].isdigit()):
            j = i + 1
            while j < n and (expr[j].isdigit() or expr[j] == "."):
                j += 1
            raw = expr[i:j]
            tokens.append(("number", raw))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            tokens.append(("ident", expr[i:j]))
            i = j
            continue
        raise ContextEvaluationError(f"无法识别的字符 {ch!r}，表达式: {expr!r}")
    return tokens


class _Parser:
    """递归下降：or <- and <- not <- cmp <- atom。"""

    def __init__(self, tokens: list[tuple[str, str]], lookup: Any) -> None:
        self._tokens = tokens
        self._pos = 0
        self._lookup = lookup

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def parse(self) -> Any:
        if not self._tokens:
            return True
        value = self._parse_or()
        if self._peek() is not None:
            raise ContextEvaluationError("表达式存在多余的词法单元")
        return value

    def _parse_or(self) -> Any:
        value = self._parse_and()
        while (tok := self._peek()) and tok[0] == "||" or (tok and tok[1] == "or"):
            self._next()
            rhs = self._parse_and()
            value = bool(value) or bool(rhs)
        return value

    def _parse_and(self) -> Any:
        value = self._parse_not()
        while (tok := self._peek()) and tok[0] == "&&" or (tok and tok[1] == "and"):
            self._next()
            rhs = self._parse_not()
            value = bool(value) and bool(rhs)
        return value

    def _parse_not(self) -> Any:
        tok = self._peek()
        if tok and (tok[0] == "!" or tok[1] == "not"):
            self._next()
            return not bool(self._parse_not())
        return self._parse_cmp()

    def _parse_cmp(self) -> Any:
        left = self._parse_atom()
        tok = self._peek()
        if tok and tok[0] in ("==", "!=", ">", ">=", "<", "<="):
            op = self._next()[0]
            right = self._parse_atom()
            try:
                if op == "==":
                    return left == right
                if op == "!=":
                    return left != right
                if op == ">":
                    return left > right
                if op == ">=":
                    return left >= right
                if op == "<":
                    return left < right
                return left <= right
            except TypeError as exc:  # 不可比较的类型
                raise ContextEvaluationError(f"无法比较 {left!r} 与 {right!r}: {exc}") from exc
        return left

    def _parse_atom(self) -> Any:
        tok = self._peek()
        if tok is None:
            raise ContextEvaluationError("表达式意外结束")
        kind, text = self._next()
        if kind == "(":
            value = self._parse_or()
            closing = self._peek()
            if closing is None or closing[0] != ")":
                raise ContextEvaluationError("缺少右括号 )")
            self._next()
            return value
        if kind == "string":
            return text
        if kind == "number":
            return float(text) if "." in text else int(text)
        if kind == "ident":
            if text == "true":
                return True
            if text == "false":
                return False
            return self._lookup(text)
        raise ContextEvaluationError(f"意外的词法单元 {text!r}")


class ContextStore:
    """管理上下文键声明与当前取值，并对条件表达式求值。"""

    def __init__(self) -> None:
        self._keys: dict[str, ContextKey] = {}
        self._values: dict[str, Any] = {}

    # -- 声明与写入 --------------------------------------------------------
    def define_key(self, key: ContextKey) -> None:
        if not key.name or not key.name[0].isalpha() and key.name[0] != "_":
            raise ContextEvaluationError(f"非法上下文键名: {key.name!r}")
        self._keys[key.name] = key
        self._values.setdefault(key.name, key.default)

    def set(self, name: str, value: Any) -> None:
        if name not in self._keys:
            # 写入一个未声明的键同样不允许静默创建，避免键名拼写错误被吞掉。
            raise UndefinedContextKeyError(name)
        self._values[name] = value

    def get(self, name: str) -> Any:
        if name not in self._keys:
            raise UndefinedContextKeyError(name)
        return self._values[name]

    def declared_keys(self) -> list[str]:
        return sorted(self._keys)

    # -- 快照与判定 --------------------------------------------------------
    def snapshot(self) -> ContextSnapshot:
        merged = {name: key.default for name, key in self._keys.items()}
        merged.update(self._values)
        return ContextSnapshot(values=dict(merged))

    def _resolve(self, name: str, snapshot: ContextSnapshot) -> Any:
        if name not in snapshot.values:
            raise UndefinedContextKeyError(name)
        return snapshot.values[name]

    def evaluate(self, expression: str, snapshot: ContextSnapshot | None = None) -> bool:
        snap = snapshot or self.snapshot()
        tokens = _tokenize(expression)
        # 标识符中可能包含 and/or/not 关键字；解析器按位置识别。
        result = _Parser(tokens, lambda name: self._resolve(name, snap)).parse()
        return bool(result)

    def check(self, expression: str | None) -> tuple[bool, str]:
        """返回 (结果, 原因)。无条件表达式视为通过。"""
        if expression is None or expression.strip() == "":
            return True, ""
        snap = self.snapshot()
        try:
            ok = self.evaluate(expression, snap)
        except UndefinedContextKeyError as exc:
            return False, f"条件引用了未定义的上下文键 {exc.key!r}"
        except ContextEvaluationError as exc:
            return False, f"条件无法判定: {exc}"
        return ok, "" if ok else f"条件 {expression!r} 不成立"
