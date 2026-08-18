# PROGRESS — 进度日志

> 账本文档。回到项目时读**最新一条**即可续上：知道"刚做完什么、现在在哪、下一步做什么"。

---

## 2026-08-18 · M1 工具循环补全（loop 两处 TODO 完成，翻译层清理）

- **openai_compat.py 清理**：删除 `_to_openai_tools`/`_parse_choice` 残留的 TODO 注释（实现早已完成），docstring 从 TODO 清单改写为行为描述；修类内方法间双空行、补文件末尾换行。
- **loop.py `_assistant_message` 完成**：把 Response 转成内部 assistant 消息——content 非空 → TextBlock，tool_calls（已是 ToolCallBlock 对象）直接并入 content 块列表。一条消息同时装文字与多个工具请求。
- **loop.py 快照回滚完成**：`history_len` 记在 system 注入后、user append 前（首次 run 时=1 只含 system，后续 run=既有历史长度）；`APIError` 时截断 history 到 history_len、iter_count 归位 start_iter，再 re-raise。等价于 M0 的 pop user 消息，但覆盖多轮循环中间出错的场景。
- **测试**：逻辑相关用例恢复绿——`test_does_not_reinject_system_prompt`、`test_api_error_rolls_back_history` 通过；全量 2 passed 3 failed。剩余 3 个失败是 M0 用例断言 `content` 裸字符串、与 M1 块列表结构不匹配，属测试适配任务（M1 收尾）。
- **记录更正**：2026-08-03 记录的"M0 5 用例保持绿"与实际不符——M1 重构（content 块列表 + loop 骨架）后旧测试未适配已挂，本次补记。

**下一步**：示例工具（计算器/读文件）+ demo 跑通端到端 → 适配 M0 测试 + 新增 M1 工具/翻译路径测试 → M1 验收合并回 main。

---

## 2026-08-03 · M1 工具系统进行中（message/tools/provider/翻译完成，loop 骨架就位）

- **里程碑定序（澄清 2026-08-02 的误称）**：M1 = 工具系统（ROADMAP 原文），钩子系统是 M2。此前 PROGRESS 写"M1 钩子系统"是编号误称，owner 已拍板按 ROADMAP 走。分支 `feat/m1-tools` 从最新 main 切出（M0 早已通过 GitHub PR #1/#2/#3 合并进 main）。
- **message.py**：content 重构为内容块列表（TextBlock/ToolCallBlock/ToolResultBlock），落地 MESSAGE_PROTOCOL §2 关键决策。to_dict/from_dict 往返无损，未知块类型抛 ValueError。两个方向用不同钥匙：对象→dict 用 isinstance、dict→对象按 type 字段。
- **tools.py**：Tool（name/description/parameters JSON Schema/func）+ ToolRegistry（register 重名抛错/get/list_specs/call）。call 永远返回 ToolResultBlock，四条失败路径（未知工具/缺参/类型错/执行崩溃）全变 is_error 喂回模型，绝不掀翻主循环。校验用返回值传信号（预期内失败），执行异常用 try/except（非预期崩溃）。
- **providers/base.py**：chat() 增加 tools 参数；Response.content 允许 None（纯工具调用）、新增 tool_calls（复用 ToolCallBlock）。
- **openai_compat.py**：双向翻译。请求：内部 Message→OpenAI wire（text 拼接、tool_calls 展开、is_error 加 [错误] 前缀、tools 数组渲染）；响应：_parse_choice 解析 content（可 None）+ tool_calls（arguments JSON 字符串→dict，解析失败抛 APIError），call_id 透传厂商值（决策 #10）。chat() 彻底脱离"to_dict 当 wire"。
- **loop.py**：ReAct 循环骨架就位（while + 工具分支 + max_iter 安全阀 MaxIterationsError + 快照式回滚），_assistant_message 与回滚两处 TODO 待填。
- 测试：M0 5 用例保持绿（FakeProvider 绕过 wire 翻译）；M1 工具/翻译路径的正式测试留到 M1 收尾（任务 #8）。

**下一步**：填 loop.py 两处 TODO → 示例工具（计算器/读文件）+ demo → 更新/新增测试 → M1 验收 → 合并回 main。

---

## 2026-08-02 · M0 收尾完成（feat/m0-kernel-skeleton）

- **CLI 错误处理**：provider 抛 `APIError` 不再 traceback 崩溃。分工：`loop.run()` 负责状态回滚（撤销已 append 的 user 消息、`iter_count` 归位，再 `raise` 上抛）；CLI 只负责展示错误并回到输入循环——前端不碰 ctx 内部（铁律 5）。
- **决策**：M0 只捕获 `APIError`，不扩大异常家族（更完整的 `on_error` 钩子机制留给 M1）；首次 run 失败时 system prompt 保留（会话固定前导，非污染）；`max_iter` 安全阀留到 M1——M0 无工具循环、一次输入恰为一次迭代，无事可守，提前实现违背"学习优先于性能"。
- **最小测试**：引入 pytest（`pytest.ini` + `requirements.txt` 加依赖）；`tests/test_loop.py` 用不联网的 `FakeProvider` 覆盖 5 场景：system 只注入一次、二次不重注入、user→assistant 追加、system_prompt 覆盖、APIError 回滚与恢复。`python -m pytest` 5 用例全绿。
- **新增文档**：`tests/CHEATSHEET.md`（pytest 最小用法，含"无断言的测试是假绿"提醒）。
- 本次一并提交此前未落的 provider `APIError` 改动（`base.py`/`openai_compat.py`）与 `AI_ONBOARDING.md` 更新。

**下一步**：M0 收尾提交即完成。之后进入 M1（钩子系统）：把 `kernel/loop.py` 的 `_emit` 空广播接入 HookManager，范围与验收见 `docs/ROADMAP.md`。

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
