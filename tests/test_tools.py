"""kernel.tools 的测试：注册、查重、call 的四条路径（成功/未知/缺参/类型错/崩溃）。

覆盖 tools.py 的设计承诺：工具出错绝不抛异常，全部变成 is_error 结果喂回模型。
"""

from __future__ import annotations

import pytest

from kernel.message import ToolResultBlock
from kernel.tools import Tool, ToolRegistry


def _make_tool(name: str = "add", func=None) -> Tool:
    """构造一个加法工具，参数 a/b 都是 number 且必填。"""
    return Tool(
        name=name,
        description="把两个数相加",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
        func=func or (lambda a, b: a + b),
    )


def test_register_and_get():
    reg = ToolRegistry()
    tool = _make_tool()
    reg.register(tool)
    assert reg.get("add") is tool
    assert reg.get("不存在的") is None


def test_register_duplicate_raises():
    """名字重复注册必须报错（让错误大声暴露，而非静默覆盖）。"""
    reg = ToolRegistry()
    reg.register(_make_tool())
    with pytest.raises(ValueError):
        reg.register(_make_tool())


def test_list_specs_returns_all():
    reg = ToolRegistry()
    reg.register(_make_tool("a"))
    reg.register(_make_tool("b"))
    assert [t.name for t in reg.list_specs()] == ["a", "b"]


def test_call_success():
    reg = ToolRegistry()
    reg.register(_make_tool())
    result = reg.call("c1", "add", {"a": 2, "b": 3})
    assert isinstance(result, ToolResultBlock)
    assert result.call_id == "c1"          # call_id 透传回填，供与请求配对
    assert not result.is_error
    assert result.content == "5"           # func 返回值被 str() 成文本


def test_call_unknown_tool_is_error():
    reg = ToolRegistry()
    result = reg.call("c1", "没有这个工具", {})
    assert result.is_error
    assert "未知工具" in result.content


def test_call_missing_argument_is_error():
    reg = ToolRegistry()
    reg.register(_make_tool())
    result = reg.call("c1", "add", {"a": 2})  # 缺必填 b
    assert result.is_error
    assert "缺少参数" in result.content


def test_call_wrong_type_is_error():
    reg = ToolRegistry()
    reg.register(_make_tool())
    result = reg.call("c1", "add", {"a": 2, "b": "字符串"})  # b 应为 number
    assert result.is_error
    assert "类型错误" in result.content


def test_call_function_crash_is_error():
    """工具真崩了（非预期异常）也绝不掀翻主循环，包装成 is_error。"""
    def boom(a, b):
        raise RuntimeError("工具内部炸了")

    reg = ToolRegistry()
    reg.register(_make_tool(func=boom))
    result = reg.call("c1", "add", {"a": 1, "b": 1})
    assert result.is_error
    assert "工具执行出错" in result.content
