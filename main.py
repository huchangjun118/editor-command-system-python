"""示例宿主应用：把命令系统与开发者终端暴露为 HTTP 接口。

启动:  uv run python main.py
接口:
  GET  /terminal/search?query=...     查找命令（含可见性/可用性/原因）
  GET  /terminal/explain/{command_id} 说明命令为何不可用或被禁用
  POST /terminal/run                  执行命令 {"command_id": ..., "args": {...},
                                        "permissions": [...], "timeout": 秒}
  POST /terminal/undo                 撤销最近一个可撤销命令
  GET  /terminal/history              审计历史（含越权/取消/超时记录）
  GET  /keybindings                   当前生效的快捷键表（含来源层级）
  GET  /keybindings/conflicts         快捷键冲突列表
"""

from __future__ import annotations

import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from command_system import (
    ArgumentSpec,
    CommandDescriptor,
    CommandRegistry,
    ContextKeys,
    DeveloperTerminal,
    ExecutionEngine,
    KeybindingResolver,
    KeybindingRule,
    KeySequence,
    Layer,
    Platform,
    Reason,
    Scope,
    SourceKind,
    StateKind,
    StateStore,
    UndoStack,
)

# ---------------------------------------------------------------- 装配

STATE_DIR = Path(".state")
store = StateStore(STATE_DIR)

context = ContextKeys()
context.define("editorOpen", True)
context.define("workspaceDirty", False)

registry = CommandRegistry()
undo_stack = UndoStack()
engine = ExecutionEngine(registry, context, undo_stack=undo_stack, default_timeout=30)
terminal = DeveloperTerminal(engine)
resolver = KeybindingResolver(Platform.LINUX)

_document: list[str] = []


def _register_builtins() -> None:
    def insert(text: str) -> str:
        _document.append(text)
        context.set("workspaceDirty", True)
        return text

    def undo_insert(text: str) -> None:
        _document.remove(text)
        if not _document:
            context.set("workspaceDirty", False)

    def save() -> str:
        context.set("workspaceDirty", False)
        return "saved"

    def slow_task(seconds: float, token) -> str:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            token.throw_if_cancelled()
            time.sleep(0.01)
        return "finished"

    builtins = [
        CommandDescriptor(
            id="editor.insert", title="Editor: Insert Text", handler=insert,
            source=SourceKind.BUILTIN, enablement="editorOpen",
            args=(ArgumentSpec("text", str),),
            undoable=True, undo_handler=undo_insert,
        ),
        CommandDescriptor(
            id="file.save", title="File: Save", handler=save,
            source=SourceKind.BUILTIN, enablement="workspaceDirty",
        ),
        CommandDescriptor(
            id="task.slow", title="Task: Slow (cancellable)", handler=slow_task,
            source=SourceKind.BUILTIN,
            args=(ArgumentSpec("seconds", float),),
        ),
        CommandDescriptor(
            id="admin.reset", title="Admin: Reset Workspace",
            handler=lambda: _document.clear() or "reset",
            source=SourceKind.BUILTIN, permission="admin",
        ),
    ]
    for d in builtins:
        registry.register_builtin(d)


def _register_sample_extension() -> None:
    """示例扩展：与内置命令走同一份注册表。"""
    registry.register_extension_commands("sample.pretty", [
        CommandDescriptor(
            id="pretty.format", title="Pretty: Format Document",
            handler=lambda: "formatted",
            source=SourceKind.EXTENSION, extension_id="sample.pretty",
            enablement="editorOpen",
        ),
    ])


def _keybinding_rules() -> list[KeybindingRule]:
    def rule(seq, cmd, layer, **kw):
        return KeybindingRule(sequence=KeySequence.parse(seq), command_id=cmd,
                              layer=layer, **kw)

    rules = [
        rule("ctrl+s", "file.save", Layer.BUILTIN),
        rule("ctrl+shift+f", "pretty.format", Layer.EXTENSION,
             extension_id="sample.pretty"),
        rule("ctrl+k ctrl+z", "editor.undo", Layer.BUILTIN),
    ]
    # 重启后恢复用户覆盖（与历史状态分开存储、可区分）
    saved = store.load(StateKind.USER_KEYBINDINGS)
    if saved:
        for item in saved.get("rules", []):
            rules.append(rule(item["sequence"], item["command_id"], Layer.USER,
                              remove=item.get("remove", False)))
    return rules


_register_builtins()
_register_sample_extension()

app = FastAPI(title="Editor Command System")


# ---------------------------------------------------------------- 接口

class RunRequest(BaseModel):
    command_id: str
    args: dict = {}
    permissions: list[str] = []
    timeout: float | None = None


def _result_payload(r) -> dict:
    return {
        "status": r.status.value,
        "value": r.value,
        "reason": r.reason.value if r.reason else None,
        "message": r.message,
    }


@app.get("/terminal/search")
def search(query: str = ""):
    return [
        {
            "id": i.id, "title": i.title, "source": i.source,
            "visible": i.visible, "enabled": i.enabled,
            "reasons": list(i.reasons),
        }
        for i in terminal.search(query)
    ]


@app.get("/terminal/explain/{command_id:path}")
def explain(command_id: str):
    return {"command_id": command_id, "reasons": terminal.explain(command_id)}


@app.post("/terminal/run")
def run(req: RunRequest):
    result = terminal.run(
        req.command_id, req.args,
        permissions=frozenset(req.permissions), timeout=req.timeout,
    )
    return _result_payload(result)


@app.post("/terminal/undo")
def undo():
    return _result_payload(engine.undo(scope=Scope.TERMINAL))


@app.get("/terminal/history")
def history():
    return [
        {
            "command_id": h.command_id, "scope": h.scope.value,
            "status": h.status.value,
            "reason": h.reason.value if h.reason else None,
            "args": h.args,
        }
        for h in engine.history()
    ]


@app.get("/keybindings")
def keybindings():
    rules = _keybinding_rules()
    return [
        {
            "sequence": str(b.sequence), "command_id": b.command_id,
            "layer": b.layer.value, "shadowed": b.shadowed,
        }
        for b in resolver.resolve(rules)
    ]


@app.get("/keybindings/conflicts")
def keybinding_conflicts():
    rules = _keybinding_rules()
    return [
        {
            "sequence": str(c.sequence), "command_ids": list(c.command_ids),
            "layer": c.layer.value, "reason": Reason.KEYBINDING_CONFLICT.value,
        }
        for c in resolver.conflicts(rules)
    ]


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
