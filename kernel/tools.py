"""工具注册与调度。

M1 新增。内核通过 ToolRegistry 使用工具：注册、把工具规格交给 provider
渲染成模型能懂的 schema、在模型要求调用工具时校验参数并执行、把结果（或
错误）变成 ToolResultBlock 喂回模型。工具出错绝不崩主循环——错误被包装成
is_error 结果，让模型自己决定下一步（自愈）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kernel.message import ToolResultBlock


@dataclass
class Tool:
    """一个可被模型调用的工具。

    Attributes:
        name: 工具名，模型用这个名字发起调用，必须唯一。
        description: 给模型看的用途说明。描述得越清楚，模型越会用对。
        parameters: 参数 JSON Schema（CHEATSHEET §7），模型据此传参，
            框架内部也用它做参数校验。
        func: 实际执行函数，以关键字参数形式接收 arguments。
    """

    name: str
    description: str
    parameters: dict
    func: Callable[..., Any]


class ToolRegistry:
    """工具注册表：注册、查找、输出规格、校验并执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具。名字重复时抛 ValueError（让错误大声暴露）。"""
        # TODO: 若 tool.name 已在 _tools 里，抛 ValueError；否则存进 _tools
        if tool.name in self._tools:
            raise ValueError(f"工具已存在: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名字查工具，查不到返回 None。"""
        # TODO
        return self._tools.get(name)

    def list_specs(self) -> list[Tool]:
        """返回全部已注册工具，供 provider 渲染厂商 schema。"""
        # TODO
        return list(self._tools.values())

    def call(self, call_id: str, name: str, arguments: dict) -> ToolResultBlock:
        """执行一次工具调用。永远返回 ToolResultBlock（成功或 is_error），不抛异常。

        call_id 来自模型的 ToolCallBlock，回填到结果里与请求配对（一对一，决策 #7）。

        流程编排：拿工具 → 校验 → 执行 → 打包结果。参数校验交给
        _validate_arguments，靠返回值传信号（None=放行，str=给模型的错误原因），
        校验不过就不执行（fail fast）。
        """
        tool = self.get(name)
        if tool is None:
            # 查不到工具：模型可能记错了名字，给它一条看得懂的错误
            return ToolResultBlock(call_id=call_id, content=f"未知工具: {name}", is_error=True)

        # 质检：把"模型实际给的 arguments"和"工具声明要的 parameters"交给
        # _validate_arguments 对照。返回值即信号——None 放行，str 是错误原因。
        validation_error = self._validate_arguments(arguments, tool.parameters)
        if validation_error is not None:
            # 校验不过：错误文案原样变成 is_error 结果喂回模型，让它自己改参数
            return ToolResultBlock(call_id=call_id, content=validation_error, is_error=True)

        try:
            # 校验通过才执行。**arguments 把参数字典解包成关键字参数（字典→具名参数）
            result = tool.func(**arguments)
            return ToolResultBlock(call_id=call_id, content=str(result), is_error=False)
        except Exception as e:
            # 工具真崩了（非预期）：异常兜住，绝不掀翻主循环，变 is_error 喂回模型
            return ToolResultBlock(call_id=call_id, content=f"工具执行出错: {e}", is_error=True)

    def _validate_arguments(self, arguments: dict, parameters: dict) -> str | None:
        """最小参数校验（质检员）。合法返回 None；非法返回给模型看的错误原因。

        与 call() 协作：call 把 arguments（模型实际给的）和 tool.parameters
        （工具声明要的）传下来，本函数对照检查。预期内的"参数不合法"用返回值
        传信号，不抛异常；非预期的崩溃才由 call 的 try/except 处理。

        不做完整 JSON Schema 校验（那要引 jsonschema 库），只查两点就够：
        必填键齐不齐 + 基础类型对不对。
        """
        required_keys = parameters.get("required", [])
        for key in required_keys:
            if key not in arguments:
                return f"缺少参数 {key}"
        properties = parameters.get("properties", {})
        for key, value in arguments.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type == "number" and not isinstance(value, (int, float)):
                    return f"参数 {key} 类型错误，期望 number"
                elif expected_type == "string" and not isinstance(value, str):
                    return f"参数 {key} 类型错误，期望 string"
                elif expected_type == "boolean" and not isinstance(value, bool):
                    return f"参数 {key} 类型错误，期望 boolean"
                elif expected_type == "integer" and not isinstance(value, int):
                    return f"参数 {key} 类型错误，期望 integer"
        return None

