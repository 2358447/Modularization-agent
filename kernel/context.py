"""一次 run 期间贯穿始终的共享状态。

模块之间、模块与内核之间只通过 Context 交换数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kernel.message import Message


@dataclass
class Context:
    """单次对话运行的共享上下文。

    Attributes:
        history: 当前对话历史。
        scratch: 模块可自由读写的共享区。
        iter_count: 当前迭代计数（M0 记录用户轮数，M1 用于 tool 循环安全阀）。
        max_iter: 单次 run 内最大允许迭代次数（M0 占位，M1 启用）。
    """

    history: list[Message] = field(default_factory=list)
    scratch: dict = field(default_factory=dict)
    iter_count: int = 0
    max_iter: int = 10
