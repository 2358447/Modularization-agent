"""Provider 抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from kernel.message import Message


@dataclass
class Response:
    """模型返回的标准化响应。

    Attributes:
        content: 文本回复。M0 只支持文本。
        usage: token 用量，形如 {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}。
        model: 模型名称。
        finish_reason: 结束原因，例如 "stop"。
    """

    content: str
    usage: dict | None = None
    model: str | None = None
    finish_reason: str | None = None


class ProviderError(Exception):
    """Provider 层错误基类。

    所有 provider 实现都应抛出此类或其子类，让内核可以用一条 except
    统一捕获，而不用关心具体是 requests、httpx 还是其他库抛出的异常。
    """


class APIError(ProviderError):
    """远程 API 调用失败，或返回了无法解析/结构异常的响应。"""


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
