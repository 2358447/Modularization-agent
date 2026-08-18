"""极简主循环：ReAct 循环（对话 + 工具调用多轮迭代）。

M0 是单次调用（说一句回一句）；M1 升级为真循环：
模型要求调工具 → 执行 → 结果回灌 → 再看模型 → …直到模型直接回答。
加上 max_iter 安全阀，防止模型陷入死循环。
"""

from __future__ import annotations

import os

from kernel.context import Context
from kernel.hooks import Hook
from kernel.message import Message, TextBlock
from kernel.providers.base import APIError, Provider, Response
from kernel.tools import ToolRegistry


# 内核默认 system prompt；可被环境变量覆盖，也可由调用方传入。
DEFAULT_SYSTEM_PROMPT = os.environ.get(
    "AGENT_SYSTEM_PROMPT",
    "You are a helpful assistant.",
)


class MaxIterationsError(Exception):
    """单次 run 超过最大迭代次数（安全阀触发，强制停止）。"""


def _emit(hook_name: str, ctx: Context) -> None:
    """M0 空广播占位。M1 保留，M2 接入 HookManager。"""
    # TODO: M2 接入 HookManager，遍历并调用对应 hook_name 的监听器。
    pass


def _assistant_message(response: Response) -> Message:
    """把模型的 Response 转成内部 assistant 消息（text 块 + tool_call 块）。

    content 非空 → 加 TextBlock；response.tool_calls（已是 ToolCallBlock
    对象）直接并入 content 块列表。一条消息同时装文字和多个工具请求。
    """
    if response.content is not None:
        content_blocks = [TextBlock(text=response.content)]
    else:
        content_blocks = []
    if response.tool_calls is not None:
        content_blocks.extend(response.tool_calls)
    return Message(role="assistant", content=content_blocks)


def run(
    user_input: str,
    ctx: Context,
    provider: Provider,
    tools: ToolRegistry | None = None,
    system_prompt: str | None = None,
) -> str:
    """运行一次用户输入 → 模型回复的循环（可调用工具多轮迭代）。

    Args:
        user_input: 用户输入文本。
        ctx: 当前上下文。
        provider: provider 实例。
        tools: 可选工具注册表；传了则把工具规格交给模型，模型可要求调用。
        system_prompt: 可选，覆盖默认 system prompt。

    Returns:
        模型最终文本回复。

    Raises:
        APIError: provider 调用失败（本轮已回滚到 run 开始时状态）。
        MaxIterationsError: 迭代超过 max_iter 安全阀。
    """
    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    # 首次运行时注入 system prompt；若历史已存在则不覆盖。
    if not ctx.history:
        ctx.history.insert(0, Message.text("system", system_prompt))
    history_len = len(ctx.history)
    ctx.history.append(Message.text("user", user_input))

    # 快照：出错时回滚到 run 开始时的状态（撤销本轮追加的全部消息）
    start_iter = ctx.iter_count

    _emit(Hook.ON_RUN_START, ctx)

    while True:
        if ctx.iter_count >= ctx.max_iter:
            raise MaxIterationsError(f"超过最大迭代次数 {ctx.max_iter}")
        ctx.iter_count += 1

        _emit(Hook.ON_ITERATION_START, ctx)
        _emit(Hook.BEFORE_MODEL_CALL, ctx)
        try:
            response = provider.chat(
                ctx.history,
                tools=tools.list_specs() if tools else None,
            )
        except APIError:
            # 快照回滚：截断 history 到 history_len、iter_count 归位到
            # start_iter，然后 re-raise。覆盖多轮循环中间出错的情况。
            ctx.history = ctx.history[:history_len]
            ctx.iter_count = start_iter

            raise
        _emit(Hook.AFTER_MODEL_CALL, ctx)

        ctx.history.append(_assistant_message(response))

        if not response.tool_calls:
            # 模型直接回答了，本轮结束
            _emit(Hook.ON_ITERATION_END, ctx)
            _emit(Hook.ON_RUN_END, ctx)
            return response.content or ""

        # 多工具串行执行（HOOKS §C）：每个工具独立走 before/after 钩子；
        # 结果先收齐，再一起塞回历史（一对一粒度，靠 call_id 配对）。
        results = []
        for call in response.tool_calls:
            _emit(Hook.BEFORE_TOOL_CALL, ctx)
            result = tools.call(call.call_id, call.name, call.arguments)
            _emit(Hook.AFTER_TOOL_CALL, ctx)
            results.append(result)

        for result in results:
            ctx.history.append(Message(role="tool", content=[result]))

        _emit(Hook.ON_ITERATION_END, ctx)
        # 循环继续：下一轮迭代
