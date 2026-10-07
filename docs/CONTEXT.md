# 上下文判定语义

## 键必须先声明

上下文键通过 `ContextStore.define_key(ContextKey(name, default, description))`
声明。**既定默认处理**规则：

1. 表达式引用了未声明的键 → 抛 `UndefinedContextKeyError`
   （`code="undefined_context_key"`），**绝不按 `true` 静默放行**；
2. `ContextStore.set(name, value)` 写入未声明键 → 同样拒绝，
   避免键名拼写错误被静默吞掉；
3. 已声明但未显式赋值的键，取声明时的 `default`。

## 条件表达式

- 字面量：`true` / `false`、整数/浮点、`"双引号"` / `'单引号'` 字符串；
- 标识符：已声明的上下文键；
- 比较：`== != > >= < <=`；
- 逻辑：`!` / `not`、`&&` / `and`、`||` / `or`；
- 括号分组。

示例：`editorFocused && mode == "normal" || dirty`

## 可见性与可用性

- `when` 决定命令是否**可见**（出现在查找/终端列表中）；
- `enablement` 决定可见命令是否**可用**（能否执行）；
- 两者都缺省：视为成立；
- 命令不可见时不再判定可用性，直接不可执行；
- 执行前系统会再次判定，绕过终端直接调用同样受限。

不成立或无法判定时，`ContextStore.check()` 返回
`(False, 原因文本)`，终端 `explain()` 会把原因展示给用户。

## 稳定性与可复现

所有判定都基于不可变的 `ContextSnapshot`：

```python
snap = context.snapshot()
context.evaluate("dirty", snap)  # 始终得到拍照那一刻的值
```

同一份快照对同一表达式的任意次求值结果完全一致；并发期间系统取
快照进行判定，多个终端/面板同时查找与执行时不会看到撕裂的状态。
