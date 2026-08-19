"""openai_compat 翻译测试：请求方向（内部 Message → OpenAI wire）+ 响应方向（wire → Response）。

翻译是 provider 层的职责（PROVIDER §2），测试覆盖：
- _to_openai_messages：四种角色如何落到 wire（含 is_error 前缀、tool_calls 展开、arguments JSON 字符串）
- _to_openai_tools：Tool 三字段如何包成 function 结构
- _parse_choice：content 可 None、tool_calls 解析、畸形 arguments 抛 APIError
"""

from __future__ import annotations

import pytest

from kernel.message import Message, TextBlock, ToolCallBlock, ToolResultBlock
from kernel.providers.base import APIError
from kernel.providers.openai_compat import OpenAICompat
from kernel.tools import Tool


# ---------- 请求方向：_to_openai_messages ----------

def test_system_and_user_joined_text():
    msgs = [Message.text("system", "你是助手"), Message.text("user", "你好")]
    wire = OpenAICompat._to_openai_messages(msgs)
    assert wire == [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "你好"},
    ]


def test_assistant_content_none_without_text():
    """assistant 无文本块 → wire 的 content 为 None（模型可容忍）。"""
    msg = Message(role="assistant", content=[])
    assert OpenAICompat._to_openai_messages([msg]) == [
        {"role": "assistant", "content": None},
    ]


def test_assistant_tool_calls_expanded():
    """一条内部消息的多个 ToolCallBlock 展开成 wire 的 tool_calls 数组，arguments 变 JSON 字符串。"""
    msg = Message(role="assistant", content=[
        TextBlock(text="我要算"),
        ToolCallBlock(call_id="c1", name="calculator", arguments={"expression": "1+1"}),
    ])
    assert OpenAICompat._to_openai_messages([msg]) == [{
        "role": "assistant",
        "content": "我要算",
        "tool_calls": [{
            "id": "c1",
            "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'},
        }],
    }]


def test_tool_message_error_prefix():
    """is_error=True 时 content 前加 [错误] 前缀（OpenAI 无 is_error 字段）。"""
    msg = Message(role="tool", content=[ToolResultBlock(call_id="c1", content="炸了", is_error=True)])
    assert OpenAICompat._to_openai_messages([msg]) == [
        {"role": "tool", "tool_call_id": "c1", "content": "[错误] 炸了"},
    ]


def test_tool_message_success_no_prefix():
    msg = Message(role="tool", content=[ToolResultBlock(call_id="c1", content="14")])
    assert OpenAICompat._to_openai_messages([msg]) == [
        {"role": "tool", "tool_call_id": "c1", "content": "14"},
    ]


# ---------- 请求方向：_to_openai_tools ----------

def test_to_openai_tools_wraps_schema():
    tool = Tool(
        name="add",
        description="加法",
        parameters={"type": "object", "properties": {"a": {"type": "number"}}, "required": ["a"]},
        func=lambda a: a,
    )
    assert OpenAICompat._to_openai_tools([tool]) == [{
        "type": "function",
        "function": {
            "name": "add",
            "description": "加法",
            "parameters": tool.parameters,   # JSON Schema 原样透传
        },
    }]


# ---------- 响应方向：_parse_choice ----------

def test_parse_choice_plain_text():
    choice = {"message": {"content": "你好"}, "finish_reason": "stop"}
    data = {"usage": {"total_tokens": 10}, "model": "gpt-x"}
    resp = OpenAICompat._parse_choice(choice, data)
    assert resp.content == "你好"
    assert resp.tool_calls is None           # 无工具调用
    assert resp.usage == {"total_tokens": 10}
    assert resp.model == "gpt-x"


def test_parse_choice_content_none_with_tool_calls():
    """纯工具调用：content 为 None，tool_calls 解析成 ToolCallBlock，call_id 透传厂商值。"""
    choice = {
        "message": {
            "content": None,
            "tool_calls": [{
                "id": "call_abc",
                "type": "function",
                "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'},
            }],
        },
        "finish_reason": "tool_calls",
    }
    resp = OpenAICompat._parse_choice(choice, {})
    assert resp.content is None
    assert resp.tool_calls is not None
    call = resp.tool_calls[0]
    assert call.call_id == "call_abc"        # 透传，不重新生成
    assert call.name == "calculator"
    assert call.arguments == {"expression": "1+1"}   # JSON 字符串被解析成 dict


def test_parse_choice_malformed_arguments_raises_api_error():
    """arguments 不是合法 JSON：畸形响应，抛 APIError 让错误大声说话。"""
    choice = {
        "message": {
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "calculator", "arguments": "不是json{"},
            }],
        },
    }
    with pytest.raises(APIError):
        OpenAICompat._parse_choice(choice, {})
