# MESSAGE_PROTOCOL — 消息协议设计

> **状态**：设计定稿 · 对齐决策 #1/#7/#10 · 活文档 · 最后更新 2026-07-30
> 框架内部流通的统一消息数据结构。内核、钩子、所有模块共用。Provider 层负责它与各厂商 API 方言的双向翻译。动到消息结构 / provider 翻译 / 记忆序列化时读这份。

---

## 0. 设计目标与核心张力

**目标**：一套与厂商无关的消息结构，作为框架内部唯一的对话表示。它必须同时满足两个相互拉扯的需求：
1. **厂商无关**：内核和模块只认这一套，不感知 OpenAI/Anthropic/Ollama 差异。
2. **可无损翻译**：能双向翻译成各家方言而不丢信息。

**结论**：内部结构取"各家能力的超集 + 预留扩展位"，翻译的脏活全部封装在 provider 层。内部结构一旦稳定，不随某家 API 变动。

---

## 1. 四种消息角色

| 角色 | 含义 | 由谁产生 |
|------|------|---------|
| `system` | 系统指令 / 人设 / 全局约束 | 框架或模块设定 |
| `user` | 用户输入 | 前端 / 外部输入 |
| `assistant` | 模型输出（思考文本 + 零或多个工具调用请求） | 模型（经 provider 翻译入内部结构） |
| `tool` | 某个工具调用的执行结果或错误 | 工具执行后由内核产生 |

> Anthropic 把工具结果塞进 `user` 消息的 block；内部统一用独立 `tool` 角色表示，翻译时由 provider 适配。内部表示优先清晰，不迁就任一厂商。

### 1.1 system message 归属

- **内核持有一个基础 system message**（可配置，可为空），作为每次发给模型的历史开头。
- 模块通过 `before_model_call` 对其**追加/加工**（人设注入、规则补充），不替换内核基础部分。
- M0 阶段：内核持有、内容写死或从配置读，暂无模块加工。

---

## 2. 消息结构（概念定义）

确切类定义（dataclass / pydantic）在实现阶段落地，此处定语义。

```
Message
├─ role     : system | user | assistant | tool   （必有）
├─ content  : 结构化内容块列表（见 §3），统一用列表承载
├─ metadata : 自由扩展区（见 §5）
└─ id       : 该消息的唯一标识（用于关联、去重、trace）
```

**关键决策：`content` 统一为"内容块列表"，而非裸字符串。** 一条 assistant 消息可能同时含"思考文本"和"多个工具调用"，裸字符串无法承载；纯文本消息也用列表（单个 text 块），保持结构统一。

---

## 3. 内容块（Content Block）类型

| 块类型 | 承载 | 出现在 | 关键字段 |
|--------|------|-------|---------|
| `text` | 纯文本（含模型的"思考"叙述） | 任意角色 | `text` |
| `tool_call` | 一次工具调用请求 | assistant | `call_id`、`tool_name`、`arguments` |
| `tool_result` | 一次工具调用的结果/错误 | tool | `call_id`、`content`、`is_error` |

**关联机制**：`tool_call.call_id` 与对应 `tool_result.call_id` 相同，形成"请求—结果"配对，这是多工具场景（HOOKS §C）正确配对的基础。

一条 assistant 消息含多个 tool_call 示例：
```
assistant.content = [
    text("我需要先查天气，再查日历"),
    tool_call(call_id="c1", tool_name="get_weather", arguments={"city":"北京"}),
    tool_call(call_id="c2", tool_name="get_calendar", arguments={"date":"today"}),
]
```
对应产生的 tool 消息采用**一对一粒度**（一条 tool 消息 = 一个 tool_result 块，见 §4.1）。

**块类型可扩展**：未来多模态（`image`/音频块）、RAG 的 `citation` 块等作为新块类型加入，不破坏现有结构。这是"为未来留位置"的核心机制。

---

## 4. 工具结果的错误表示

工具执行失败时不抛裸异常进主流程，而是产生一个标记的 `tool_result` 块：
```
tool_result(call_id=..., content="错误信息文本", is_error=True)
```
`is_error=True` 让模型明确知道"这次调用失败了"，可自行改参数重试或换方案。内核默认行为（喂回模型）就是把这条带错误标记的结果塞回历史。provider 翻译时把 `is_error` 映射为各家表示。

### 4.1 多个工具结果的内部粒度：一对一（决策 #7）

内部统一 **"一条 tool 消息 = 一个 tool_result 块"**，靠 `call_id` 配对。合并/拆分交给 provider：
- **→ OpenAI**：每个 tool_call_id 对应一条独立 `role:tool` 消息——一对一直接映射，零成本。
- **→ Anthropic**：并行工具结果须放在同一条 user 消息内、作为多个 tool_result block 且结果前无文本——provider 将连续多条 tool 消息**聚合**为一条。

选一对一：粒度最细最好推理；与 HOOKS §C 天然契合；两个翻译方向都可行，"合并"比"拆分"易实现。

---

## 5. metadata 扩展区（模块的立足点）

每条消息带一个 `metadata` 自由区，供模块附加信息而不污染核心字段：
- **按模块命名空间隔离**：`metadata["rag"]`、`metadata["memory"]`、`metadata["trace"]`，各模块只读写自己的命名空间（铁律 5）。
- 典型用途：RAG 标注检索来源与分数；记忆标注是否已持久化、重要度；可观测记录序号与时间戳；token 统计标注本条 token 数。
- **metadata 不参与发给模型的内容**：provider 翻译时默认剥离，它是框架内部的旁路信息。

---

## 6. 序列化

消息结构必须可无损序列化/反序列化（记忆持久化、trace 落盘、多 agent 传递都需要）：
- 结构化格式（JSON 为基线），包含 `id`/`role`/`content`（含所有块）/`metadata`。
- 往返无损：`deserialize(serialize(msg)) == msg`。
- 块类型用显式 `type` 字段标注，保证未来新增块类型时旧数据仍可解析。

---

## 7. 对话历史（Conversation / History）

- 历史 = 有序的 Message 列表，持有在 `Context` 中。
- 内核主循环向历史追加消息；拦截者经"返回修改指令、内核施加"改动历史（HOOKS §A），不得就地篡改。
- 上下文压缩模块通过修改指令替换/精简历史；被替换的原始历史是否留存供回溯，由该模块决定并记 trace。

---

## 8. 待实现阶段敲定的细节

- Message / ContentBlock 的确切类型形式（dataclass 更轻 / pydantic 利于校验与序列化）。
- **`message.id` 生成方式**（已定，决策 #10）：单调自增计数器或 uuid4（实现阶段二选一），无"可复现"约束。M0 实现 Message 时即用。
- **`call_id` 生成方式**（已定，决策 #10）：透传厂商返回值（OpenAI `tool_call_id`、Anthropic `tool_use.id`），内核不生成；prompt 模拟的 provider 内部自造并保证同 run 唯一。M1 落地。
- 序列化遇未知块类型的降级策略。
- metadata 是否需要大小上限。
