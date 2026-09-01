# kernel/ 技术盲区速查

用途：owner 实现 kernel 各模块时可能不熟的技术点（M0/M1 已收录；M2 起按步骤在文件末尾追加，见 §11–14）。

---

## 1. `@dataclass`（Message / Context / Response）

- **用途**：自动生成 `__init__`、`__repr__`、`__eq__`，减少样板代码。
- **最小例子**：
  ```python
  from dataclasses import dataclass

  @dataclass
  class Point:
      x: int
      y: int = 0

  p = Point(1)
  ```
- **出现位置**：`kernel/message.py`、`kernel/context.py`、`kernel/providers/base.py`。

---

## 2. `ABC` + `@abstractmethod`

- **用途**：定义抽象基类，子类必须实现 `chat()`，否则无法实例化。
- **最小例子**：
  ```python
  from abc import ABC, abstractmethod

  class Provider(ABC):
      @abstractmethod
      def chat(self): ...
  ```
- **出现位置**：`kernel/providers/base.py`。

---

## 3. `from __future__ import annotations`

- **用途**：让类型注解里的类名可以前向引用，避免循环导入时硬写字符串。
- **最小例子**：
  ```python
  from __future__ import annotations

  class Node:
      def next(self) -> Node: ...  # 不用写 "Node"
  ```
- **出现位置**：所有 kernel 模块顶部。

---

## 4. `os.environ.get`

- **用途**：读取环境变量，同时给默认值。
- **最小例子**：
  ```python
  import os
  api_key = os.environ.get("OPENAI_API_KEY", "")
  ```
- **出现位置**：`kernel/providers/openai_compat.py`、`kernel/loop.py`。

---

## 5. `requests` POST OpenAI `/chat/completions`

- **用途**：构造 HTTP 请求，把本地 Message 翻译成 OpenAI 兼容格式。
- **最小例子**：
  ```python
  import requests

  resp = requests.post(
      f"{base_url}/chat/completions",
      headers={
          "Authorization": f"Bearer {api_key}",
          "Content-Type": "application/json",
      },
      json={
          "model": model,
          "messages": [{"role": "user", "content": "hi"}],
      },
  )
  resp.raise_for_status()
  data = resp.json()
  content = data["choices"][0]["message"]["content"]
  ```
- **出现位置**：`kernel/providers/openai_compat.py`。

---

## 6. 钩子广播 `_emit`（M2 第一步起为真实广播）

- **用途**：主循环在每个关键时机广播钩子事件。`run()` 内部闭包捕获 `hooks`（可为 `None`）与 `ctx`，调用点只传钩子名；`hooks=None` 时为空操作（M0/M1 行为不变）。
- **最小例子**：
  ```python
  def run(..., hooks: HookManager | None = None) -> str:
      def _emit(hook_name: str) -> None:
          if hooks is not None:
              hooks.emit(hook_name, ctx)
      _emit(Hook.ON_RUN_START)  # 调用点只传钩子名
  ```
- **出现位置**：`kernel/loop.py`。

---

## 7. JSON Schema（工具的 parameters 格式）

- **用途**：工具函数参数的结构化描述，模型根据它决定传什么参数；框架内部 tools.py 用它做参数校验。
- **最小例子**：
  ```json
  {
    "type": "object",
    "properties": {
      "a": {"type": "number"},
      "b": {"type": "number"}
    },
    "required": ["a", "b"]
  }
  ```
- **出现位置**：`kernel/tools.py`（`Tool.parameters`）、示例工具、`openai_compat.py` 渲染 tools 数组。

## 8. OpenAI 工具调用 wire 格式

**请求方向**（把工具规格发给模型）：
```json
{
  "model": "...",
  "messages": [...],
  "tools": [
    {"type": "function", "function": {
      "name": "calculator",
      "description": "...",
      "parameters": { /* 上述 JSON Schema */ }
    }}
  ]
}
```

**响应方向**（模型要求调用工具）：`choices[0].message.tool_calls` 是数组：
```json
[{
  "id": "call_abc123",
  "type": "function",
  "function": {"name": "calculator", "arguments": "{\"a\": 2, \"b\": 3}"}
}]
```
- **`arguments` 是 JSON 字符串**，要 `json.loads` 成 dict。
- **`id` 就是 call_id**：透传厂商值（决策 #10），内核不生成。
- 纯工具调用时 `message.content` 为 `None`，要容忍。
- 模型**不再要求调用**时，`tool_calls` 字段不存在或为空 → 主循环正常返回。

**tool 消息**（把结果喂回模型）：
```json
{"role": "tool", "tool_call_id": "call_abc123", "content": "5"}
```
- OpenAI 没有 is_error 字段 → 出错时在 content 前注明（PROVIDER §2）。
- **出现位置**：`kernel/providers/openai_compat.py`。

## 9. 内部 Message ↔ OpenAI 方言翻译要点

- 内部 `Message.to_dict()` 是**内部序列化**（内容块列表），**不是** wire 格式；OpenAI 请求体由 provider 单独构造——翻译脏活留在 provider 层，内核不感知厂商格式。
- assistant 消息的多个 `ToolCallBlock` → 展开成 `tool_calls` 数组；text 块合并成 content 字符串（没有 text 就留 None）。
- 内部**一对一** tool 消息（一条 = 一个 `ToolResultBlock`）→ OpenAI 每条直接是 `role:tool` + `tool_call_id`（决策 #7 一对一映射，零成本）。
- **出现位置**：`kernel/providers/openai_compat.py`。

## 10. `ast` 安全求值（计算器工具）

- **用途**：对不可信表达式做算术运算。**不要用 `eval`**——任意代码执行漏洞。
- **最小思路**：只放行白名单节点（数字常量 + 加减乘除二元运算），其余节点类型抛异常。
  ```python
  import ast, operator

  OPS = {
      ast.Add: operator.add, ast.Sub: operator.sub,
      ast.Mult: operator.mul, ast.Div: operator.truediv,
  }

  def safe_eval(expr: str) -> float:
      node = ast.parse(expr, mode="eval").body   # 只取表达式主体
      # 递归只允许 Constant / BinOp / UnaryOp，其它节点类型抛 ValueError
  ```
- 校验失败 → 工具返回 `is_error=True`，错误信息喂回模型。
- **出现位置**：示例工具计算器。

## 11. 观察者（Observer）模式（M2 第二步）

- **用途**：钩子回调默认是观察者——**只读** `ctx`、返回 `None`、顺序无关、崩了零影响（防线 2）。内核不依赖回调返回值。
- **最小例子**：
  ```python
  hooks = HookManager()

  def count_iters(ctx):
      print("iteration", ctx.iter_count)  # 只读，不修改 ctx，返回 None

  hooks.register(Hook.ON_ITERATION_START, count_iters, priority=100)
  ```
- **出现位置**：`kernel/hooks.py`、`tests/test_hooks.py`。

## 12. 崩溃隔离（防线 1，M2 第二步）

- **用途**：`emit` 给每个回调包 `try/except`，单个回调抛异常 → 记日志 + 跳过，**其余照常、不掀翻内核**。
- **关键点**：
  - `except Exception`（**不要 catch `BaseException`**）——`KeyboardInterrupt`/`SystemExit` 必须放行（Ctrl-C 优雅退出靠它）。
  - 用 `logger.warning` 记可查信息（hook_name + 回调名 + exc），**绝不 raise**——否则一个崩了又连坐。
  - 回调名用 `getattr(callback, "__name__", callback)`，避免打出每次运行都变的内存地址。
- **出现位置**：`kernel/hooks.py` 的 `HookManager.emit`。
- **注意**：钩子回调自身崩溃由防线 1 兜底，**不触发** `on_error`（否则钩子崩溃引发 on_error、on_error 又是钩子……钩子风暴）。见 HOOKS §5。

## 13. 优先级排序（M2 第一步）

- **用途**：同一钩子点多回调时，`register(priority=...)` 决定调用顺序——数字**升序**（小的先），同优先级按**注册顺序**（`sorted` 稳定），默认 500。
- **最小例子**：
  ```python
  hooks.register(Hook.ON_RUN_START, a, priority=200)
  hooks.register(Hook.ON_RUN_START, b, priority=100)  # b 先于 a 被调用
  ```
- **出现位置**：`kernel/hooks.py` 的 `register` / `emit`。

## 14. 拦截者 / 修改指令模式（M2 第三步）

- **用途**：钩子回调可以**改数据**了——但禁止就地改（不许 `ctx.history = [...]` 直接篡改），必须**返回修改指令**（`Modify`），由内核校验（防线 3）后施加。好处：所有修改经内核之手，"谁、何时、改了什么"可追溯、可拒绝、顺序可控。
- **最小例子**（RAG 注入原型）：
  ```python
  from kernel.hooks import Hook, modify

  def rag_inject(ctx):
      chunks = retrieve(ctx.history[-1])
      return modify([Message.text("user", f"[资料] {chunks}")])

  hooks.register(Hook.BEFORE_MODEL_CALL, rag_inject, priority=100)  # 注入段须在压缩段(200)之前
  ```
- **关键点**：
  - **角色由返回值隐式区分**（决策）：返回 `None` = 观察者，返回 `Modify` = 拦截者，其他返回值 = 脏指令视同非法拒绝。
  - `Modify` 是 frozen dataclass，字段 `append_messages: tuple[Message, ...]`（tuple 防拦截者持有可篡改历史的引用）；构造走 `modify([...])`，list 自动转 tuple。
  - `is_terminal()` 恒 `False`——第四步的 Skip/Halt/Replace 中断指令共用这个接口，`Modify` 是指令家族的一员。
  - **逐个施加**：emit 循环里校验一个施加一个，后面的回调天然看到前面的修改（注入先于压缩的顺序保证，HOOKS §7）。
  - 校验拒绝 = **该拦截者本轮失效**：记 warning 后继续下一个回调，绝不 raise（拒绝路径自身不许炸出 emit，见 HOOKS §7 的 `%s` 教训）。
- **出现位置**：`kernel/hooks.py`（`Modify` / `modify` / `_validate_modify` / `emit`）、`tests/test_hooks.py`。
