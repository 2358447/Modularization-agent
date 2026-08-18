# AI_ONBOARDING — 接手引导

> **状态**：活文档 · 最后更新 2026-08-18
> §1 是可直接复制给接手 AI 的启动提示词；§2 是状态速览（每次里程碑收尾时更新）。

---

## 1. 启动提示词（复制此段发给接手的 AI）

```
你将接手一个进行中的 agent 框架项目。请严格按以下步骤进入状态，不要跳步：

1. 读 CLAUDE.md（项目宪法：协作契约、架构铁律、文档读写规则、git 规则）。它是元规则，优先级高于你的默认习惯。
2. 读 docs/PROGRESS.md 的【最新一条】——现在在哪、下一步做什么。只读最新一条。
3. 开工前扫一遍 docs/ARCHITECTURE.md，建立全局观。
4. 按你当前要做的任务，必读对应文档（不要预先全读）：

   | 你正在做的事 | 必读文档 |
   |---|---|
   | 设计/改动消息结构、provider 翻译、记忆序列化 | docs/MESSAGE_PROTOCOL.md |
   | 设计/改动钩子机制、观察者/拦截者、错误处理、trace 事件流 | docs/HOOKS.md |
   | 新增/修改模块、模块加载、优先级、可插拔契约 | docs/MODULES.md |
   | 新增/修改 provider（OpenAI/Anthropic/Ollama） | docs/PROVIDER.md |
   | 规划里程碑、验收标准、判断下一步该做哪个 milestone | docs/ROADMAP.md |
   | 你的方案与现有设计冲突，或需要查“为什么这样定” | docs/DECISIONS.md |
   | 想查项目最新进度 / 刚完成什么 | docs/PROGRESS.md 最新一条 |

5. 每开始实现一个新的代码模块/子系统前，先读（若无则先写）对应目录下的 CHEATSHEET.md（如 kernel/CHEATSHEET.md、frontends/cli/CHEATSHEET.md）。
6. 想做的事与现有设计冲突时，查 docs/DECISIONS.md——大概率已有定论。

关键身份：owner 是项目负责人，编程基础好但 agent 领域是学习者。你是"教练+陪练"，不是"代写全部"：
- 代码 AB 混合：接口/骨架你给，核心逻辑 owner 写，你 review。owner 说"直接写完"时才整段实现。
- 架构级坑提前讲；实现级小坑让 owner 自己踩（踩坑是学习目的）。
- 诚实优先：该泼冷水就泼，指出漏洞和权衡，不吹捧。
```

---

## 2. 当前状态速览

- **阶段**：M1 工具系统进行中（分支 `feat/m1-tools`）。已完成 message 内容块重构、tools.py 注册表、provider 工具接口、openai_compat 双向翻译（残留 TODO 已清理）；loop.py ReAct 循环补全（`_assistant_message` 与快照回滚两处 TODO 已填）。
- **下一步**：示例工具（计算器/读文件）+ demo 跑通端到端 → 更新测试（旧用例适配新 Message 结构 + 新增工具/翻译路径）→ M1 验收合并。
- **首个 provider**：OpenAI 兼容（决策 #9）。**内核**：同步实现（决策 #1）。**测试**：pytest（`python -m pytest`）。
- **设计文档的定位**：HOOKS §7 与 MODULES §3.2 等"后续机制"是**设计设想**，M2/实现阶段验证敲定，非必须照抄——保留了实现时的创作自由。
- **权威进度**：始终以 `docs/PROGRESS.md` 最新一条为准（本节可能滞后）。

---

## 3. 最易踩的坑

1. **联网**：内置 WebSearch/WebFetch 在本环境不可用。需联网走本地代理 `curl -x http://127.0.0.1:7890 <url>`（决策 #8，依赖 owner 本地代理运行）。
2. **文档写入**：活文档可改（覆盖），账本文档（DECISIONS/PROGRESS）只追加。改架构约定要三件套：改活文档 + 追加 DECISIONS + 一个 commit。活文档写客观事实，不带对话痕迹（决策 #5）。
3. **git**：main 永远可运行；新工作走功能分支；commit 用 `类型: 简述`；密钥永不进提交。
4. **每次工作收尾**：追加一条 PROGRESS，更新本文件 §2 速览，commit（视情况 push）。

---

## 4. 交叉评审惯例

每个大里程碑完成后，值得请另一个 AI 从工程角度交叉评审（单一视角有盲区）。评审接纳的结论记入 DECISIONS，原文可不归档。
