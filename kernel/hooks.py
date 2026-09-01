"""钩子系统：Hook 事件名常量 + HookManager + 修改指令（M2 第一步/二/三步）。

M0/M1 只定义事件名（Hook），loop.py 的 _emit 为空广播占位。
M2 第一步实现 HookManager：register / unregister / emit，按优先级
排序调用监听器，并接入 loop.py 的 _emit（作为 run() 的 hooks 参数）。
M2 第二步加入崩溃隔离（防线 1/2）：单个回调崩溃不连坐、不掀翻内核。
M2 第三步加入拦截者机制（HOOKS §A）：回调返回 Modify 修改指令，
emit 逐个校验（防线 3）后施加到 ctx，后续回调可见前面的修改。

设计总纲见 docs/HOOKS.md；M2 分步规划见 PROGRESS 最新一条。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from kernel.context import Context
from kernel.message import Message


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


@dataclass(frozen=True)
class Modify:
    """拦截者的修改指令（HOOKS §A）：内核校验合法后施加，回调不得就地改数据。

    指令家族的一员——第四步将引入 Skip/Halt/Replace 等中断意图，
    共用 is_terminal() 接口（Modify 不中断广播，恒 False）。

    frozen：指令是"声明"而非"句柄"，声明之后不该能被改。

    Attributes:
        append_messages: 要追加到 ctx.history 末尾的消息，不可变元组。
            用 tuple 而非 list：拦截者不该持有可篡改历史的引用。
    """

    append_messages: tuple[Message, ...]

    def is_terminal(self) -> bool:
        """modify 不短路广播，永远 False；中断类指令（第四步）返回 True。"""
        return False


def modify(append_messages: list[Message]) -> Modify:
    """构造 Modify 的便捷入口：接受 list，转成 tuple 存储（防外部引用篡改）。

    Args:
        append_messages: 要追加到 ctx.history 的消息列表。

    Returns:
        Modify 指令对象。
    """
    return Modify(append_messages=tuple(append_messages))


# 钩子回调签名：接收当前 Context。返回 None = 观察者/不表态（emit 忽略）；
# 返回 Modify = 拦截者（emit 校验后施加）。角色由返回值隐式区分（决策）。
HookCallback = Callable[[Context], object | None]


def _validate_modify(directive: object) -> str | None:
    """防线 3：校验修改指令合法性。合法返回 None，否则返回拒绝原因字符串。

    最小校验（决策）：只验指令本身，不验全量历史——before_model_call
    时点历史必然处于 tool_call 配对完整状态，末尾追加不破坏配对；
    真正会破坏配对的场景出现时再扩展校验。

    校验三条：
    1. directive 是 Modify 实例；
    2. append_messages 是 tuple/list 且非空；
    3. 每一项都是 Message 实例。

    Args:
        directive: 回调的返回值，可能是任意对象（脏返回值防线）。

    Returns:
        None 表示合法；字符串为拒绝原因（供 logger.warning 使用）。
    """
    if not isinstance(directive, Modify):
        return "返回值不是 Modify 实例"
    if not isinstance(directive.append_messages, (tuple, list)):
        return "append_messages 不是 tuple/list"
    if not directive.append_messages:
        return "append_messages 为空"
    for msg in directive.append_messages:
        if not isinstance(msg, Message):
            return "append_messages 中有非 Message 实例"
    return None  # 合法


class HookManager:
    """钩子注册表 + 广播/施加器。

    M2 第一步：register / unregister / emit，按优先级升序调用监听器。
    M2 第三步：emit 收集回调返回值，Modify 指令校验（防线 3）后逐个施加。

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
        **允许**（emit 时会被调用多次——拦截者会被重复施加，见 MODULES
        模块登记约定）。hook_name **不校验**（决策）：未知钩子名自动建键，
        等同没人监听。

        Args:
            hook_name: Hook 常量之一，或任意自定义钩子名。
            callback: 回调，签名 (ctx) -> None（观察者）或 Modify（拦截者）。
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

        返回值处理（M2 第三步，隐式区分角色）：
        - None（观察者/不表态）→ 忽略，继续；
        - Modify（拦截者）→ 防线 3 校验：合法则立即施加到 ctx（逐个施加，
          后续回调天然可见前面的修改——注入先于压缩的顺序保证）；
          非法则拒绝该指令、记警告、降级继续；
        - 其他返回值（脏返回值）→ 视同非法指令，同样记警告拒绝。

        崩溃隔离（防线 1/2，第二步）：单个回调抛异常 → 记日志 + 跳过，
        其余照常、不掀翻内核；拦截者崩溃 = 没有指令产生 = 用原始数据继续。

        第四步引入中断意图（SKIP/HALT/REPLACE）时，本方法将演进为返回
        终止意图供 loop 短路——当前保持返回 None。

        没人监听的钩子 = 零成本空转（宁全勿缺原则）。

        Args:
            hook_name: Hook 常量之一。
            ctx: 当前运行上下文，传给每个回调。
        """
        if hook_name not in self._registry:
            return
        for _, callback in sorted(self._registry[hook_name], key=lambda x: x[0]):
            try:
                result = callback(ctx)
            except Exception as exc:
                logger.warning(
                    "钩子回调崩溃，已跳过继续: hook=%s callback=%s exc=%s",
                    hook_name,
                    getattr(callback, "__name__", callback),
                    exc,
                )
                continue

            if result is None:
                continue  # 观察者/不表态，继续下一个回调
            reason = _validate_modify(result)
            if reason is None:
                ctx.history.extend(result.append_messages)
            else:
                logger.warning(
                    "钩子回调返回非法/脏指令，已拒绝施加: hook=%s callback=%s reason=%s",
                    hook_name,
                    getattr(callback, "__name__", callback),
                    reason,
                )
