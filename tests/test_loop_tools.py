"""loop 工具循环测试：模型发 tool_calls → 工具执行 → 结果回灌 → 模型继续，直到直接回答。

用假 provider 按脚本返回响应（不联网），验证：
- 一次工具调用闭环：assistant 请求 → tool 结果（call_id 配对）→ 最终回答
- 工具失败（is_error）也正常回灌，主循环不崩
- max_iter 安全阀在模型无限要求调工具时强制停止
"""

from __future__ import annotations

import pytest

from kernel.context import Context
from kernel.loop import MaxIterationsError, run
from kernel.message import ToolCallBlock
from kernel.providers.base import Provider, Response
from kernel.tools import Tool, ToolRegistry


def _echo_registry() -> ToolRegistry:
    """注册一个 echo 工具（参数原样返回），供各测试复用。"""
    reg = ToolRegistry()
    reg.register(Tool(
        name="echo",
        description="把 text 原样返回",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        func=lambda text: text,
    ))
    return reg


class ScriptedProvider(Provider):
    """按脚本返回：第一次调用要求调 echo 工具，第二次给出最终回答。"""

    def __init__(self, arguments=None, final_reply="done"):
        self.arguments = arguments or {"text": "hello"}
        self.final_reply = final_reply
        self.calls = 0

    def chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            # 纯工具调用：无文本，只有一张工具申请单
            return Response(
                content=None,
                tool_calls=[ToolCallBlock(call_id="c1", name="echo", arguments=self.arguments)],
            )
        return Response(content=self.final_reply)


def test_loop_runs_tool_then_answers():
    """模型先要求调工具 → 结果回灌 → 再回答。验证完整 ReAct 一轮。"""
    ctx = Context()
    result = run("hi", ctx, ScriptedProvider(), tools=_echo_registry())

    assert result == "done"
    # 历史：system, user, assistant(工具请求), tool(结果), assistant(回答)
    assert [m.role for m in ctx.history] == ["system", "user", "assistant", "tool", "assistant"]

    assistant_req = ctx.history[2].content[0]   # ToolCallBlock
    tool_result = ctx.history[3].content[0]     # ToolResultBlock
    assert isinstance(assistant_req, ToolCallBlock)
    assert assistant_req.call_id == tool_result.call_id   # 请求—结果配对
    assert tool_result.content == "hello"
    assert not tool_result.is_error


def test_loop_feeds_tool_error_back_to_model():
    """工具崩溃产生 is_error 结果，也照常回灌，主循环不崩、模型继续。"""
    def boom(text):
        raise RuntimeError("echo 崩了")

    reg = ToolRegistry()
    reg.register(Tool(
        name="echo",
        description="回显",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        func=boom,
    ))

    ctx = Context()
    result = run("hi", ctx, ScriptedProvider(), tools=reg)

    assert result == "done"
    tool_result = ctx.history[3].content[0]
    assert tool_result.is_error
    assert "工具执行出错" in tool_result.content


class InfiniteToolProvider(Provider):
    """永远要求调工具的 provider，用于触发 max_iter 安全阀。"""

    def chat(self, messages, tools=None, **kwargs):
        return Response(content=None, tool_calls=[ToolCallBlock(call_id="c1", name="echo", arguments={"text": "x"})])


def test_loop_max_iter_safety_valve():
    """模型无限要调工具 → max_iter 安全阀强制停止，抛 MaxIterationsError。"""
    ctx = Context()
    ctx.max_iter = 3
    with pytest.raises(MaxIterationsError):
        run("hi", ctx, InfiniteToolProvider(), tools=_echo_registry())
