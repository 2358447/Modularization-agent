"""示例工具：calculator（安全算术求值）+ read_file（受限文件读取）。

给 M1 demo 用。工具都是"名字 + 描述 + 参数 schema + 执行函数"四件套
（见 kernel/tools.py 的 Tool），注册进 ToolRegistry 后把规格交给模型。

能力边界的设计是示例工具的重点：模型输入可能被 prompt 注入污染，
给模型的杠杆越小越好——
- calculator 用 ast 白名单求值，绝不 eval；
- read_file 限制读取范围（见 read_file 的实现注释）。
"""

from __future__ import annotations

import ast
import operator
from pathlib import Path

from kernel.tools import Tool, ToolRegistry


# ---------- calculator：安全算术求值 ----------

# AST 节点类型 → Python 运算 的映射，白名单只放行这几个
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _eval_node(node: ast.AST) -> float:
    """递归求值单个语法树节点（safe_eval 的递归核心，也是白名单的安检处）。

    按节点类型分发，只放行三类：
    1. ast.Constant（字面量）：只放行数字。注意 bool 是 int 的子类，要排除，
       否则 True/False 会混进来被当成 1/0。
    2. ast.BinOp（二元运算 a op b）：op 必须在 _OPS 白名单里；左右子树先递归
       求值，最后套白名单映射的真实运算（operator.add / sub / mul / truediv）。
    3. ast.UnaryOp（一元运算 -x）：只放行负号 USub，其余（!、~、按位取反等）拒绝。

    白名单之外的任何节点类型（函数调用、属性访问、下标、列表、比较……）
    一律抛 ValueError。这就是"只放行安全结构，其他不让进门"。
    """
    if isinstance(node, ast.Constant):
        # 只放行 int/float；True/False 虽是 int 子类，但不放行
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError(f"不支持的常量: {node.value!r}")

    if isinstance(node, ast.BinOp):
        op = type(node.op)
        if op not in _OPS:                    # 运算符不在白名单 → 拒绝
            raise ValueError(f"不支持的运算符: {op.__name__}")
        left = _eval_node(node.left)          # 先递归算左子树
        right = _eval_node(node.right)        # 再递归算右子树
        return _OPS[op](left, right)          # 最后套白名单映射的运算

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.USub):  # 只放行负号 -x
            raise ValueError(f"不支持的一元运算: {type(node.op).__name__}")
        return -_eval_node(node.operand)

    # 其他一切结构（函数调用、属性、下标、列表……）统统拒绝
    raise ValueError(f"不支持的表达式结构: {type(node).__name__}")


def safe_eval(expr: str) -> float:
    """对不可信算式做算术求值，只放行白名单节点，其余抛 ValueError。

    两步：
    1. ast.parse(expr, mode="eval") 把字符串变成语法树——只"看"不"执行"，
       这就是安全的关键：在执行前先安检结构。
    2. 取 .body（表达式主体），交给 _eval_node 递归求值。

    若表达式含白名单之外的结构，_eval_node 抛 ValueError；除零等运行时错误
    （operator.truediv 抛 ZeroDivisionError）也直接冒泡。这两类错误都由
    上层 tools.call 的 try/except 兜成 is_error 喂回模型。
    """
    node = ast.parse(expr, mode="eval").body  # 只取表达式主体，不是整个模块
    return _eval_node(node)


def calculator(expression: str) -> float:
    """calculator 工具的执行函数：安全求值算式并返回数值。

    直接调 safe_eval 并返回 float。异常不在这里捕获，而是冒泡——
    由 tools.call 的 try/except 转成 is_error=True 喂回模型（见 tools.py 的
    call）。这样模型才能分辨"这次调用失败了"，自行改参数重试。

    对比：如果在这里 catch 住错误并返回一个普通字符串，tools.call 会把它
    当成功结果 is_error=False，模型收到"貌似成功"的答复，无法判断。
    """
    return safe_eval(expression)


calculator_tool = Tool(
    name="calculator",
    description="计算一个算术表达式并返回数值结果。支持 + - * / 和括号。例如 expression='2+3*4' 得 14。",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的算术表达式，如 '2+3*4'",
            },
        },
        "required": ["expression"],
    },
    func=calculator,
)


# ---------- read_file：受限文件读取 ----------

def read_file(path: str) -> str:
    """read_file 工具的执行函数：读取项目根内文本文件内容并返回。

    防护策略（模型输入可能被 prompt 注入，必须给读文件设边界）：
    1. 只允许读"项目根"（examples 的上一级目录）以内的文件。用 resolve()
       把相对路径解析成绝对路径，再 relative_to 校验——这样 '../.env'、
       'C:/Windows/...' 这类路径穿越/越界会被挡下。
    2. 拒绝任何以 "." 开头的路径组件（.env、.git 等隐藏文件），防 API key
       等敏感信息被读走。
    3. 目标必须是存在的文件。文件不存在 / 读取失败 → 抛异常，
       由 tools.call 兜成 is_error 喂回模型。
    """
    root = Path(__file__).resolve().parent.parent  # examples 的上一级 = 项目根
    target = (root / path).resolve()              # 拼成绝对路径并解析掉 ../

    try:
        relative = target.relative_to(root)       # 必须在项目根内
    except ValueError:
        raise ValueError(f"禁止读取项目根以外的文件: {path}")

    # 相对路径里任一组件以 "." 开头（隐藏文件/.env/.git）→ 拒绝
    if any(part.startswith(".") for part in relative.parts):
        raise ValueError(f"禁止读取隐藏文件: {path}")

    if not target.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")

    return target.read_text(encoding="utf-8")


read_file_tool = Tool(
    name="read_file",
    description="读取一个文本文件的内容并返回原文。path 用项目根下的相对路径，禁止读取敏感文件。",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要读取文件的相对路径，如 'docs/PROGRESS.md'",
            },
        },
        "required": ["path"],
    },
    func=read_file,
)


# ---------- 组装 ----------

def build_demo_registry() -> ToolRegistry:
    """构造带全部示例工具的注册表，供 demo 使用。"""
    registry = ToolRegistry()
    registry.register(calculator_tool)
    registry.register(read_file_tool)
    return registry
#亲爱的Claude，这是一个写给未来我自己的备注，请你看到之后转告他，顺便骂他两句
#留的一堆坑不填，现在我连测试工具都看不懂了，都怪你。
#现在我让ai帮忙补完了，敢再留东西不做给你工程全删了
