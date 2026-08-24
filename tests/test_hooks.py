"""kernel.hooks.HookManager 最小测试（M2 第一步/第二步）。

覆盖：
- 注册/注销（含重复注册的处理）
- 优先级升序调用、同优先级按注册顺序
- 没人监听的钩子空转、回调返回值被忽略
- 崩溃隔离（M2 第二步，防线 1/2）：单回调崩溃不连坐、不掀翻内核
- loop 接入 HookManager：纯对话 / 工具路径下，钩子按生命周期顺序广播
"""

from __future__ import annotations

from kernel.context import Context
from kernel.hooks import Hook, HookManager
from kernel.loop import run
from kernel.message import Message, ToolCallBlock
from kernel.providers.base import Provider, Response
from kernel.tools import Tool, ToolRegistry


class FakeProvider(Provider):
    """固定回复、不发工具调用的假 provider。"""

    def chat(self, messages: list[Message], **kwargs) -> Response:
        return Response(content="ok")


class ScriptedProvider(Provider):
    """按脚本返回：第一次要求调工具，之后直接回答。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None, **kwargs) -> Response:
        self.calls += 1
        if self.calls == 1:
            return Response(
                content=None,
                tool_calls=[ToolCallBlock(call_id="c1", name="echo", arguments={"text": "hi"})],
            )
        return Response(content="done")


def _echo_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(
        name="echo",
        description="把 text 原样返回",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        func=lambda text: text,
    ))
    return reg


def test_emit_calls_in_priority_order():
    """同一钩子按 priority 升序调用（数字小的先）。"""
    hooks = HookManager()
    order: list[int] = []

    hooks.register(Hook.ON_RUN_START, lambda ctx: order.append(200), priority=200)
    hooks.register(Hook.ON_RUN_START, lambda ctx: order.append(100), priority=100)
    hooks.register(Hook.ON_RUN_START, lambda ctx: order.append(150), priority=150)

    hooks.emit(Hook.ON_RUN_START, Context())

    assert order == [100, 150, 200]


def test_register_default_priority_keeps_registration_order():
    """不传 priority 默认 500；同优先级按注册顺序（sorted 稳定）。"""
    hooks = HookManager()
    order: list[str] = []

    hooks.register(Hook.ON_RUN_START, lambda ctx: order.append("a"))
    hooks.register(Hook.ON_RUN_START, lambda ctx: order.append("b"))

    hooks.emit(Hook.ON_RUN_START, Context())

    assert order == ["a", "b"]


def test_unregister_removes_callback():
    """注销后该回调不再被调用，其余照常。"""
    hooks = HookManager()
    calls: list[str] = []

    def a(ctx):
        calls.append("a")

    def b(ctx):
        calls.append("b")

    hooks.register(Hook.ON_RUN_START, a)
    hooks.register(Hook.ON_RUN_START, b)
    hooks.unregister(Hook.ON_RUN_START, a)

    hooks.emit(Hook.ON_RUN_START, Context())

    assert calls == ["b"]


def test_unregister_removes_all_duplicates():
    """同一回调重复注册两次，注销一次后全部不触发。"""
    hooks = HookManager()
    calls: list[str] = []
    cb = lambda ctx: calls.append("x")

    hooks.register(Hook.ON_RUN_START, cb)
    hooks.register(Hook.ON_RUN_START, cb)
    hooks.unregister(Hook.ON_RUN_START, cb)

    hooks.emit(Hook.ON_RUN_START, Context())

    assert calls == []


def test_emit_on_unregistered_or_unknown_hook_is_noop():
    """没人监听的钩子、未知钩子名：零成本空转，不报错。"""
    hooks = HookManager()

    hooks.emit(Hook.ON_RUN_START, Context())  # 注册表里有键没回调
    hooks.emit("totally_unknown_hook", Context())  # 连键都没有


def test_emit_ignores_callback_return_value():
    """回调返回非 None（未来拦截者修改指令的雏形）不影响广播。"""
    hooks = HookManager()
    calls: list[str] = []

    hooks.register(Hook.ON_RUN_START, lambda ctx: "modify(...)")  # 返回值被忽略
    hooks.register(Hook.ON_RUN_START, lambda ctx: calls.append("done"))

    hooks.emit(Hook.ON_RUN_START, Context())

    assert calls == ["done"]


def test_loop_hooks_fire_in_lifecycle_order():
    """纯对话一轮：6 个钩子按生命周期顺序各触发一次。"""
    hooks = HookManager()
    fired: list[str] = []

    def record(name):
        def cb(ctx):
            fired.append(name)

        return cb

    for hook_name, label in [
        (Hook.ON_RUN_START, "run_start"),
        (Hook.ON_ITERATION_START, "iter_start"),
        (Hook.BEFORE_MODEL_CALL, "before_model"),
        (Hook.AFTER_MODEL_CALL, "after_model"),
        (Hook.ON_ITERATION_END, "iter_end"),
        (Hook.ON_RUN_END, "run_end"),
    ]:
        hooks.register(hook_name, record(label))

    ctx = Context()
    result = run("hello", ctx, FakeProvider(), hooks=hooks)

    assert result == "ok"
    assert fired == [
        "run_start",
        "iter_start",
        "before_model",
        "after_model",
        "iter_end",
        "run_end",
    ]


def test_observer_receives_the_same_context_instance():
    """回调拿到的是 run 传入的同一个 ctx 实例（is 同一对象）。"""
    hooks = HookManager()
    seen: list[Context] = []
    hooks.register(Hook.BEFORE_MODEL_CALL, lambda ctx: seen.append(ctx))

    ctx = Context()
    run("hello", ctx, FakeProvider(), hooks=hooks)

    assert seen and seen[0] is ctx


def test_loop_hooks_fire_around_tool_call():
    """工具路径：before/after_tool_call 每个工具触发一次，循环继续到回答。"""
    hooks = HookManager()
    fired: list[str] = []
    hooks.register(Hook.BEFORE_TOOL_CALL, lambda ctx: fired.append("before_tool"))
    hooks.register(Hook.AFTER_TOOL_CALL, lambda ctx: fired.append("after_tool"))
    hooks.register(Hook.ON_ITERATION_END, lambda ctx: fired.append("iter_end"))
    hooks.register(Hook.ON_RUN_END, lambda ctx: fired.append("run_end"))

    ctx = Context()
    result = run("hi", ctx, ScriptedProvider(), tools=_echo_registry(), hooks=hooks)

    assert result == "done"
    # 工具路径跑了两轮迭代：第一轮 before/after_tool → iter_end，
    # 第二轮模型直接回答 → iter_end → run_end。
    assert fired == ["before_tool", "after_tool", "iter_end", "iter_end", "run_end"]


def test_crashing_callback_does_not_break_emit():
    """崩溃回调前后的回调都照常调用（不连坐，防线 1）。"""
    hooks = HookManager()
    calls: list[str] = []

    def boom(ctx):
        raise RuntimeError("observer crashed")

    def mark(label):
        def cb(ctx):
            calls.append(label)

        return cb

    hooks.register(Hook.ON_RUN_START, mark("before"), priority=100)
    hooks.register(Hook.ON_RUN_START, boom, priority=200)
    hooks.register(Hook.ON_RUN_START, mark("after"), priority=300)

    hooks.emit(Hook.ON_RUN_START, Context())  # 不抛

    assert calls == ["before", "after"]


def test_emit_does_not_raise_when_callback_crashes():
    """回调抛异常时 emit 自身不抛（不掀翻内核）。"""
    hooks = HookManager()
    hooks.register(Hook.ON_RUN_START, lambda ctx: 1 / 0)

    hooks.emit(Hook.ON_RUN_START, Context())  # 不抛即通过


def test_multiple_crashing_callbacks_others_still_run():
    """多个崩溃回调夹正常回调，正常回调全部照跑。"""
    hooks = HookManager()
    calls: list[str] = []

    def boom(ctx):
        raise ValueError("boom")

    def mark(label):
        def cb(ctx):
            calls.append(label)

        return cb

    hooks.register(Hook.ON_RUN_START, boom, priority=100)
    hooks.register(Hook.ON_RUN_START, mark("a"), priority=200)
    hooks.register(Hook.ON_RUN_START, boom, priority=300)
    hooks.register(Hook.ON_RUN_START, mark("b"), priority=400)
    hooks.register(Hook.ON_RUN_START, boom, priority=500)

    hooks.emit(Hook.ON_RUN_START, Context())

    assert calls == ["a", "b"]


def test_crashing_observer_in_loop_does_not_break_run():
    """loop 里挂一个会崩的观察者，run() 仍正常返回（防线 1 兜底）。"""
    hooks = HookManager()

    def boom(ctx):
        raise RuntimeError("observer died")

    hooks.register(Hook.BEFORE_MODEL_CALL, boom)

    ctx = Context()
    result = run("hello", ctx, FakeProvider(), hooks=hooks)

    assert result == "ok"
