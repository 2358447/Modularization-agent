"""kernel.loop.run() 的最小测试：不联网，用 FakeProvider 模拟模型。"""

from __future__ import annotations

import pytest

from kernel.context import Context
from kernel.loop import run
from kernel.message import Message
from kernel.providers.base import APIError, Provider, Response


class FakeProvider(Provider):
    """可控回复 / 可控抛错的假 provider。

    用法：
        FakeProvider()                    # 永远回 "ok"
        FakeProvider(reply="你好")         # 永远回 "你好"
        FakeProvider(error=APIError(...)) # chat() 时抛错
    """

    def __init__(self, reply: str = "ok", error: APIError | None = None) -> None:
        self.reply = reply
        self.error = error

    def chat(self, messages: list[Message], **kwargs) -> Response:
        if self.error is not None:
            raise self.error
        return Response(content=self.reply)


def test_first_run_injects_system_prompt():
    """空历史首次 run：system 在最前，且只注入一次。"""
    ctx = Context()
    result = run("hello", ctx, FakeProvider(reply="hi"))

    assert result == "hi"
    assert [m.role for m in ctx.history] == ["system", "user", "assistant"]
    assert ctx.history[0].content == "You are a helpful assistant."


def test_does_not_reinject_system_prompt():
    """连续两次 run，system 只出现一次（二次 run 时历史非空，不再注入）。"""
    ctx = Context()
    run("first", ctx, FakeProvider())
    run("second", ctx, FakeProvider())

    assert [m.role for m in ctx.history] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_appends_user_and_assistant_after_reply():
    """一次 run 后历史末尾应为 user → assistant。"""
    ctx = Context()
    run("hello", ctx, FakeProvider(reply="hi"))

    assert ctx.history[-2].role == "user"
    assert ctx.history[-2].content == "hello"
    assert ctx.history[-1].role == "assistant"
    assert ctx.history[-1].content == "hi"


def test_system_prompt_override():
    """显式传入 system_prompt 覆盖默认值。"""
    ctx = Context()
    run("hi", ctx, FakeProvider(), system_prompt="你是助手")

    assert ctx.history[0].role == "system"
    assert ctx.history[0].content == "你是助手"


def test_api_error_rolls_back_history():
    """provider 抛 APIError：user 消息被撤销、iter_count 回滚、异常上抛。"""
    ctx = Context()

    with pytest.raises(APIError):
        run("hello", ctx, FakeProvider(error=APIError("boom")))

    # 首次失败：system 已注入并保留（会话固定前导），user 被撤掉。
    assert [m.role for m in ctx.history] == ["system"]
    assert ctx.iter_count == 0

    # 换正常 provider 继续：历史从 [system] 接着走，无孤儿、无重复。
    run("recover", ctx, FakeProvider(reply="ok"))
    assert [m.role for m in ctx.history] == ["system", "user", "assistant"]
