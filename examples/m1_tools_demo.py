"""M1 工具系统端到端 demo：真实 provider + 示例工具跑通 ReAct 闭环。

跑法（在项目根目录）：
    python -m examples.m1_tools_demo

前置：.env 里有 OpenAI 兼容的 key / base_url / model（参考 .env.example）。

验证目标：
    用户问题 → 模型要求调工具（calculator / read_file）→ 工具执行 →
    结果回灌 → 模型基于结果给出最终回答。
"""

from __future__ import annotations

from dotenv import load_dotenv

from kernel.context import Context
from kernel.loop import run
from kernel.providers.openai_compat import OpenAICompat

from examples.tools import build_demo_registry


def main() -> None:
    load_dotenv()                          # 读 .env：OPENAI_API_KEY / BASE / MODEL

    ctx = Context()                        # 对话记录本（本 demo 只跑一轮）
    provider = OpenAICompat()              # 真实 provider，走 .env 里的配置
    tools = build_demo_registry()          # 工具箱：calculator + read_file

    # 演示问题：故意问一个必须调计算器的。模型会先发"工具调用请求"，
    # 框架执行完把结果喂回，模型再基于结果给出最终回答——这就是 ReAct 闭环。
    user_input = "帮我计算 (2+3)*4 等于多少，只要结果"
    reply = run(user_input, ctx, provider, tools=tools)
    print(reply)

    # 想加深理解：取消下面两行注释，看每次工具调用在历史里怎么被记录
    # print("\n==== 本轮历史 ====")
    # for m in ctx.history:
    #     print(f"[{m.role}] {[b.type for b in m.content]}")


if __name__ == "__main__":
    main()
