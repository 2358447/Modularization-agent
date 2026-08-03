"""统一消息协议：content 为内容块列表。

M1 落地 MESSAGE_PROTOCOL §2 的关键决策——content 统一为内容块列表，
一条 assistant 消息可同时承载思考文本 + 多个工具调用（裸字符串装不下）。
纯文本消息是"单个 text 块"的列表，结构统一。

块类型带显式 type 字段（MESSAGE_PROTOCOL §6），未来新增块类型（image/
citation 等）不破坏旧数据解析。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------- 内容块类型 ----------

@dataclass
class TextBlock:
    """纯文本块。"""

    type: str = "text"
    text: str = ""


@dataclass
class ToolCallBlock:
    """一次工具调用请求（由模型产生）。

    call_id 透传厂商值（决策 #10）：OpenAI 的 tool_call.id / Anthropic 的
    tool_use.id，内核不生成。与对应 ToolResultBlock 靠 call_id 配对。
    """

    type: str = "tool_call"
    call_id: str = ""
    name: str = ""
    arguments: dict = field(default_factory=dict)


@dataclass
class ToolResultBlock:
    """一次工具调用的结果或错误（由工具执行后内核产生）。"""

    type: str = "tool_result"
    call_id: str = ""
    content: str = ""
    is_error: bool = False


# 内容块联合类型。序列化两个方向用不同的钥匙：对象→字典用 isinstance
# （对象自带类型，最稳）；字典→对象没有对象可认，只能按 type 字符串字段。
Block = TextBlock | ToolCallBlock | ToolResultBlock


# ---------- 块序列化 ----------

def block_to_dict(block: Block) -> dict:
    """内容块 → dict。例：TextBlock → {"type": "text", "text": "..."}。

    未知类型抛 ValueError（与 block_from_dict 对称，让错误大声暴露而非静默 None）。
    """
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    elif isinstance(block, ToolCallBlock):
        return {
            "type": "tool_call",
            "call_id": block.call_id,
            "name": block.name,
            "arguments": block.arguments,
        }
    elif isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "call_id": block.call_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    else:
        raise ValueError(f"未知的块类型: {type(block)}")


def block_from_dict(data: dict) -> Block:
    """dict → 内容块。

    按 data["type"] 分发反序列化；未知 type 抛 ValueError，给未来新增块类型留兜底。
    """
    if data["type"] == "text":
        return TextBlock(text=data.get("text", ""))
    elif data["type"] == "tool_call":
        return ToolCallBlock(
            call_id=data.get("call_id", ""),
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
        )
    elif data["type"] == "tool_result":
        return ToolResultBlock(
            call_id=data.get("call_id", ""),
            content=data.get("content", ""),
            is_error=data.get("is_error", False),
        )
    else:
        raise ValueError(f"未知的块类型: {data['type']}")


# ---------- 消息 ----------

@dataclass
class Message:
    """一次对话消息。

    Attributes:
        role: 说话人角色。取值 system / user / assistant / tool。
        content: 内容块列表。纯文本消息是 [TextBlock(...)]。
    """

    role: str
    content: list[Block] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为内部格式（块列表），供测试/持久化使用。

        注意：这是内部序列化，不是 OpenAI wire 格式；wire 翻译在 provider 层。
        """
        return {"role": self.role, "content": [block_to_dict(b) for b in self.content]}

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        """从内部格式反序列化（to_dict 的逆操作，往返无损）。"""
        return cls(
            role=data["role"],
            content=[block_from_dict(b) for b in data.get("content", [])],
        )

    @staticmethod
    def text(role: str, text: str) -> "Message":
        """便捷构造纯文本消息，免得调用方到处写 [TextBlock(...)]。"""
        return Message(role=role, content=[TextBlock(text=text)])
