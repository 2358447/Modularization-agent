"""OpenAI 兼容 provider。

支持任何提供 OpenAI /chat/completions 接口的服务。
"""

from __future__ import annotations

import os

import requests

from kernel.message import Message
from kernel.providers.base import APIError, Provider, Response


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
        """调用 OpenAI 兼容 /chat/completions 接口。

        Args:
            messages: 对话历史。
            **kwargs: 暂时保留，M0 不使用。

        Returns:
            标准化后的 Response。
        """
        messages_dicts = [x.to_dict() for x in messages]
        body = {
            "model": self.model,
            "messages": messages_dicts,
        }

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
            reply_content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise APIError(f"OpenAI 兼容 provider 返回结构异常: {exc}") from exc

        return Response(
            content=reply_content,
            usage=data.get("usage"),
            model=data.get("model"),
            finish_reason=choice.get("finish_reason"),
        )

