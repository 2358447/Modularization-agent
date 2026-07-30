# MESSAGE_PROTOCOL — 消息协议设计

> **状态**：草稿 v0.1，待 owner 审阅
> **对齐决策**：#1（同步内核）；被 HOOKS.md 依赖
> **文档类型**：活文档
> **最后更新**：2026-07-30

> 定义框架内部流通的统一消息数据结构。内核、钩子、所有模块共用此结构。
> Provider 层负责在此结构与各厂商 API 方言之间双向翻译。
> 动到消息结构 / provider 翻译 / 记忆序列化时，读这份。

---

## 0. 设计目标与核心张力

**目标**：一套与厂商无关的消息结构，作为框架内部的唯一对话表示。

**核心张力**：该结构必须同时满足两个相互拉扯的需求——
1. **厂商无关**：内核和模块只认这一套结构，不感知 OpenAI / Anthropic / Ollama 的差异。
2. **可无损翻译**：能双向翻译成各家 API 方言而不丢信息。

各家差异举例：
- OpenAI：assistant 消息带 `tool_calls` 数组，工具结果是独立的 `role=tool` 消息，用 `tool_call_id` 关联。
- Anthropic：消息 `content` 是 block 数组，可含 `text` / `tool_use` / `tool_result` block；工具结果作为 `user` 消息里的 `tool_result` block。
- Ollama / 开源：部分模型无原生 function calling，工具调用需靠 prompt 约定 + 文本解析。

**结论**：内部结构取"各家能力的超集 + 预留扩展位"，翻译的脏活全部封装在 provider 层（见 PROVIDER.md）。内部结构一旦稳定，不随某家 API 变动而变动。

---

## 1. 四种消息角色

| 角色 | 含义 | 由谁产生 |
|------|------|---------|
| `system` | 系统指令 / 人设 / 全局约束 | 框架或模块设定 |
| `user` | 用户输入 | 前端 / 外部输入 |
| `assistant` | 模型输出（思考文本 + 零或多个工具调用请求） | 模型（经 provider 翻译入内部结构） |
| `tool` | 某个工具调用的执行结果或错误 | 工具执行后由内核产生 |

> 注：Anthropic 把工具结果塞进 `user` 消息的 block；内部结构统一用独立的 `tool` 角色表示，翻译时再由 provider 适配。内部表示优先清晰，不迁就任一厂商。

### 1.1 system message 归属

- **内核持有一个基础 system message**（可配置，可为空），作为每次发给模型的历史开头。
- 模块通过 `before_model_call` 的 modify 对其**追加/加工**（如人设注入、规则补充），不替换内核基础部分。
- M0 阶段：内核持有、内容写死或从配置读，暂无模块加工。

---

## 2. 消息结构（概念定义）

一条消息（Message）的概念字段。确切的类定义（dataclass / pydantic）在内核实现阶段落地，此处定语义。

```
Message
├─ role            : system | user | assistant | tool   （必有）
├─ content         : 结构化内容块列表（见 §3），统一用列表承载
├─ metadata        : 自由扩展区（见 §5）
└─ id              : 该消息的唯一标识（用于关联、去重、trace）
```

**关键决策：`content` 统一为"内容块列表"，而非裸字符串。**
- 一条 assistant 消息可能同时含"思考文本"和"多个工具调用"——裸字符串无法承载，必须是块列表。
- 纯文本消息（user 输入）也用列表表示（单个 text 块），保持结构统一，避免"有时是字符串有时是列表"的分支。

---

## 3. 内容块（Content Block）类型

`content` 是一个内容块列表。块类型如下：

| 块类型 | 承载 | 出现在 | 关键字段 |
|--------|------|-------|---------|
| `text` | 纯文本（含模型的"思考"叙述） | 任意角色 | `text` |
| `tool_call` | 一次工具调用请求 | assistant | `call_id`、`tool_name`、`arguments` |
| `tool_result` | 一次工具调用的结果/错误 | tool | `call_id`、`content`、`is_error` |

**关联机制**：`tool_call.call_id` 与对应 `tool_result.call_id` 相同，形成"请求—结果"配对。这是多工具场景（HOOKS §C）能正确配对结果的基础。

**一条 assistant 消息含多个 tool_call 的示例（概念）**：
```
assistant.content = [
    text("我需要先查天气，再查日历"),
    tool_call(call_id="c1", tool_name="get_weather", arguments={"city":"北京"}),
    tool_call(call_id="c2", tool_name="get_calendar", arguments={"date":"today"}),
]
```
对应产生的 tool 消息**统一采用"一条 tool 消息 = 一个 tool_result 块"的一对一粒度**（见 §4.1）：
```
tool.content = [ tool_result(call_id="c1", content="晴 25°C", is_error=False) ]
tool.content = [ tool_result(call_id="c2", content="3个日程", is_error=False) ]
```

**块类型可扩展**：未来多模态（图片 `image` 块、音频块）、引用来源（RAG 的 `citation` 块）等，都作为新块类型加入，不破坏现有结构。这是"为未来留位置"的核心机制。

---

## 4. 工具结果的错误表示

工具执行失败时（HOOKS 硬伤 B），不抛裸异常进主流程，而是产生一个 `tool_result` 块并标记：
```
tool_result(call_id=..., content="错误信息文本", is_error=True)
```
- `is_error=True` 让模型明确知道"这次调用失败了",可自行决定改参数重试或换方案。
- 内核默认行为（喂回模型）就是把这条带错误标记的结果塞回历史。
- provider 翻译时，把 `is_error` 映射为各家表示（OpenAI 在 content 里注明、Anthropic 的 tool_result 有 `is_error` 字段）。

### 4.1 多个工具结果的内部粒度：一对一

内部统一用 **"一条 tool 消息 = 一个 tool_result 块"**（一个工具调用对应一条结果消息，靠 `call_id` 配对）。合并/拆分交给 provider 层。

依据两家 API 的冲突要求：
- **OpenAI**：要求每个 `tool_call_id` 对应一条独立的 `role:tool` 消息（拆成多条）。内部一对一 → 直接映射，零成本。
- **Anthropic**（官方文档明确）：并行工具的所有结果必须放在**同一条 user 消息**内、作为多个 `tool_result` block，且结果前不能有文本内容，否则破坏并行工具机制。内部一对一 → provider 将连续的多条 tool 消息**聚合**为一条 user 消息的多个 block。

选一对一的理由：粒度最细、最好推理；与 HOOKS §C"每个工具独立走 before/after_tool_call、执行完即产出结果"的流程天然契合；两个翻译方向都可行，且"合并"比"拆分"实现简单。

---

## 5. metadata 扩展区（模块的立足点）

每条消息带一个 `metadata` 自由区，供模块附加信息而不污染核心字段。约定：

- **按模块命名空间隔离**：`metadata["rag"]`、`metadata["memory"]`、`metadata["observability"]`，各模块只读写自己的命名空间，互不干扰（呼应铁律 5：模块通过统一结构交互，不私下互传）。
- 典型用途：
  - RAG：`metadata["rag"] = {"retrieved_from": [...], "scores": [...]}` 标注这条消息注入了哪些检索来源。
  - 记忆：标注该消息是否已持久化、重要度评分。
  - 可观测：`metadata["trace"] = {"seq": 42, "ts": ...}` 记录序号与时间。
  - token 统计：标注本条的 token 数。
- **metadata 不参与发给模型的内容**：provider 翻译时默认剥离 metadata（除非某块本身是要发送的内容）。它是框架内部的旁路信息。

---

## 6. 序列化

消息结构必须可无损序列化/反序列化（记忆持久化、trace 落盘、多 agent 传递都需要）。

要求：
- 采用结构化格式（JSON 为基线）。
- 序列化**包含** `id`、`role`、`content`（含所有块）、`metadata`。
- 往返无损：`deserialize(serialize(msg)) == msg`。
- 块类型用显式 `type` 字段标注，保证未来新增块类型时旧数据仍可解析（未知块类型的降级策略在实现阶段定）。

---

## 7. 对话历史（Conversation / History）

- 历史 = 有序的 Message 列表，持有在 `Context` 中（ARCHITECTURE §2.6）。
- 内核主循环向历史追加消息；拦截者经"返回修改指令、内核施加"的机制改动历史（HOOKS 硬伤 A），不得就地篡改。
- 上下文压缩模块（`before_model_call`）通过返回修改指令替换/精简历史；被替换的原始历史是否留存供回溯，由该模块决定并记 trace。

---

## 8. 与其他文档的关系

- **被 HOOKS.md 依赖**：`before_model_call` 改的是历史（Message 列表），`before_tool_call` 读的是 `tool_call` 块，`after_tool_call` 产出 `tool_result` 块。
- **依赖方 PROVIDER.md**：provider 负责 Message ↔ 各厂商方言的双向翻译，是本结构与外部世界的唯一接口。
- **trace event 字段**与本结构一并在内核实现阶段最终敲定（HOOKS §9）。

---

## 9. 待内核实现阶段敲定的细节

- [ ] Message / ContentBlock 的确切类型形式（dataclass 还是 pydantic；pydantic 利于校验与序列化，dataclass 更轻）
- [ ] `id` / `call_id` 的生成方式（同步内核下不可用随机源的约束，见决策 #1 相关；需可复现）
- [ ] 序列化遇未知块类型的降级策略
- [ ] metadata 是否需要大小上限，防止无节制膨胀
