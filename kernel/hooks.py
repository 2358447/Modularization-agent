"""钩子系统：Hook 事件名常量 + HookManager + 修改指令（M2 第一步/二/三步）。

M0/M1 只定义事件名（Hook），loop.py 的 _emit 为空广播占位。
M2 第一步实现 HookManager：register / unregister / emit，按优先级
排序调用监听器，并接入 loop.py 的 _emit（作为 run() 的 hooks 参数）。
M2 第二步加入崩溃隔离（防线 1/2）：单个回调崩溃不连坐、不掀翻内核。
M2 第三步加入拦截者机制（HOOKS §A）：Modify 修改指令校验后施加。
M2 第四步加入中断三意图（HOOKS §D）：Skip/Halt/Replace 与 Modify 共用
Directive 家族，第一个终止意图短路广播并交还 loop 执行。

设计总纲见 docs/HOOKS.md；M2 分步规划见 PROGRESS 最新一条。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from kernel.context import Context
from kernel.message import Message, ToolResultBlock
from kernel.providers.base import Response


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


class Directive(ABC):
    """钩子指令家族基类。is_terminal()=False：emit 施加后继续广播；
    =True：短路广播、交还 loop 执行流程动作（HookManager 书记员，loop 执行者）。
    第五步错误裁决走"收集-裁决"，不经此短路模型，届时另立约定。
    """

    @abstractmethod
    def is_terminal(self) -> bool: ...


@dataclass(frozen=True)
class Modify(Directive):
    """修改指令：追加消息到 ctx.history（回调不得就地改数据）。

    append_messages 用 tuple：拦截者不该持有可篡改历史的引用。
    """

    append_messages: tuple[Message, ...]

    def is_terminal(self) -> bool:
        return False


@dataclass(frozen=True)
class Skip(Directive):
    """拦截意图：不执行本工具，内核给模型一条"被拒"结果，run 继续。"""

    reason: str = ""

    def is_terminal(self) -> bool:
        return True


@dataclass(frozen=True)
class Halt(Directive):
    """中断意图：终止整个 run（急停、预算耗尽）。不回滚历史——补全占位后
    历史合法可续跑（见 loop._halt_tool_batch）。"""

    reason: str = ""

    def is_terminal(self) -> bool:
        return True


@dataclass(frozen=True)
class Replace(Directive):
    """替换意图：短路真实调用，用 payload 顶替产物（缓存/mock）。

    payload 合法类型依钩子点而定，emit 校验（防线 3）。
    """

    payload: object

    def is_terminal(self) -> bool:
        return True


def modify(append_messages: list[Message]) -> Modify:
    """构造 Modify：list 自动转 tuple 存储。"""
    return Modify(append_messages=tuple(append_messages))


# Replace.payload 合法类型按钩子点而定；表到第三行时重构为类型自带知识。
_REPLACE_PAYLOAD_TYPES: dict[str, type] = {
    Hook.BEFORE_TOOL_CALL: ToolResultBlock,
    Hook.BEFORE_MODEL_CALL: Response,
}

# Modify 禁入：批次中途追加会插在 tool_call 与结果之间，破坏配对。
_MODIFY_FORBIDDEN_HOOKS = frozenset({Hook.BEFORE_TOOL_CALL, Hook.AFTER_TOOL_CALL})


# 钩子回调签名：返回 None = 观察者；返回 Directive = 拦截者（隐式区分角色）。
HookCallback = Callable[[Context], object | None]


def _validate_directive(directive: object, hook_name: str) -> str | None:
    """防线 3：合法返回 None，否则返回拒绝原因字符串。分派规则：

    1. 非 Directive 实例 → 拒；
    2. Modify → append_messages 是 tuple/list、非空、每项是 Message，
       且钩子点不在 _MODIFY_FORBIDDEN_HOOKS；
    3. Skip / Halt → reason 须是 str；
    4. Replace → payload 须是 _REPLACE_PAYLOAD_TYPES[hook_name] 的实例。
    """
    # TODO(M2 第四步·owner)：按四条分派，任一不过 return 原因字符串。
    raise NotImplementedError


class HookManager:
    """钩子注册表 + 广播/施加器（书记员）：施加 Modify、收集终止意图，不做流程动作。

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

    def emit(self, hook_name: str, ctx: Context) -> Directive | None:
        """按优先级升序调用回调；返回第一个终止意图（Skip/Halt/Replace），无则 None。

        - None 返回值 → 观察者，忽略；
        - Modify → 校验后立即施加（逐个施加，后续回调可见前面的修改）；
        - 终止意图 → 短路：停止广播，指令交还调用方（§D）；
        - 校验非法（含脏返回值）→ 记警告、不短路、继续（降级当没发生过）；
        - 单回调崩溃 → 记日志跳过（防线 1/2）。
        """
        if hook_name not in self._registry:
            return None
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
            reason = _validate_directive(result, hook_name)
            if reason is not None:
                logger.warning(
                    "钩子回调返回非法/脏指令，已拒绝: hook=%s callback=%s reason=%s",
                    hook_name,
                    getattr(callback, "__name__", callback),
                    reason,
                )
                continue
            # TODO(M2 第四步·owner)：is_terminal() 为真 → return result；
            #   否则（Modify）施加 ctx.history.extend(result.append_messages)。
        return None
