# 可扩展开发工具的命令与快捷键系统

一套纯 Python 实现的命令/快捷键基础设施，内置能力与外部扩展通过
**同一套入口**贡献命令；命令既能由快捷键触发，也能在进程内开发者
终端中查找、解释与执行。命令的可见性/可用性由上下文条件决定。

## 能力一览

1. **统一注册**：内置与扩展共用注册表；重复 `id` 被拒绝并区分原因；
   扩展停用/移除后其命令立即失效，不影响其他命令。
2. **上下文判定**：可见性 `when` 与可用性 `enablement` 基于声明键的
   快照求值；未定义键按既定规则拒绝（绝不静默放行），判定稳定可复现。
3. **快捷键系统**：多段组合键、平台区分、用户覆盖优先于扩展默认；
   冲突可检出并给出可区分提示；解析结果说明每条绑定来自哪一层。
4. **执行链路**：参数按声明解析校验，非法参数被拒绝；失败不写撤销
   历史（不留半成品）；命令内部再次触发自身会被重入保护拦截。
5. **权限与审计**：作用域等级校验；越权调用被拒绝并留可追溯审计记录；
   终端可解释命令为何不可用/被禁用。
6. **并发与取消**：注册表/判定/历史均线程安全；长命令支持协作式取消
   与超时；取消/超时不会写入历史。
7. **撤销与追溯**：成功的可撤销命令按 LIFO 回退；撤销与执行共享串行
   锁，并发结果确定；用户键位覆盖与历史元数据分区持久化，重启后
   可区分且不丢失。
8. **自动化测试**：覆盖命令冲突、上下文判定、快捷键解析、越权调用、
   并发与取消等场景。

## 快速开始

```python
from editor_command_system import (
    CommandSystem, Command, CommandParameter, Platform,
)

system = CommandSystem(state_path="./state.json")

@system.context
def _unused(): ...

# 声明上下文键（未声明键不会被静默放行）
from editor_command_system import ContextKey
system.context.define_key(ContextKey("dirty", False))

# 注册一条可撤销、需要上下文启用的命令
system.register(Command(
    id="file.insert-text",
    title="插入文本",
    handler=lambda text: text,
    parameters=[CommandParameter("text", "string", required=True)],
    enablement="dirty",
    undo_handler=lambda result, args: print("撤销:", result),
))

system.context.set("dirty", True)
print(system.execute("file.insert-text", {"text": "hello"}).value)

# 用户覆盖快捷键并持久化
system.set_user_binding("ctrl+s", "file.insert-text", Platform.LINUX)

# 终端：查找与解释
for exp in system.terminal.help("insert"):
    print(exp.render())
```

## 开发者终端

```python
exp = system.terminal.explain("file.insert-text")
print(exp.render())          # 状态、禁用原因、权限、快捷键来源
system.terminal.run("file.insert-text", {"text": "hi"})
system.terminal.execute_line("file.insert-text text=hi")  # 文本入口
```

也可以直接运行演示：

```bash
python3 main.py
```

## 运行测试

```bash
python3 -m pytest -q
```

## 文档

- [注册规则](docs/REGISTRATION.md)
- [上下文判定语义](docs/CONTEXT.md)
- [快捷键与配置项](docs/CONFIGURATION.md)

## 源码结构

```
src/editor_command_system/
  errors.py        # 稳定错误码体系
  context.py       # 上下文键、快照与表达式判定
  registry.py      # 统一命令注册表与扩展生命周期
  keybindings.py   # 分层快捷键、平台、冲突检测
  permissions.py   # 作用域校验与审计
  executor.py      # 执行链路、参数校验、重入、取消/超时、撤销
  history.py       # LIFO 撤销栈
  persistence.py   # 用户覆盖/历史分区原子持久化
  terminal.py      # 开发者终端（查找/解释/执行）
  system.py        # 门面，组装并联动持久化
```
