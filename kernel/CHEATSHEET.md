# kernel/ 技术盲区速查

用途：owner 在实现 M0 kernel 时可能不熟的技术点。

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

## 6. 空钩子广播 `_emit`

- **用途**：M0 不实现 HookManager，但要让主循环的关键位置可见，M1 直接替换函数体。
- **最小例子**：
  ```python
  def _emit(hook_name: str, ctx: Context) -> None:
      pass  # M1 替换为 hook_manager.emit(hook_name, ctx)
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
