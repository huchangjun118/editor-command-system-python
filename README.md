# Editor Command System (Python)

面向可扩展开发工具的命令与快捷键系统，配套可在工具内调用的开发者终端。
内置能力与外部扩展通过**同一套入口**贡献命令；用户既可以用快捷键触发，
也可以在开发者终端里查找与执行命令，命令的可见性与可用性由上下文条件决定。

## 运行

```bash
uv sync
uv run pytest          # 全部自动化测试
uv run python main.py  # 启动示例宿主（FastAPI，127.0.0.1:8000）
```

## 模块结构

| 模块 | 职责 |
| --- | --- |
| `command_system/errors.py` | 可区分的错误类型与 `Reason` 原因码 |
| `command_system/context.py` | 上下文键存储与 when 表达式解析/判定 |
| `command_system/registry.py` | 命令注册表（内置与扩展共用） |
| `command_system/keybindings.py` | 快捷键解析、分层覆盖、冲突检测 |
| `command_system/execution.py` | 执行链路：校验、权限、递归保护、取消/超时 |
| `command_system/undo.py` | 撤销栈（LIFO、线程安全） |
| `command_system/persistence.py` | 用户覆盖与历史的落盘与恢复 |
| `command_system/terminal.py` | 开发者终端：查找、解释、执行 |
| `main.py` | 示例宿主：把终端暴露为 HTTP 接口 |

## 注册规则

- 内置命令与扩展命令写入**同一份 `CommandRegistry`**，命令 ID 全局唯一。
- 重复 ID 一律被拒绝，错误 `reason = duplicate_command_id`，
  `detail` 中携带冲突双方来源（`existing_source` / `new_extension` 等），可区分。
- 扩展命令按批**原子注册**：批内任一命令冲突，整批不生效。
- 扩展 `unregister_extension(id)` 后其命令**立即失效**
  （`COMMAND_NOT_FOUND`），不影响其他命令；撤销栈中属于该扩展的条目
  在撤销时安全跳过。

```python
registry.register_builtin(CommandDescriptor(
    id="editor.insert", title="Editor: Insert Text",
    handler=insert, source=SourceKind.BUILTIN,
    args=(ArgumentSpec("text", str),),
    enablement="editorOpen",
    undoable=True, undo_handler=undo_insert,
))
registry.register_extension_commands("my.ext", [descriptor, ...])
```

## 上下文判定语义

- 上下文键必须先 `context.define(name, default)` 再使用。
- 表达式中引用**未定义的键**抛出 `ContextError(UNDEFINED_CONTEXT_KEY)`，
  绝不静默放行；已定义未赋值的键取声明的默认值。
- when 表达式语法：`key`、`!key`、`key == 值`、`key != 值`、`&&`、`||`、括号。
- 表达式被解析为不可变语法树，求值只依赖上下文快照，
  同一组上下文下结果**稳定且可复现**。
- `when` 控制可见性（搜索/菜单），`enablement` 控制可用性（能否执行）。

## 快捷键规则

- 层级（低→高）：`builtin` < `extension` < `user`；高层覆盖低层，
  每条解析结果都携带 `layer` 说明来源，被覆盖者标记 `shadowed=True`。
- 用户层可用 `remove=True` 解除低层绑定。
- 支持多段组合键（`ctrl+k ctrl+s`）与平台专属绑定（`platform=Platform.MACOS`）。
- **同层**、同序列绑定到多个命令即冲突：`conflicts()` 检出，
  `assert_no_conflicts()` 抛出 `reason = keybinding_conflict`；
  跨层同序列是覆盖而非冲突。

## 执行链路

执行顺序：存在性 → enablement → 权限 → 作用域 → 递归深度 → 参数校验 → 执行。

- 参数按 `ArgumentSpec` 校验，非法参数以可区分 reason 拒绝：
  `missing_argument` / `unknown_argument` / `invalid_argument_type` /
  `invalid_argument_value`。
- 受限命令（`permission=...`）越权调用返回 `denied / permission_denied`
  并写入审计历史；`metadata={"allowed_scopes": {...}}` 可限制调用作用域。
- 同一命令在调用链上重复进入超过 `max_recursion` 次被拒绝
  （`recursion_limit`），不会无限递归或卡死。
- 处理器异常时不写撤销栈、不记成功，**不留半成品状态**。
- 取消（`CancellationToken`）与超时是终态：状态为 `cancelled` / `timeout`，
  不进入撤销栈，历史不会被误记为成功。
- 可撤销命令成功后才入撤销栈，`engine.undo()` 严格按 LIFO 回退；
  撤销与新执行并发时由互斥锁保证结果确定（等同于某种串行顺序）。

## 开发者终端

```python
terminal = DeveloperTerminal(engine)
terminal.search("save")      # 模糊查找，附可见性/可用性/原因
terminal.explain("admin.reset")  # 为何不可用/被禁用
terminal.run("editor.insert", {"text": "hi"}, permissions=frozenset())
```

HTTP 接口见 `main.py` 模块 docstring（`/terminal/search`、`/terminal/explain/`、
`/terminal/run`、`/terminal/undo`、`/terminal/history`、`/keybindings` 等）。

## 配置项

| 配置 | 位置 | 说明 |
| --- | --- | --- |
| `max_recursion` | `ExecutionEngine(...)` | 同一命令在调用链上的最大深度，默认 8 |
| `default_timeout` | `ExecutionEngine(...)` | 默认执行超时（秒），可被单次调用覆盖 |
| `undo_stack` | `ExecutionEngine(...)` | 传入 `UndoStack()` 启用撤销 |
| `platform` | `KeybindingResolver(...)` | 平台专属绑定的判定目标 |
| `StateStore(directory)` | 持久化目录 | `user_keybindings.json` 与 `history.json`
  分开存储，重启后可区分；写入为临时文件 + 原子替换 |

## 测试覆盖

`tests/` 覆盖：命令冲突与原子注册、上下文判定（含未定义键拒绝与可复现性）、
快捷键解析/覆盖/平台/冲突、参数校验、越权调用与审计、递归保护、
取消与超时、并发执行与撤销的一致性、持久化重启恢复、HTTP 终端冒烟。
