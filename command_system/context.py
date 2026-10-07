"""上下文键存储与 when 表达式判定。

语义约定：
- 上下文键必须先 ``define`` 再使用；在表达式中引用未定义的键会抛出
  ``ContextError(UNDEFINED_CONTEXT_KEY)``，绝不静默放行。
- 已定义但未显式赋值的键取其声明的默认值。
- 同一组上下文下，同一表达式的判定结果稳定且可复现：
  表达式被解析为不可变语法树，求值只依赖快照，无任何随机或时序因素。

表达式语法（空白可忽略）：
    expr    := orExpr
    orExpr  := andExpr ("||" andExpr)*
    andExpr := unary ("&&" unary)*
    unary   := "!" unary | "(" expr ")" | atom
    atom    := KEY ("==" | "!=") VALUE | KEY
    KEY     := [A-Za-z_][A-Za-z0-9_.-]*
    VALUE   := 单/双引号字符串 | 数字 | true | false
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

from .errors import ContextError, Reason


@dataclass(frozen=True)
class ContextKeyDef:
    name: str
    default: Any = False


class ContextKeys:
    """上下文键的声明与取值存储（线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._defs: dict[str, ContextKeyDef] = {}
        self._values: dict[str, Any] = {}

    def define(self, name: str, default: Any = False) -> None:
        if not name or not isinstance(name, str):
            raise ContextError(Reason.UNDEFINED_CONTEXT_KEY, "上下文键名必须是非空字符串")
        with self._lock:
            self._defs[name] = ContextKeyDef(name, default)

    def set(self, name: str, value: Any) -> None:
        with self._lock:
            if name not in self._defs:
                raise ContextError(
                    Reason.UNDEFINED_CONTEXT_KEY,
                    f"上下文键未定义: {name!r}",
                    detail={"key": name},
                )
            self._values[name] = value

    def get(self, name: str) -> Any:
        with self._lock:
            if name not in self._defs:
                raise ContextError(
                    Reason.UNDEFINED_CONTEXT_KEY,
                    f"上下文键未定义: {name!r}",
                    detail={"key": name},
                )
            return self._values.get(name, self._defs[name].default)

    def is_defined(self, name: str) -> bool:
        with self._lock:
            return name in self._defs

    def snapshot(self) -> dict[str, Any]:
        """返回当前所有键的有效值快照（含默认值），用于可复现判定。"""
        with self._lock:
            return {name: self._values.get(name, d.default) for name, d in self._defs.items()}


# ---------------------------------------------------------------------------
# when 表达式：词法分析
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<op>&&|\|\||==|!=|!|\(|\))
      | (?P<string>'[^']*'|"[^"]*")
      | (?P<number>-?\d+(?:\.\d+)?)
      | (?P<ident>[A-Za-z_][A-Za-z0-9_.\-]*)
    )
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _Token:
    kind: str   # op / string / number / ident
    text: str


def _tokenize(expression: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(expression):
        if expression[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(expression, pos)
        if not m or m.end() == pos:
            raise ContextError(
                Reason.INVALID_WHEN_EXPRESSION,
                f"when 表达式在位置 {pos} 处无法解析: {expression!r}",
                detail={"expression": expression, "position": pos},
            )
        pos = m.end()
        if m.lastgroup == "op":
            tokens.append(_Token("op", m.group("op")))
        elif m.lastgroup == "string":
            tokens.append(_Token("string", m.group("string")[1:-1]))
        elif m.lastgroup == "number":
            tokens.append(_Token("number", m.group("number")))
        else:
            tokens.append(_Token("ident", m.group("ident")))
    return tokens


# ---------------------------------------------------------------------------
# when 表达式：语法树节点（不可变，保证判定可复现）
# ---------------------------------------------------------------------------


class _Node:
    def evaluate(self, values: dict[str, Any]) -> bool:
        raise NotImplementedError

    def keys(self) -> set[str]:
        raise NotImplementedError


@dataclass(frozen=True)
class _KeyNode(_Node):
    name: str

    def evaluate(self, values: dict[str, Any]) -> bool:
        return bool(values[self.name])

    def keys(self) -> set[str]:
        return {self.name}


@dataclass(frozen=True)
class _NotNode(_Node):
    child: _Node

    def evaluate(self, values: dict[str, Any]) -> bool:
        return not self.child.evaluate(values)

    def keys(self) -> set[str]:
        return self.child.keys()


@dataclass(frozen=True)
class _BinaryNode(_Node):
    op: str  # && || == !=
    left: _Node
    right: _Node | Any  # 比较运算的右操作数是字面量

    def evaluate(self, values: dict[str, Any]) -> bool:
        if self.op == "&&":
            return self.left.evaluate(values) and self.right.evaluate(values)
        if self.op == "||":
            return self.left.evaluate(values) or self.right.evaluate(values)
        left_val = values[self.left.name]  # 比较运算左侧必为键
        if self.op == "==":
            return left_val == self.right
        return left_val != self.right

    def keys(self) -> set[str]:
        result = self.left.keys()
        if isinstance(self.right, _Node):
            result |= self.right.keys()
        return result


_LITERALS: dict[str, Any] = {"true": True, "false": False}


class _Parser:
    def __init__(self, tokens: list[_Token], source: str):
        self._tokens = tokens
        self._pos = 0
        self._source = source

    def _error(self, msg: str) -> ContextError:
        return ContextError(
            Reason.INVALID_WHEN_EXPRESSION,
            f"when 表达式无效: {msg}（{self._source!r}）",
            detail={"expression": self._source},
        )

    def _peek(self) -> _Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> _Token:
        tok = self._peek()
        if tok is None:
            raise self._error("表达式意外结束")
        self._pos += 1
        return tok

    def parse(self) -> _Node:
        node = self._parse_or()
        if self._peek() is not None:
            raise self._error(f"存在多余内容 {self._peek().text!r}")
        return node

    def _parse_or(self) -> _Node:
        node = self._parse_and()
        while self._peek() is not None and self._peek().text == "||":
            self._next()
            node = _BinaryNode("||", node, self._parse_and())
        return node

    def _parse_and(self) -> _Node:
        node = self._parse_unary()
        while self._peek() is not None and self._peek().text == "&&":
            self._next()
            node = _BinaryNode("&&", node, self._parse_unary())
        return node

    def _parse_unary(self) -> _Node:
        tok = self._peek()
        if tok is not None and tok.kind == "op" and tok.text == "!":
            self._next()
            return _NotNode(self._parse_unary())
        if tok is not None and tok.kind == "op" and tok.text == "(":
            self._next()
            node = self._parse_or()
            closing = self._next()
            if closing.kind != "op" or closing.text != ")":
                raise self._error("缺少右括号")
            return node
        return self._parse_atom()

    def _parse_atom(self) -> _Node:
        tok = self._next()
        if tok.kind != "ident":
            raise self._error(f"期望上下文键，得到 {tok.text!r}")
        node: _Node = _KeyNode(tok.text)
        nxt = self._peek()
        if nxt is not None and nxt.kind == "op" and nxt.text in ("==", "!="):
            op = self._next().text
            value_tok = self._next()
            if value_tok.kind == "string":
                value: Any = value_tok.text
            elif value_tok.kind == "number":
                value = float(value_tok.text) if "." in value_tok.text else int(value_tok.text)
            elif value_tok.kind == "ident" and value_tok.text in _LITERALS:
                value = _LITERALS[value_tok.text]
            else:
                raise self._error(f"比较右值无效: {value_tok.text!r}")
            node = _BinaryNode(op, node, value)
        return node


class WhenClause:
    """when 表达式：解析一次得到不可变语法树，可反复对快照求值。"""

    def __init__(self, expression: str, root: _Node):
        self.expression = expression
        self._root = root

    @staticmethod
    def parse(expression: str) -> "WhenClause":
        if not expression or not expression.strip():
            raise ContextError(
                Reason.INVALID_WHEN_EXPRESSION,
                "when 表达式不能为空",
                detail={"expression": expression},
            )
        tokens = _tokenize(expression)
        root = _Parser(tokens, expression).parse()
        return WhenClause(expression, root)

    def evaluate(self, keys: ContextKeys) -> bool:
        values = keys.snapshot()
        for name in self._root.keys():
            if name not in values:
                raise ContextError(
                    Reason.UNDEFINED_CONTEXT_KEY,
                    f"when 表达式引用了未定义的上下文键: {name!r}",
                    detail={"key": name, "expression": self.expression},
                )
        return self._root.evaluate(values)

    def referenced_keys(self) -> set[str]:
        return self._root.keys()

    def __repr__(self) -> str:  # pragma: no cover
        return f"WhenClause({self.expression!r})"
