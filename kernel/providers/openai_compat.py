"""OpenAI 兼容 provider。

支持任何提供 OpenAI /chat/completions 接口的服务。
M1 补工具调用翻译：
- 请求方向：内部 Message → OpenAI wire 格式（含 tools 数组渲染）。
- 响应方向：OpenAI 响应 → 内部 Response（解析 tool_calls，arguments 是 JSON 字符串）。

厂商差异（字段名、结构、is_error 表示）全部吸收在本层，内核不感知。
"""

from __future__ import annotations

import json
import os

import requests

from kernel.message import Message, TextBlock, ToolCallBlock, ToolResultBlock
from kernel.providers.base import APIError, Provider, Response
from kernel.tools import Tool


class OpenAICompat(Provider):
    """OpenAI 兼容 provider 实现。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        **kwargs,
    ) -> Response:
        """调用 OpenAI 兼容 /chat/completions 接口。

        请求方向：内部 Message → OpenAI wire（_to_openai_messages），有工具时
        渲染 tools 数组（_to_openai_tools）。响应方向：_parse_choice 解析出
        content（可 None）+ tool_calls，透传厂商 call_id。
        """
        body = {
            "model": self.model,
            "messages": self._to_openai_messages(messages),
        }
        if tools:
            body["tools"] = self._to_openai_tools(tools)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise APIError(f"OpenAI 兼容 provider 请求失败: {exc}") from exc
        except ValueError as exc:
            raise APIError(f"OpenAI 兼容 provider 返回非 JSON: {exc}") from exc

        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise APIError(f"OpenAI 兼容 provider 返回结构异常: {exc}") from exc

        return self._parse_choice(choice, data)

    # ---------- 请求方向：内部 Message → OpenAI wire ----------

    @staticmethod
    def _to_openai_messages(messages: list[Message]) -> list[dict]:
        """内部 Message → OpenAI wire 消息数组。要点见 CHEATSHEET §9：

        - system/user：content 用文本块的拼接字符串。
        - assistant：content = 文本（无文本则 None）；有 tool_call 块时展开成
          [{"id": call_id, "type": "function", "function": {"name": ...,
          "arguments": <JSON 字符串>}}]。
        - tool：{"role": "tool", "tool_call_id": call_id, "content": ...}，
          is_error=True 时 content 前加 "[错误] " 注明（OpenAI 无 is_error 字段）。
        """
        messages_list = []
        for message in messages:
            # 从 content 里提取文本（只拼 TextBlock 的 text；没有文本块则 None）
            text_blocks = [b.text for b in message.content if isinstance(b, TextBlock)]
            text = "\n".join(text_blocks) if text_blocks else None

            if message.role == "tool":
                # tool 消息只有一块 ToolResultBlock，取它自己的 content 字段
                result = message.content[0]
                content = result.content
                if result.is_error:
                    content = "[错误] " + content  # OpenAI 无 is_error 字段，写进文本
                wire = {"role": "tool", "tool_call_id": result.call_id, "content": content}

            elif message.role == "assistant":
                wire = {"role": "assistant", "content": text}
                # 从 content 里筛出所有 ToolCallBlock，展开成 tool_calls 数组
                call_blocks = [b for b in message.content if isinstance(b, ToolCallBlock)]
                if call_blocks:
                    wire["tool_calls"] = [
                        {
                            "id": b.call_id,
                            "type": "function",
                            "function": {
                                "name": b.name,
                                "arguments": json.dumps(b.arguments),
                            },
                        }
                        for b in call_blocks
                    ]

            else:  # system / user
                wire = {"role": message.role, "content": text}

            messages_list.append(wire)
        return messages_list


    @staticmethod
    def _to_openai_tools(tools: list[Tool]) -> list[dict]:
        """渲染 tools 数组：[{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]。

        直接复用 Tool 的 name/description/parameters 三个字段（CHEATSHEET §8）。
        """
        # TODO
        tools_list = []
        for tool in tools:
            tools_list.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            })
        return tools_list

    # ---------- 响应方向：OpenAI wire → 内部 Response ----------

    @staticmethod
    def _parse_choice(choice: dict, data: dict) -> Response:
        """OpenAI 响应 → 内部 Response（CHEATSHEET §8 响应方向）。

        TODO:
        - content = choice["message"].get("content")，纯工具调用时是 None，别炸。
        - tool_calls = choice["message"].get("tool_calls")，可能缺省（无工具调用）。
          每个：call_id=item["id"]（透传厂商值，决策 #10）、
          name=item["function"]["name"]、arguments=json.loads(JSON 字符串)。
          ——JSON 解析失败怎么处理？建议抛 APIError（畸形响应，让错误大声说话）。
        - 组装 Response(content, tool_calls or None, usage, model, finish_reason)。
        """
        # TODO
        content = choice["message"].get("content")
        tool_calls = []
        for item in choice["message"].get("tool_calls", []):
            try:
                arguments = json.loads(item["function"]["arguments"])
            except json.JSONDecodeError as exc:
                raise APIError(f"OpenAI 兼容 provider 返回畸形工具调用参数: {exc}") from exc
            tool_calls.append(ToolCallBlock(
                call_id=item["id"],
                name=item["function"]["name"],
                arguments=arguments
            ))
        return Response(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage=data.get("usage"),
            model=data.get("model"),
            finish_reason=choice.get("finish_reason"),
        )
