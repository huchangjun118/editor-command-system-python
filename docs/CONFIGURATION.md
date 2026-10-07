# 快捷键与配置项

## 组合键规范

- 修饰键：`ctrl`、`shift`、`alt`、`meta`（`cmd`/`super`/`win` 归一化为 `meta`）；
- 主键：字母/数字/功能键名；单字符主键转小写；
- 段内以 `+` 连接，多段组合键（chord）以空格分隔：`ctrl+k ctrl+s`；
- 规范化函数 `normalize_chord()` 会统一大小写、修饰键别名与顺序，
  因此 `Ctrl+K  Ctrl+S` 与 `ctrl+k ctrl+s` 等价。

## 分层与优先级（从高到低）

1. `user`：用户覆盖（`set_user_binding`），持久化到状态文件，重启后恢复；
2. `extension_default`：内置/扩展默认绑定（`add_default`）。

同一层内，当前平台的专属绑定优先于 `Platform.ANY`。用户层对
“同 chord + 同平台 + 同 when”重复设置时是**覆盖**而非追加，
不会产生重复条目。

## 平台

`Platform.LINUX` / `MACOS` / `WINDOWS` / `ANY`。解析时传入当前平台：

```python
resolved = keybindings.resolve("ctrl+s", platform=Platform.MACOS)
```

## 冲突检测

同一层、同一平台键、同一 `when` 条件成立时，多个命令绑定到同一
chord 即为冲突：

- `resolve()` 遇到无法用优先级分出胜负的多条绑定时抛
  `KeybindingConflictError`，携带 `chord` 与去重后的 `command_ids`；
- `detect_conflicts()` 返回全部 `Conflict` 列表，`message()` 给出
  可区分的提示（层、平台、chord、涉及命令）。

`when` 互斥的两条绑定（如 `editorFocused` 与 `!editorFocused`）
在任一时刻只有一条生效，不算冲突。

## 解析结果的来源说明

`ResolvedBinding` 包含：

- `layer` / `source`：最终生效绑定来自哪一层、哪个来源；
- `platform` / `when`：适用平台与条件；
- `overridden`：被它压过的低优先级绑定；
- `describe_origin()`：一行人类可读说明，例如
  `ctrl+s -> fmt.save（用户覆盖，来源 user）`。

## 持久化文件

状态文件为 JSON，含三个顶层分区，重启后可明确区分：

| 分区 | 内容 | 重启后 |
| --- | --- | --- |
| `version` | 模式版本 | 用于将来迁移 |
| `user_bindings` | 用户键位覆盖 | 完整恢复，参与解析 |
| `history` | 历史元数据（命令 id/参数/时间戳） | 只读可追溯；撤销处理器无法跨进程恢复，不参与撤销 |

写入采用临时文件 + 原子替换，异常中断不会留下半截文件。

## 执行与权限配置

- `CommandSystem(state_path=..., history_limit=100)`：
  `history_limit` 为撤销栈容量，超出时最早的条目被淘汰；
- 作用域等级（数值越大权限越高）：
  `guest(0) < user(10) < developer(20) < admin(30)`，
  可通过 `PermissionManager(levels={...})` 自定义；
- 命令的 `required_permission` 为所需最低等级；
  未声明的命令任何作用域都可执行；
- 每次权限校验（允许或拒绝）都写入审计记录
  （`PermissionManager.records()` / `denied_records()`）；
- `ExecutionRequest(timeout=...)` 设置超时秒数；超时与取消返回
  `error_code="command_cancelled"`，且不写入撤销历史。
