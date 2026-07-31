# PROVIDER — Provider 抽象层设计

> **状态**：设计定稿 · 对齐决策 #1/#7/#9 · 活文档 · 最后更新 2026-07-30
> 内核唯一依赖的模型接入接口，以及内部消息与各厂商 API 方言的双向翻译职责。
> 内核和模块**永不直接调用任何厂商 SDK**——一切经此层。写 provider 实现 / 新增厂商时读这份。

---

## 0. 职责与边界

**Provider 层是框架与外部模型世界的唯一接口**，把"厂商差异"这个脏活完全吸收，使内核和模块只面对统一的 Message 结构。

- 内核 → provider：给统一格式历史 + 可用工具，要"模型的下一步"。
- provider → 厂商：翻译成方言，发请求。
- 厂商 → provider：把响应翻译回统一 Message。
- provider → 内核：返回统一格式的 assistant 消息（含 text/tool_call 块）。

**边界铁律**：厂商特定的字段名、请求结构、鉴权方式，只存在于本层各厂商实现里，不泄漏到内核或模块。

---

## 1. 统一接口（内核依赖的能力）

确切方法签名在实现阶段定，此处定语义。

### 1.1 核心：chat（一次模型调用）
```
chat(messages: list[Message], tools: list[ToolSpec], options) -> ModelResponse
```
- 输入：统一格式历史、可用工具规格、调用选项（温度、max_tokens 等）。
- 输出 `ModelResponse`：翻译回统一格式的 assistant 消息（text 块 + 零或多个 tool_call 块）+ `stop_reason`（正常结束/要调工具/超长度/被安全拦截，统一枚举）+ `usage`（token 用量）。
- 同步阻塞（决策 #1）。

### 1.2 流式：chat_stream（前端实时显示）
```
chat_stream(messages, tools, options) -> Iterator[StreamEvent]
```
- 用**同步生成器**逐步 yield 事件（文本增量、工具调用开始/完成），满足 CLI 实时显示。
- 事件类型统一化，屏蔽各厂商流式协议差异（OpenAI SSE delta、Anthropic event stream）。
- 流结束后应能组装出与 `chat` 等价的完整 `ModelResponse`。
- **与钩子的关系**：流式下 `after_model_call` 退化为纯观察者（HOOKS §4.1）；"替换响应"须由 `before_model_call` 的 REPLACE 在调用前短路。

### 1.3 用量报告：usage
每次调用返回 token 用量（输入/输出/总计），供预算控制、成本统计模块消费。各厂商字段不同，本层归一化。

### 1.4 能力声明：capabilities
provider 声明自身能力供内核/模块查询：`supports_native_tools`（否则需 §3 prompt 模拟）、`supports_streaming`、`context_window`（供压缩模块参考）、`supports_parallel_tools`，其他按需扩展。

---

## 2. 翻译职责（双向）

- **请求方向（Message → 方言）**：角色映射；内容块（text/tool_call/tool_result）翻译；统一 ToolSpec → 厂商 function/tool schema。
- **响应方向（方言 → Message）**：厂商工具调用表示 → 统一 tool_call 块（保留 call_id）；stop_reason → 统一枚举；文本/思考 → text 块。
- **多工具结果聚合/拆分（决策 #7）**：内部为一对一。→OpenAI 直接映射为多条 `role:tool` 消息；→Anthropic 将连续多条内部 tool 消息**聚合**为一条 user 消息的多个 tool_result block（结果块前不得有文本，否则破坏并行工具机制）；←响应时把 Anthropic 一条消息内的多个 block 拆回多条内部消息。
- **错误标记**：内部 `tool_result.is_error` ↔ 各厂商错误表示（OpenAI 于 content 注明、Anthropic tool_result 的 is_error 字段）。

---

## 3. 无原生 function calling 的厂商（如部分 Ollama 模型）

能力声明 `supports_native_tools=False` 的 provider 需在本层内部模拟工具调用：
- **请求方向**：把工具规格以约定格式写进 prompt（工具列表 + 要求模型以特定 JSON 格式输出调用）。
- **响应方向**：解析模型文本输出，提取工具调用意图，构造成统一 tool_call 块。
- 解析失败：转成可喂回模型的提示（"请按格式重新输出"），不崩溃。
- 此复杂度**完全封装在本层**，内核对"这家不支持原生工具"无感知。

> 这是"厂商差异吸收在 provider 层"最典型的体现。

---

## 4. 鉴权与配置

- API key 等敏感信息经环境变量 / `.env`（已 gitignore，不进提交）。
- 各 provider 的 endpoint、模型名、超时等经配置声明。
- **OpenAI 兼容层**应允许自定义 base_url，一份实现覆盖 OpenAI 官方 + 大量国内中转 + 开源兼容服务。

---

## 5. 实现顺序（先一家跑通，其余留骨架）

- 接口从第一天即按"多 provider"设计（统一抽象基类/协议）。
- **先实现 OpenAI 兼容跑通**（决策 #9），其余（Anthropic/Ollama）作为骨架（声明能力、抛"未实现"）。
- 填第二家（Anthropic）时是检验 provider 抽象是否漏设计的最佳时机（验证多工具聚合翻译）。
- 联网核实：本地代理可用（决策 #8），写实现时对着真实 API 文档验证翻译逻辑。

---

## 6. 待实现阶段敲定的细节

- ModelResponse / StreamEvent / ToolSpec / capabilities 的确切类型。
- Provider 抽象形式（ABC 还是 Protocol）。
- stop_reason 统一枚举的完整取值。
- 流式事件类型的完整清单。
- 重试/超时/限速放本层还是交"重试模块"（初步：网络级基础重试在本层，语义级重试交模块）。
- token 计数：增可选 `count_tokens`，拿不到时 tiktoken 近似并声明为估算值（压缩模块 M4 前置）。
