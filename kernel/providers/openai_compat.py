"""OpenAI 兼容 provider。

支持任何提供 OpenAI /chat/completions 接口的服务。
"""

from __future__ import annotations

import os

from kernel.message import Message
from kernel.providers.base import Provider, Response


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

    def chat(self, messages: list[Message], **kwargs) -> Response:
        """TODO: 实现真实 HTTP 调用。

        M0 骨架阶段返回固定 stub，便于端到端 hello-world。
        """
        # TODO: import requests
        # TODO: POST {self.base_url}/chat/completions
        # TODO: 构造 body：model + messages（调用每个 Message.to_dict()）
        # TODO: parse JSON，提取 choices[0].message.content
        # TODO: return Response(content=..., usage=..., model=..., finish_reason=...)
        return Response(
            content="hello from stub",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            model=self.model,
            finish_reason="stop",
        )
