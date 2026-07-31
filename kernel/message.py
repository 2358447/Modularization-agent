"""统一消息协议的最小实现（M0 文本版）。

未来 M1/M2 会扩展 content 为 content_parts、tool_calls、tool_results。
M0 只支持 role + 纯文本 content。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Message:
    """一次对话消息。

    Attributes:
        role: 说话人角色。取值 system / user / assistant / tool。
        content: 文本内容。M0 仅支持纯字符串。
    """

    role: str
    content: str

    def to_dict(self) -> dict:
        """序列化为 provider 易消费的 dict。"""
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        """从 dict 反序列化。"""
        return cls(role=data["role"], content=data["content"])
