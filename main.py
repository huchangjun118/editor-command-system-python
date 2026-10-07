"""命令系统的可运行演示：注册、上下文、权限、快捷键、终端与撤销。

直接运行：``python3 main.py``（无需安装包，脚本会自举 src 路径）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from editor_command_system import (  # noqa: E402
    Command,
    CommandParameter,
    CommandSystem,
    ContextKey,
    KeyBinding,
    Platform,
)


def build_demo(state_path: str | None = None) -> CommandSystem:
    system = CommandSystem(state_path=state_path)
    ctx = system.context
    ctx.define_key(ContextKey("editorFocused", True, "编辑器是否聚焦"))
    ctx.define_key(ContextKey("dirty", False, "文档是否有未保存修改"))

    document: dict[str, str] = {"text": ""}

    def insert_text(text: str) -> str:
        document["text"] += text
        return document["text"]

    def undo_insert(result: str, args: dict) -> None:
        inserted = args["text"]
        if document["text"].endswith(inserted):
            document["text"] = document["text"][: -len(inserted)]

    system.register(Command(
        id="doc.insert-text",
        title="插入文本",
        category="文档",
        handler=insert_text,
        parameters=[CommandParameter("text", "string", required=True)],
        when="editorFocused",
        enablement="dirty",
        undo_handler=undo_insert,
        source="builtin",
    ))

    system.register(Command(
        id="sys.reload-window",
        title="重载窗口（受限）",
        category="系统",
        handler=lambda: "reloaded",
        required_permission="admin",
        source="builtin",
    ))

    system.keybindings.add_default(
        KeyBinding("doc.insert-text", "ctrl+i", source="builtin")
    )
    system.set_user_binding("ctrl+i", "doc.insert-text", Platform.LINUX)
    return system


def main() -> None:
    system = build_demo()
    term = system.terminal

    print("== 初始：dirty=false，命令应被禁用 ==")
    print(term.explain("doc.insert-text").render())

    print("\n== 越权调用受限命令（guest -> admin） ==")
    result = term.run("sys.reload-window", caller_scope="guest")
    print(f"success={result.success} code={result.error_message}")
    audit = system.permissions.denied_records()[-1]
    print(f"审计: {audit.command_id} scope={audit.scope} -> 允许={audit.allowed}")

    print("\n== 满足上下文后执行并撤销 ==")
    system.context.set("dirty", True)
    result = term.run("doc.insert-text", {"text": "hello"})
    print(f"执行成功={result.success}，文档={result.value!r}")
    system.executor.undo_last()
    print("撤销后文档已回退（撤销处理器运行）")

    print("\n== 快捷键来源 ==")
    resolved = system.keybindings.resolve("ctrl+i", platform=Platform.LINUX)
    print(resolved.describe_origin())

    print("\n== 查找命令 ==")
    for exp in term.help("插入"):
        print(exp.render())


if __name__ == "__main__":
    main()
