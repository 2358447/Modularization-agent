"""钩子事件名常量。

M0 只定义事件名，loop.py 在关键位置调用空广播函数占位。
M1 实现 HookManager 后，把空广播替换为真正的 emit。
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
