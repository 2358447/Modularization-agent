"""极简 CLI 前端。"""

from __future__ import annotations

import signal
import sys

from dotenv import load_dotenv

from kernel.context import Context
from kernel.loop import run
from kernel.providers.base import APIError
from kernel.providers.openai_compat import OpenAICompat


def _on_sigint(_signum: int, _frame) -> None:
    """Ctrl-C 优雅退出：打印换行后退出。"""
    print("\n[收到 Ctrl-C，退出]")
    sys.exit(0)


def main() -> None:
    """CLI 入口。"""
    load_dotenv()

    signal.signal(signal.SIGINT, _on_sigint)

    ctx = Context()
    provider = OpenAICompat()

    print("M0 CLI — 输入文字开始对话，Ctrl-C 退出。")
    while True:
        try:
            user_input = input(">>> ").strip()
        except EOFError:
            print()
            break

        if not user_input:
            continue
        try:
            reply = run(user_input, ctx, provider)
            print(reply)
        except APIError as exc:
            print(f"[错误] {exc}")


if __name__ == "__main__":
    main()
