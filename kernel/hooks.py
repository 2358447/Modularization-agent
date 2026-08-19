"""钩子系统：Hook 事件名常量 + HookManager（M2 第一步实现）。

M0/M1 只定义事件名（Hook），loop.py 的 _emit 为空广播占位。
M2 第一步在本文件实现 HookManager：register / unregister / emit，
并按优先级排序调用监听器，替换 loop.py 的空广播。

设计总纲见 docs/HOOKS.md；M2 分步规划见 PROGRESS 最新一条。
"""

from __future__ import annotations


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
