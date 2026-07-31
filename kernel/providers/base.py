"""Provider 抽象基类。

内核只通过 Provider 接口与具体模型商交互。所有厂商差异（OpenAI/Anthropic/Ollama 等）
都收敛在各自的 Provider 实现里，内核、CLI、测试代码不依赖任何具体 SDK。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto

from kernel.message import Message


class ProviderCapability(Enum):
    """Provider 声明自身支持的能力。

    内核在调用 provider 的某些功能前，应先检查 capabilities()，
    避免把 tool_calls 发给不支持的 provider，或在 M1 流式模块挂载前确认支持 STREAM。
    """

    CHAT = auto()          # 普通对话（M0 最低要求）
    STREAM = auto()        # 流式返回
    TOOL_USE = auto()      # 工具调用
    COUNT_TOKENS = auto()  # 估算 token 用量


@dataclass
class Response:
    """模型返回的标准化响应。

    Attributes:
        content: 文本回复。M0 只支持文本；M1 可能为空（当存在 tool_calls 时）。
        usage: token 用量，形如 {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}。
        model: 模型名称。
        finish_reason: 结束原因，例如 "stop"、"tool_calls"。
    """

    content: str
    usage: dict | None = None
    model: str | None = None
    finish_reason: str | None = None


class ProviderError(Exception):
    """Provider 层错误基类。

    所有 provider 实现都应抛出此类或其子类，让内核可以用一条 except
    统一捕获，而不用关心底层是 requests、httpx 还是其他库。
    """


class ConfigurationError(ProviderError):
    """Provider 配置缺失或非法，例如 api_key 为空、base_url 格式错误。"""


class APIError(ProviderError):
    """远程 API 调用失败，或返回了无法解析/结构异常的响应。"""


class UnsupportedCapabilityError(ProviderError):
    """Provider 不支持被请求的能力，例如向不支持 tool_use 的 provider 发 tool 消息。"""


class Provider(ABC):
    """统一大模型调用接口。内核只依赖此接口。"""

    @abstractmethod
    def chat(self, messages: list[Message], **kwargs) -> Response:
        """给定历史消息，返回模型下一步响应。

        Args:
            messages: 已发生的对话历史。
            **kwargs: provider 特定参数（温度、模型名等）。

        Returns:
            标准化后的 Response。

        Raises:
            ProviderError: 当 provider 调用出现不可恢复错误时抛出。
        """
        raise NotImplementedError

    def capabilities(self) -> set[ProviderCapability]:
        """声明本 provider 支持的能力集合。

        默认只支持普通 chat。子类若支持流式、工具调用或 token 计数，应覆盖此方法。

        Returns:
            支持的能力集合。
        """
        return {ProviderCapability.CHAT}

    def count_tokens(self, messages: list[Message]) -> int:
        """估算给定消息的 token 数。

        M0 默认未实现。子类若支持 COUNT_TOKENS 能力，应覆盖此方法。

        Args:
            messages: 要估算的消息列表。

        Returns:
            token 总数。

        Raises:
            UnsupportedCapabilityError: 默认实现直接抛出，表示本 provider 不支持。
        """
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} 未实现 count_tokens"
        )
