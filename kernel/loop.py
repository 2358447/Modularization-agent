"""极简主循环：ReAct 循环（对话 + 工具调用多轮迭代）。

M0 是单次调用（说一句回一句）；M1 升级为真循环：
模型要求调工具 → 执行 → 结果回灌 → 再看模型 → …直到模型直接回答。
加上 max_iter 安全阀，防止模型陷入死循环。
"""

from __future__ import annotations

import os

from kernel.context import Context
from kernel.hooks import Directive, Halt, Hook, HookManager, Replace, Skip
from kernel.message import Message, TextBlock, ToolResultBlock
from kernel.providers.base import APIError, Provider, Response
from kernel.tools import ToolRegistry


# 内核默认 system prompt；可被环境变量覆盖，也可由调用方传入。
DEFAULT_SYSTEM_PROMPT = os.environ.get(
    "AGENT_SYSTEM_PROMPT",
    "You are a helpful assistant.",
)


class MaxIterationsError(Exception):
    """单次 run 超过最大迭代次数（安全阀触发，强制停止）。"""


class RunHalted(Exception):
    """拦截者 HALT 终止 run（§D）。不回滚历史——占位补全后历史合法可续跑。"""


def _assistant_message(response: Response) -> Message:
    """把模型的 Response 转成内部 assistant 消息（text 块 + tool_call 块）。

    content 非空 → 加 TextBlock；response.tool_calls（已是 ToolCallBlock
    对象）直接并入 content 块列表。一条消息同时装文字和多个工具请求。
    """
    if response.content:
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
    hooks: HookManager | None = None,
) -> str:
    """运行一次用户输入 → 模型回复的循环（可调用工具多轮迭代）。

    Args:
        user_input: 用户输入文本。
        ctx: 当前上下文。
        provider: provider 实例。
        tools: 可选工具注册表；传了则把工具规格交给模型，模型可要求调用。
        system_prompt: 可选，覆盖默认 system prompt。
        hooks: 可选 HookManager；传了则每个关键时机广播钩子事件。
            None（默认）时全部为空操作，行为与 M0/M1 完全一致。

    Returns:
        模型最终文本回复。

    Raises:
        APIError: provider 调用失败（本轮已回滚到 run 开始时状态）。
        MaxIterationsError: 迭代超过 max_iter 安全阀。
        RunHalted: 拦截者发出 HALT（历史已补全占位、保持合法可续跑）。
    """
    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    # 钩子广播入口（决策 #12：hooks 作 run() 参数）。M2 第四步：返回终止意图；
    # Halt 默认就地 raise，工具批次中途两点传 halt_raises=False（先补占位再抛）。
    def _emit(hook_name: str, *, halt_raises: bool = True) -> Directive | None:
        """广播钩子事件；返回终止意图（无则 None）。"""
        directive = hooks.emit(hook_name, ctx) if hooks is not None else None
        # TODO(M2 第四步·owner)：halt_raises 且是 Halt → raise RunHalted(reason)
        return directive

    def _halt_tool_batch(
        executed_results: list[ToolResultBlock],
        remaining_calls: list,
        reason: str,
    ) -> None:
        """HALT 落在批次中途：已执行结果入历史 → 未执行 calls 补
        tool_result(is_error=True, content="aborted: run halted") 占位
        （配对完整、可续跑）→ raise RunHalted(reason)。

        remaining_calls 含触发 HALT 的当前调用（它同样没有结果）。
        """
        # TODO(M2 第四步·owner)：本步核心，约 10 行。
        raise NotImplementedError

    # 首次运行时注入 system prompt；若历史已存在则不覆盖。
    if not ctx.history:
        ctx.history.insert(0, Message.text("system", system_prompt))
    history_len = len(ctx.history)
    ctx.history.append(Message.text("user", user_input))

    # 快照：出错时回滚到 run 开始时的状态（撤销本轮追加的全部消息）
    start_iter = ctx.iter_count

    _emit(Hook.ON_RUN_START)

    while True:
        if ctx.iter_count >= ctx.max_iter:
            raise MaxIterationsError(f"超过最大迭代次数 {ctx.max_iter}")
        ctx.iter_count += 1

        _emit(Hook.ON_ITERATION_START)
        directive = _emit(Hook.BEFORE_MODEL_CALL)
        # TODO(M2 第四步·owner)：Replace → response = payload，跳过 provider.chat
        #   （无真实调用即无 APIError）；其他非 None → warning 忽略，照常调用。
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
        _emit(Hook.AFTER_MODEL_CALL)

        ctx.history.append(_assistant_message(response))

        if not response.tool_calls:
            # 模型直接回答了，本轮结束
            _emit(Hook.ON_ITERATION_END)
            _emit(Hook.ON_RUN_END)
            return response.content or ""

        # 多工具串行（§C）：每工具独立走 before/after 钩子，结果收齐后一起塞回。
        # 终止意图在此分派；HALT 须先补占位（halt_raises=False）。
        results: list[ToolResultBlock] = []
        for idx, call in enumerate(response.tool_calls):
            directive = _emit(Hook.BEFORE_TOOL_CALL, halt_raises=False)
            # TODO(M2 第四步·owner)：分派终止意图——
            #   Skip → result = ToolResultBlock(call_id, is_error=True,
            #       content=f"skipped: {reason}")，不执行工具；
            #   Replace → result = payload；
            #   Halt → _halt_tool_batch(results, response.tool_calls[idx:], reason)；
            #   其余 → 正常执行工具。
            result = tools.call(call.call_id, call.name, call.arguments)

            after_directive = _emit(Hook.AFTER_TOOL_CALL, halt_raises=False)
            # TODO(M2 第四步·owner)：after 点是 Halt →
            #   _halt_tool_batch(results + [result], tool_calls[idx + 1:], reason)
            results.append(result)

        for result in results:
            ctx.history.append(Message(role="tool", content=[result]))

        _emit(Hook.ON_ITERATION_END)
        # 循环继续：下一轮迭代
