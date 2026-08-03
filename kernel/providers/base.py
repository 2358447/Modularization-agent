"""Provider 抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from kernel.message import Message, ToolCallBlock
from kernel.tools import Tool


@dataclass
class Response:
    """模型返回的标准化响应。

    Attributes:
        content: 文本回复。模型只回工具调用时可为 None（纯工具调用无文本）。
        tool_calls: 模型要求调用的工具列表（零个 = 正常回答）。
        usage: token 用量，形如 {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}。
        model: 模型名称。
        finish_reason: 结束原因，例如 "stop"。
    """

    content: str | None = None
    tool_calls: list[ToolCallBlock] | None = None
    usage: dict | None = None
    model: str | None = None
    finish_reason: str | None = None


class APIError(Exception):
    """Provider 调用过程中的请求或解析错误。"""


class Provider(ABC):
    """统一大模型调用接口。内核只依赖此接口。"""

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        **kwargs,
    ) -> Response:
        """给定历史消息和可用工具，返回模型下一步响应。

        Args:
            messages: 已发生的对话历史。
            tools: 可用工具列表，provider 负责渲染成厂商 schema；None 或空 =
                纯对话（不声明工具）。M1 首次引入。
            **kwargs: provider 特定参数，M0 保留扩展性。

        Returns:
            Response：文本 + 零个或多个 tool_calls。
            返回的 ToolCallBlock.call_id 透传厂商值（决策 #10），内核不生成。
        """
        raise NotImplementedError
