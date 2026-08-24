"""钩子系统：Hook 事件名常量 + HookManager（M2 第一步/第二步实现）。

M0/M1 只定义事件名（Hook），loop.py 的 _emit 为空广播占位。
M2 第一步实现 HookManager：register / unregister / emit，按优先级
排序调用监听器，并接入 loop.py 的 _emit（作为 run() 的 hooks 参数）。
M2 第二步加入崩溃隔离（防线 1/2）：单个回调崩溃不连坐、不掀翻内核。

设计总纲见 docs/HOOKS.md；M2 分步规划见 PROGRESS 最新一条。
"""

from __future__ import annotations

import logging
from typing import Callable

from kernel.context import Context


logger = logging.getLogger(__name__)


class Hook:
    """钩子点命名空间。"""

    ON_RUN_START = "on_run_start"
    ON_ITERATION_START = "on_iteration_start"
    BEFORE_MODEL_CALL = "before_model_call"
    AFTER_MODEL_CALL = "after_model_call"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    ON_ITERATION_END = "on_iteration_end"
    ON_RUN_END = "on_run_end"
    ON_ERROR = "on_error"
    ON_TOOL_ERROR = "on_tool_error"


# 钩子回调签名：接收当前 Context。观察者返回 None；拦截者返回修改指令
# （M2 步骤 3 引入，第一步的 emit 忽略返回值）。
HookCallback = Callable[[Context], object | None]


class HookManager:
    """钩子注册表 + 广播器。

    M2 第一步：register / unregister / emit，按优先级升序调用监听器。
    观察者/拦截者区分、修改指令、错误裁决在后续步骤引入（见 docs/HOOKS.md）。

    Attributes:
        _registry: hook_name → 已注册回调的 (priority, callback) 列表。
    """

    def __init__(self) -> None:
        """注册表初始为空，键在 register 时按需创建。"""
        self._registry: dict[str, list[tuple[int, HookCallback]]] = {}

    def register(
        self,
        hook_name: str,
        callback: HookCallback,
        priority: int = 500,
    ) -> None:
        """注册一个监听指定钩子的回调。

        键不存在时自动建空列表再追加；同一 (hook_name, callback) 重复注册
        **允许**（emit 时会被调用多次）——观察者阶段无妨，拦截机制引入后再审视。
        hook_name **不校验**（决策）：未知钩子名自动建键，等同没人监听。

        Args:
            hook_name: Hook 常量之一，或任意自定义钩子名。
            callback: 回调，签名 (ctx) -> None（观察者）或修改指令（步骤 3）。
            priority: 同一钩子点按数字升序执行（小的先）。默认 500 是占位值，
                各模块优先级约定登记在 docs/MODULES.md。
        """
        self._registry.setdefault(hook_name, []).append((priority, callback))

    def unregister(self, hook_name: str, callback: HookCallback) -> None:
        """注销一个回调。按回调对象身份匹配，删除该钩子名下所有匹配项。

        找不到（未注册或已注销）则静默忽略。重复注册过的回调，一次注销全部移除。

        Args:
            hook_name: Hook 常量之一。
            callback: 当初 register 时传入的同一个回调对象。
        """
        if hook_name in self._registry:
            self._registry[hook_name] = [
                (p, cb) for (p, cb) in self._registry[hook_name] if cb is not callback
            ]

    def emit(self, hook_name: str, ctx: Context) -> None:
        """广播钩子事件：按优先级升序依次调用该钩子的全部回调，传入 ctx。

        没人监听的钩子 = 零成本空转（宁全勿缺原则）。回调返回值被忽略——
        拦截者的"返回修改指令、内核施加"机制在步骤 3 引入，届时收集返回值
        （可能演进为 emit_and_collect）。

        M2 第二步（防线 1/2）：单个回调抛异常 → 记日志 + 跳过，其余照常、
        不掀翻内核。观察者崩了零影响（防线 2）。

        Args:
            hook_name: Hook 常量之一。
            ctx: 当前运行上下文，传给每个回调。
        """
        if hook_name in self._registry:
            for _, callback in sorted(self._registry[hook_name], key=lambda x: x[0]):
                try:
                    callback(ctx)
                except Exception as exc:
                    logger.warning(
                        "钩子回调崩溃，已跳过继续: hook=%s callback=%s exc=%s",
                        hook_name,
                        getattr(callback, "__name__", callback),
                        exc,
                    )
