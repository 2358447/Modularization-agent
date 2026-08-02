"""极简主循环：纯对话模式。"""

from __future__ import annotations

import os

from kernel.context import Context
from kernel.hooks import Hook
from kernel.message import Message
from kernel.providers.base import APIError, Provider


# 内核默认 system prompt；可被环境变量覆盖，也可由调用方传入。
DEFAULT_SYSTEM_PROMPT = os.environ.get(
    "AGENT_SYSTEM_PROMPT",
    "You are a helpful assistant.",
)


def _emit(hook_name: str, ctx: Context) -> None:
    """M0 空广播占位。M1 替换为 HookManager.emit。"""
    # TODO: M1 接入 HookManager，遍历并调用对应 hook_name 的监听器。
    pass


def run(
    user_input: str,
    ctx: Context,
    provider: Provider,
    system_prompt: str | None = None,
) -> str:
    """运行一次用户输入 → 模型回复的循环。

    M0 纯对话：没有 tool 调用，没有多轮迭代（一次 LLM 调用即返回）。

    Args:
        user_input: 用户输入文本。
        ctx: 当前上下文。
        provider: provider 实例。
        system_prompt: 可选，覆盖默认 system prompt。

    Returns:
        模型文本回复。
    """
    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    _emit(Hook.ON_RUN_START, ctx)

    # 首次运行时注入 system prompt；若历史已存在则不覆盖。
    if not ctx.history:
        ctx.history.insert(0, Message(role="system", content=system_prompt))

    ctx.history.append(Message(role="user", content=user_input))
    ctx.iter_count += 1

    _emit(Hook.ON_ITERATION_START, ctx)
    _emit(Hook.BEFORE_MODEL_CALL, ctx)
    try:
        response = provider.chat(ctx.history)
    except APIError as exc:
        ctx.history.pop()  # 移除最后一条用户消息，避免重复
        ctx.iter_count -= 1
        raise

    _emit(Hook.AFTER_MODEL_CALL, ctx)

    assistant_message = Message(role="assistant", content=response.content)
    ctx.history.append(assistant_message)

    _emit(Hook.ON_ITERATION_END, ctx)
    _emit(Hook.ON_RUN_END, ctx)

    return response.content
