# PROGRESS — 进度日志

> 账本文档。回到项目时读**最新一条**即可续上：知道"刚做完什么、现在在哪、下一步做什么"。

---

## 2026-07-30 · 立项与设计阶段完成

- 敲定项目定位、协作契约、架构铁律（见 CLAUDE.md）。
- 完成六份设计文档：ARCHITECTURE（架构总纲）、HOOKS（钩子系统）、MESSAGE_PROTOCOL（消息协议）、MODULES（模块系统）、PROVIDER（provider 抽象）、ROADMAP（实现路线）。
- 决策落档 #1–#10：同步内核、git 治理、文档分层、多工具结果一对一粒度、联网走本地代理、首实现 OpenAI 兼容、外部评审接纳等。
- git 仓库、`.gitignore`/`.gitattributes` 就位。

---

## 2026-07-31 · M0 骨架完成（feat/m0-kernel-skeleton）

- 切出功能分支 `feat/m0-kernel-skeleton`。
- 完成 M0 骨架代码：`kernel/`（`message`、`context`、`hooks`、`loop`、`providers/base`、`providers/openai_compat`）+ `frontends/cli/main.py` + `kernel/CHEATSHEET.md` + `frontends/cli/CHEATSHEET.md` + `requirements.txt` + `.env.example`。
- 关键架构选择：`loop.py` 中预埋空钩子广播（M1 接入 HookManager 时不改内核）；system prompt 可被环境变量 `AGENT_SYSTEM_PROMPT` 覆盖；OpenAI 兼容 provider 从环境变量读取配置。
- 验收：`printf 'hi\nhello\n' | python -m frontends.cli.main` 跑通 stub 回复；Ctrl-C 优雅退出已注册。
- 提交：`3620817 feat: M0 骨架（端到端 hello，所有真逻辑为 TODO）`；分支已推 origin。

**下一步**：owner 逐文件填 TODO，从 `kernel/providers/openai_compat.py` 真实 HTTP 调用开始，再到 `message` / `context` / `loop` / `cli` 打磨。每填完一个文件一个 commit。填完后用真实 key 做 CLI 多轮对话验收。

---

## 2026-07-31 · M0 provider 与 CLI 收尾

- 将 `kernel/providers/base.py` 回退到 M0 最简版本：仅保留 `Response` + `Provider.chat()` 抽象方法。
- 清理 `kernel/providers/openai_compat.py`：删除过期 TODO、修正 PEP 8 格式，保留真实 HTTP 调用；不添加错误包装、`kwargs` 透传、`timeout`。
- CLI 增加 `.env` 自动加载：`requirements.txt` 引入 `python-dotenv`，`frontends/cli/main.py` 启动时调用 `load_dotenv()`。
- 验证：`printf '你好\\n' | python -m frontends.cli.main` 成功调用 DeepSeek 并返回真实回复。
- `kernel/CHEATSHEET.md` 同步回退到 M0 范围。
- 分支 `feat/m0-kernel-skeleton` 已推 origin；当前提交 `5191a2d`。

**下一步**：继续填 M0 其余 TODO——`message.py` / `context.py` / `loop.py` / `cli/main.py` 的细节打磨与错误处理。

---

## 2026-07-30 · 文档整顿，重回代码正轨

- **诊断**：文档一度膨胀到 1753 行且 0 行代码，治理规则过度细化、后续路线被写死为"权威正文"，杜绝了踩坑学习的初衷。
- **整顿**（决策 #11）：破例重写账本（合并原 #11–13 反复决策、压缩流水进度）；活文档中"写死后续路线"的部分降格为设计设想/实现参考；保留成熟的治理框架与全部设计内容。文档精简约一半。
- **现状**：设计阶段收尾，元层工作结束，可开始写代码。

**下一步（明确动作）**：进入 **M0 最小内核**。开分支 `feat/m0-kernel-skeleton`，先出 CHEATSHEET，再实现：Message(text 块最小版) + Provider 抽象 + OpenAI 兼容 `chat` + 极简主循环(纯对话) + 极简 CLI + Context 雏形 + 内核持有 system prompt + CLI 捕获 Ctrl-C 优雅退出。验收：CLI 多轮对话跑通。协作按 AB 混合。

**准备事项**：owner 备好 OpenAI 兼容的 API key + base_url，放入 `.env`（已被 gitignore 忽略）。
