# PROGRESS — 进度日志

> 账本文档。回到项目时读**最新一条**即可续上：知道"刚做完什么、现在在哪、下一步做什么"。

---

## 2026-09-01 · M2 第四步设计拍板 + 骨架落地（逻辑待填）

- **五个设计决策**（讨论拍板，全文见 HOOKS §7"第四步设计结论"）：① Skip/Halt/Replace 与 Modify 共用 `Directive` 基类，`is_terminal()` 分界；② 分工——HookManager 书记员（施加 Modify、收集终止意图），loop 执行者（动流程）；③ HALT 用 `RunHalted` 异常传出、**不回滚历史**（可续跑是 HALT 的意义）；④ 批次中途 HALT 先补 `tool_result(is_error)` 占位再抛（`_halt_tool_batch`）；⑤ Replace payload 按钩子点在 emit 校验（表驱动，第三行时重构为类型自带知识）。
- **骨架绘制时新发现**：Modify 在 before/after_tool_call 会插在 tool_call 与配对结果之间、破坏 wire 合法性 → `_MODIFY_FORBIDDEN_HOOKS` 禁入（防线 3 随用例生长的第一次扩展）；after_tool_call 的"改结果"Replace 推迟到真实用例出现。
- **骨架内容**：Directive 家族（纯声明）+ 两张校验表 + `emit` 签名改 `Directive | None` + loop 的 `RunHalted` / `_emit(halt_raises=...)` / `_halt_tool_batch` 签名与 docstring。**六处 TODO 待 owner 填**：`_validate_directive`（四条分派）、emit 短路一行、`_emit` 的 Halt 一行、模型点 Replace 短路、工具点 Skip/Replace/Halt 三分派、`_halt_tool_batch`（本步核心，约 10 行）。
- **预埋的坑（已记录防遗忘）**：first-wins 短路模型**不覆盖**第五步错误裁决（收集-裁决），on_error 届时另立约定（HOOKS §7 标注）。
- **当前状态**：import 干净；39/45 passed——6 个失败全是依赖 TODO 的拦截者用例，填完即回绿（骨架提交进功能分支，符合"半成品不进 main"）。
- **杂项**：第四步注释做过一轮精简（设计叙述移入文档，代码只留职责定性 + 防坑提示）；版本树思维导图（本地 HTML，含各里程碑能力与 M4+ 钩子挂载点）已生成给 owner，未入库。

**下一步**：填六处 TODO → pytest 回绿 → 补测试（短路规则/HALT 占位/Replace 两点/Skip 拒绝结果/Modify 禁入）→ 收尾三件套 → M2 还剩第五步（错误裁决）、第六步（trace 事件流）、第七步（验收）。

---

## 2026-09-01 · M2 第三步完成（拦截者机制·防线 3 + 测试 45）

- **修改指令落地**：`Modify`（frozen dataclass，唯一字段 `append_messages: tuple[Message, ...]`，tuple 防拦截者持有可篡改引用）+ 构造入口 `modify(list)`（自动转 tuple）。`is_terminal()` 恒 False——只给第四步中断指令留家族接口的缝，不预建类型（吸取第一步"预填 10 键"教训）。
- **三个实现级决策**（讨论后拍板）：① 施加放 emit 循环逐个校验+施加——loop.py 零改动，后续回调天然可见前面的修改（注入先于压缩的顺序保证）；② 角色由返回值隐式区分（None=观察者 / Modify=拦截者 / 其他=脏指令视同非法）；③ 防线 3 最小校验——只验指令本身三条（Modify 实例 / tuple|list 非空 / 每项是 Message），不验全量历史（校验跟着真实用例长）。
- **防线 3 落地**：`_validate_modify` 非法 → warning（hook + 回调 + 原因）→ 拒绝该拦截者本轮 → 继续广播，绝不 raise。防线 2 补完：拦截者崩溃 = 无指令产生 = 用原始数据继续，与观察者同款，零新代码。
- **踩坑（review 抓出，测试测不出）**：拒绝日志用 `+` 拼接 `getattr(callback,"__name__",callback)`，其 fallback 是回调对象本身——无名回调（如 `functools.partial`）时 TypeError 冲出 emit、掀翻主循环，恰好击穿防线 1；普通函数测试全绿测不出来。修正为 `%s` 惰性格式化（与防线 1 同款）+ 补 partial 回归测试。教训：日志拼接一律走惰性格式化。
- **测试**：38 → 45 passed。新增 7 例（is_terminal 契约 / 观察者回归 / 合法施加 / 顺序可见 / 非法指令四连 / 无名回调 / loop 注入进模型输入= RAG 最小原型）；改写 1 例（"返回值被忽略"的前提已被第三步语义取代，留旧断言即假绿）。
- **收尾**：CHEATSHEET §14 回填（拦截者/修改指令模式）；HOOKS §7 回填"第三步已验证敲定"；ROADMAP 状态表 + AI_ONBOARDING §2 同步。

**下一步**：M2 第四步——中断三意图 SKIP/HALT/REPLACE + 短路规则（HOOKS §D，HALT 落在多工具批次中途须补全 tool_result 占位），届时 emit 演进为返回终止意图供 loop 短路。

---

## 2026-08-24 · M2 第二步完成（崩溃隔离·防线 1/2 + 测试 + CHEATSHEET 补充）

- **防线 1 落地**：`HookManager.emit` 给每个回调包 `try/except`——单个回调抛异常 → `logger.warning` 记一条（hook_name + 回调名 `getattr(callback,"__name__")` + 异常）→ 跳过继续，其余照常、不掀翻内核。`except Exception` 而非 `BaseException`（Ctrl-C 的 `KeyboardInterrupt` 必须放行）。
- **通道边界确认**：logger 走 stderr（给人看）、`ctx.history` 是模型唯一输入（给 AI 看），两条独立通道——回调崩溃细节不会进模型上下文。trace 事件流（给前端看）是 M2 步骤 6 的第三条通道。
- **测试**：`tests/test_hooks.py` 新增 4 例崩溃隔离（崩溃前后回调照跑 / emit 不抛 / 多崩夹正常全跑 / loop 里崩的观察者不中断 run）。全量 38 passed。
- **清理**：删 `loop.py` 遗留的过期 TODO(M2 第一步)；`hooks.py` 僵尸 TODO 随实现落地删除（TODO 生命周期 = 到实现落地为止）。
- **CHEATSHEET**：补 §11 观察者 / §12 崩溃隔离 / §13 优先级（决策 #4 欠账补上），§6「空钩子广播 `_emit`」同步为真实广播现状。

**下一步**：M2 第三步——拦截者机制（返回修改指令、内核校验后施加，HOOKS §A），届时 emit 收集回调返回值（可能演进为 emit_and_collect）。

---

## 2026-08-20 · M2 第一步完成（HookManager + 接入 _emit + 测试）

- **决策落定**：挂载方式选 **run() 参数**（决策 #12）——hook manager 是内核基础设施而非 run 数据；`_emit` 由模块级函数改为 `run()` 内部闭包（捕获 hooks+ctx），8 个调用点从 `_emit(X, ctx)` 改为 `_emit(X)`。讨论要点：挂 Context 的"零改动"优势在 M2 中段（拦截/错误裁决要重构 loop↔hooks 交互）会过期。
- **hooks.py**：`HookManager` 三个方法实现。register 用 `setdefault` 按需建键 + 追加；unregister 按回调对象身份（`is not`）过滤，删除全部重复匹配；emit 按 priority 升序调用，缺键空转，忽略返回值。docstring 从 TODO 清单改写为行为描述（M1 同款清理）。
- **loop.py**：`run()` 加 `hooks: HookManager | None = None` 参数（None=空操作，M0/M1 行为不变）；`_emit` 变闭包，接入 `hooks.emit`。
- **测试**：新增 `tests/test_hooks.py` 9 例——优先级排序、同优先级按注册序、注销、重复注册一次注销全删、空转、返回值忽略、loop 纯对话生命周期 6 事件、ctx 同一实例、工具路径 before/after_tool 每工具触发。全量 34 passed。
- **owner 定的两个实现级决策**：允许重复注册（观察者阶段无妨，拦截机制引入后再审视）；hook_name 不校验（未知钩子名自动建键）。
- **踩坑记录**：① "预填 10 个键 + `dir(Hook)` 内省"是过度设计，解决不存在的问题（键按需建即可，emit 用 get 兜底空转）；② register 的 append 误放进 `if not in` 分支，第二次注册同一钩子会静默丢回调——`setdefault` 一行同时解决。

**下一步**：M2 第二步——观察者机制：只读、排序、崩溃隔离（防线 1/2）。届时 emit 给每个回调包 try/except，单个回调崩溃不连坐。

---

## 2026-08-18 · M2 钩子系统规划（枢纽里程碑，第一步 TODO 已标）

- **M1 已完成并合并回 main**（见下一条）。M2 = 钩子系统内核（ROADMAP 原文），是后续所有模块的挂载点、整个架构的枢纽。设计总纲 `docs/HOOKS.md`；当前 `kernel/hooks.py` 只有 `Hook` 事件名枚举，`kernel/loop.py` 的 `_emit` 是空广播。
- **M2 范围**（ROADMAP §2）：10 个钩子点广播 + 观察者/拦截者 + 优先级排序 + 拦截者"返回修改指令、内核施加+校验"（HOOKS §A）+ 中断三意图 SKIP/HALT/REPLACE（§D）+ 错误裁决 HALT>RETRY>FEED_MODEL（§B）+ 四道防线 + 内核内建 trace 事件流。
- **建议分步**：
  1. **第一步（TODO 已标）**：实现 `kernel/hooks.py` 的 `HookManager`（register/unregister/emit + 按优先级排序），把 `loop.py` 的 `_emit` 空广播接入。**开工前先定挂载方式**：hook_manager 作为 `run()` 参数（与 provider/tools 平级，默认 None=空操作）vs 挂 Context——权衡可测试性 vs 模块访问便利。
  2. 观察者机制：只读、排序、崩溃隔离（防线 1/2）。
  3. 拦截者机制：返回修改指令、内核校验后施加（HOOKS §A 逐个施加）。
  4. 中断意图 SKIP/HALT/REPLACE + 短路规则（§D，HALT 多工具补全占位）。
  5. 错误处理：on_error/on_tool_error + 内核裁决（§B）。
  6. trace 事件流 + 四道防线完善（§5/§6）。
  7. 验收：一个空观察者 + 一个简单拦截者，验证挂载/优先级/崩溃降级/trace 输出（ROADMAP 验收补充）。
- **注意**：HOOKS §7 的机制（逐个施加、短路、HALT 补全）是**设计设想，实现时验证敲定**并回填该节；改动架构走三件套（改活文档 + 追加 DECISIONS + commit）。
- **开分支前**：按决策 #4 先产出 `kernel/CHEATSHEET.md` 的 M2 补充（观察者/拦截者模式、优先级、修改指令模式）。

**下一步**：开 `feat/m2-hooks` 分支，先定 HookManager 挂载方式，实现第一步（HookManager + 接入 `_emit`）。

---

## 2026-08-18 · M1 收尾完成（示例工具 + demo + 测试全绿，合并回 main）

- **示例工具 + demo**：`examples/tools.py` 新增 calculator（ast 白名单安全求值，禁 eval）与 read_file（三层防护：只读项目根内、拒隐藏文件、须存在）；`examples/m1_tools_demo.py` 端到端 demo，真实 provider 跑通（"计算 (2+3)*4" → 模型调 calculator → 结果回灌 → 回答 20），M1 ReAct 闭环验证成立。
- **测试补齐**：全量 25 passed。M0 5 用例适配块列表结构；新增 tools 8 例（注册/查重/call 五路径）、openai_compat 9 例（双向翻译）、loop 工具循环 3 例（闭环/错误回灌/max_iter 安全阀）。
- **微优化**：`_assistant_message` 用 truthy 判断 content，纯工具调用不再产生空 TextBlock。
- **收尾**：合并 `feat/m1-tools` 回 main（分支上 5 个 commit），ROADMAP M1 标记完成。

**下一步**：M2 钩子系统（分支 `feat/m2-hooks`）——把 `kernel/loop.py` 的 `_emit` 空广播接入 HookManager，范围与验收见 `docs/ROADMAP.md`。

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
