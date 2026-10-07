# 命令注册规则

## 统一注册表

内置命令与扩展贡献的命令共用同一个 `CommandRegistry`，通过 `Command`
描述符注册，没有任何“特殊入口”：

```python
from editor_command_system import Command, CommandParameter

registry.register(Command(
    id="file.save",                    # 全局唯一标识
    title="保存文件",
    handler=do_save,                   # 可调用对象
    source="builtin",                  # 贡献来源（任意可读字符串）
    extension_id=None,                 # 扩展贡献时填写扩展 id
    category="file",
    parameters=[
        CommandParameter("path", "string", required=True),
        CommandParameter("format", "string", default="auto"),
    ],
    when="editorFocused",              # 可见性条件（见 CONTEXT.md）
    enablement="dirty",                # 可用性条件
    required_permission="user",        # 所需最低作用域
    undo_handler=undo_save,            # 提供即代表可撤销
))
```

## 重复标识

- `id` 重复时抛出 `CommandAlreadyExistsError`（`code="command_already_exists"`）；
- 错误对象携带 `command_id` 与 `existing_source`（先注册者的来源），
  调用方可以据此区分“与内置命令冲突”还是“与某扩展冲突”；
- 后到的注册请求**整体拒绝**，不会覆盖既有命令。

## 扩展生命周期

| 操作 | 行为 |
| --- | --- |
| `deactivate_extension(ext_id)` | 该扩展的命令立即失效：`get()` 抛 `CommandNotFoundError`，列表中消失，快捷键/终端无法触发 |
| `activate_extension(ext_id)` | 恢复该扩展命令，命令定义不丢失 |
| `remove_extension(ext_id)` | 彻底删除该扩展贡献的全部命令 |

停用/移除只影响该扩展自身贡献的命令，其他命令（含其他扩展）不受影响。

通过 `CommandSystem` 门面使用时，扩展生命周期还会自动联动快捷键层：
停用扩展会使其默认绑定暂时不可解析，恢复时重新生效，移除时连同默认
绑定一起清除；用户覆盖（来源为 `user`）始终保留，不随扩展删除。

## 参数声明

`CommandParameter.type` 仅支持：`string` / `int` / `float` / `bool` / `json`。

- 缺少必填参数：`InvalidParameterError`（`code="invalid_parameter"`）；
- 传入未声明参数：以同样错误码拒绝，原因中包含“未声明”；
- 类型转换失败：同样错误码，原因中包含期望类型；
- 声明了默认值的可选参数，缺省时由系统填充默认值。

## 执行结果

执行从不抛出业务异常给调用方，而是返回 `ExecutionResult`：

- `success`、`value`：成功结果；
- `error_code`：稳定的错误码字符串，供程序区分失败原因；
- `error_message`：面向人的描述；
- `undoable`：该次执行是否已进入撤销栈；
- `execution_id`：本次执行的唯一标识（前置校验被拒绝时为空或 `rejected`）。
