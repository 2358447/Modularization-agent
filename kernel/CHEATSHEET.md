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

## 5. `requests` POST OpenAI `/chat/completions`（owner 填 `openai_compat.py` 的 TODO 时用）

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

## 7. `ProviderError` / `APIError`

- **用途**：把 `requests` 的网络/HTTP/JSON 异常统一包成 provider 层异常。内核只认识 `ProviderError`，不用直接处理具体 HTTP 库的细节；未来换 `httpx` 时内核无感。
- **最小例子**：
  ```python
  class ProviderError(Exception): ...
  class APIError(ProviderError): ...

  try:
      resp = requests.post(...)
      resp.raise_for_status()
  except requests.RequestException as exc:
      raise APIError(f"请求失败: {exc}") from exc
  ```
- **出现位置**：`kernel/providers/base.py`、`kernel/providers/openai_compat.py`。

---

## 8. `**kwargs` 透传

- **用途**：`chat(messages, temperature=0.5)` 里的 provider 特定参数通过 `**kwargs` 合并进请求 body。
- **最小例子**：
  ```python
  body = {"model": self.model, "messages": [...]}
  body.update(kwargs)  # 把 temperature / max_tokens 等加进去
  ```
- **出现位置**：`kernel/providers/openai_compat.py`。
- **注意**：M0 不做白名单校验。未来若 provider 对参数敏感，可在这里加校验或过滤。

---

## 9. `ProviderCapability` 能力声明

- **用途**：让 provider 主动声明自己支持哪些能力（chat / stream / tool_use / count_tokens），内核在调用前可先检查，避免把不支持的请求发给 provider。
- **最小例子**：
  ```python
  from enum import Enum, auto

  class ProviderCapability(Enum):
      CHAT = auto()
      STREAM = auto()
      TOOL_USE = auto()
      COUNT_TOKENS = auto()

  class MyProvider(Provider):
      def capabilities(self) -> set[ProviderCapability]:
          return {ProviderCapability.CHAT, ProviderCapability.STREAM}
  ```
- **出现位置**：`kernel/providers/base.py`。

---

## 10. `ConfigurationError` / `UnsupportedCapabilityError`

- **用途**：进一步细分 provider 异常。
  - `ConfigurationError`：配置缺失（如 api_key 为空）。
  - `UnsupportedCapabilityError`：调用了 provider 没声明支持的能力（如让不支持 tool_use 的 provider 执行工具）。
- **最小例子**：
  ```python
  if not self.api_key:
      raise ConfigurationError("OPENAI_API_KEY 未配置")

  if ProviderCapability.TOOL_USE not in self.capabilities():
      raise UnsupportedCapabilityError("本 provider 不支持 tool_use")
  ```
- **出现位置**：`kernel/providers/base.py`、`kernel/providers/openai_compat.py`（未来可补充校验）。

---

## 11. `count_tokens` 占位

- **用途**：估算消息 token 数，用于预算模块或上下文溢出检测。M0 默认抛出 `UnsupportedCapabilityError`，子类可覆盖。
- **最小例子**：
  ```python
  def count_tokens(self, messages: list[Message]) -> int:
      raise UnsupportedCapabilityError("未实现")
  ```
- **出现位置**：`kernel/providers/base.py`。
