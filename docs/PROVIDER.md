# PROVIDER — Provider 抽象层设计

> **状态**：草稿 v0.1，待 owner 审阅
> **对齐决策**：#1（同步内核）、#8（多工具结果粒度）；依赖 MESSAGE_PROTOCOL.md
> **文档类型**：活文档
> **最后更新**：2026-07-30

> 定义内核唯一依赖的模型接入接口，以及内部消息与各厂商 API 方言的双向翻译职责。
> 内核和模块**永不直接调用任何厂商 SDK**——一切经此层。
> 写 provider 实现 / 新增厂商支持时读本文件。

---

## 0. 职责与边界

**Provider 层是框架与外部模型世界的唯一接口。** 它把"厂商差异"这个脏活完全吸收，使内核和模块只面对统一的 Message 结构（MESSAGE_PROTOCOL）。

- **内核 → provider**：给统一格式的历史 + 可用工具，要一个"模型的下一步"。
- **provider → 厂商**：翻译成该厂商 API 方言，发请求。
- **厂商 → provider**：把厂商响应翻译回统一 Message。
- **provider → 内核**：返回统一格式的 assistant 消息（含 text/tool_call 块）。

边界铁律：**厂商特定的字段名、请求结构、鉴权方式，只存在于本层的各厂商实现里，不泄漏到内核或模块。**

---

## 1. 统一接口（内核依赖的能力）

一个 Provider 实现必须提供以下能力。确切方法签名在内核实现阶段定，此处定语义。

### 1.1 核心：chat（一次模型调用）
```
chat(messages: list[Message], tools: list[ToolSpec], options) -> ModelResponse
```
- 输入：统一格式历史、可用工具规格、调用选项（温度、max_tokens 等）。
- 输出：`ModelResponse`，含：
  - 翻译回统一格式的 assistant 消息（text 块 + 零或多个 tool_call 块）
  - `stop_reason`（正常结束 / 要调工具 / 超长度 / 被安全拦截等，统一枚举）
  - `usage`（token 用量，见 §1.3）
- 同步阻塞（决策 #1）。

### 1.2 流式：chat_stream（前端实时显示）
```
chat_stream(messages, tools, options) -> Iterator[StreamEvent]
```
- 用**同步生成器**逐步 yield 事件（文本增量、工具调用开始/完成等），满足 CLI 实时显示（决策 #1：同步下流式用生成器）。
- 事件类型统一化，屏蔽各厂商流式协议差异（OpenAI SSE delta、Anthropic event stream 等）。
- 流结束后应能组装出与 `chat` 等价的完整 `ModelResponse`。

### 1.3 用量报告：usage
- 每次调用返回 token 用量（输入/输出/总计）。
- 供预算控制、成本统计模块消费（MODULES §4.2/§4.5）。
- 各厂商用量字段不同，本层归一化为统一结构。

### 1.4 能力声明：capabilities
provider 声明自身能力，供内核/模块查询后决定行为：
- `supports_native_tools`：是否支持原生 function calling（否则需 §3 的 prompt 模拟）
- `supports_streaming`：是否支持流式
- `context_window`：上下文窗口大小（供压缩模块参考）
- `supports_parallel_tools`：是否支持一次多工具调用
- 其他按需扩展

---

## 2. 翻译职责（双向）

### 2.1 请求方向：Message → 厂商方言
- 角色映射：内部 system/user/assistant/tool → 各厂商对应结构。
- 内容块翻译：text/tool_call/tool_result 块 → 厂商表示。
- 工具规格翻译：统一 ToolSpec → 厂商 function/tool schema。

### 2.2 响应方向：厂商响应 → Message
- 厂商的工具调用表示 → 统一 tool_call 块（生成/保留 call_id）。
- 厂商的 stop_reason → 统一枚举。
- 文本/思考内容 → text 块。

### 2.3 关键翻译点：多工具结果的聚合/拆分（决策 #8）
内部为"一条 tool 消息 = 一个 tool_result 块"（一对一）。翻译时：
- **→ OpenAI**：一对一直接映射为多条 `role:tool` 消息。
- **→ Anthropic**：将**连续的多条内部 tool 消息聚合**为**一条 user 消息**的多个 tool_result block，且**结果块前不得有文本内容**（否则破坏并行工具机制，见决策 #8 官方依据）。
- **← 响应**：Anthropic 一条消息内的多个 tool_result/tool_use block 拆回多条内部消息。

### 2.4 错误标记翻译
- 内部 `tool_result.is_error` ↔ 各厂商错误表示（OpenAI 于 content 注明、Anthropic tool_result 的 is_error 字段）。

---

## 3. 无原生 function calling 的厂商（如部分 Ollama 模型）

能力声明 `supports_native_tools=False` 的 provider，需在本层内部模拟工具调用：
- **请求方向**：把工具规格以约定格式写进 prompt（如"可用工具列表 + 要求模型以特定 JSON 格式输出调用"）。
- **响应方向**：解析模型文本输出，提取出工具调用意图，构造成统一 tool_call 块。
- 解析失败（模型没按格式输出）：按 HOOKS 错误处理——转成可喂回模型的提示（"请按格式重新输出"），不崩溃。
- 此复杂度**完全封装在本层**，内核对"这家不支持原生工具"无感知——它照常拿到统一的 tool_call 块。

> 这是"厂商差异吸收在 provider 层"最典型的体现，也是 owner 学习"框架替你做了多少脏活"的最佳样本。

---

## 4. 鉴权与配置

- API key 等敏感信息经环境变量 / `.env`（已被 .gitignore 忽略，铁律：不进提交）。
- 各 provider 的 endpoint、模型名、超时等经配置声明。
- OpenAI 兼容层：因大量国内中转/开源服务走 OpenAI 兼容协议，OpenAI 实现应允许自定义 base_url，一份实现覆盖多个兼容后端。

---

## 5. 实现顺序（先一家跑通，其余留骨架）

- 接口从第一天即按"多 provider"设计（统一抽象基类/协议）。
- **先实现一家跑通**，其余作为骨架（声明能力、抛"未实现"）。
- 首实现厂商在 ROADMAP 阶段与 owner 确定（候选：Anthropic tool_use 协议最干净适合做基准 / OpenAI 兼容生态最广 / Ollama 零成本可断网）。
- 联网核实：本地代理可用（决策 #9），写实现时对着真实 API 文档/调用验证翻译逻辑。

---

## 6. 与其他文档的关系

- **依赖 MESSAGE_PROTOCOL.md**：翻译的源与目标是 Message 结构。
- **被内核主循环依赖**：主循环调用 `chat`/`chat_stream` 推进（ARCHITECTURE §2.1）。
- **服务于模块**：预算/成本模块消费 usage，压缩模块参考 context_window。

---

## 7. 待内核实现阶段敲定的细节

- [ ] ModelResponse / StreamEvent / ToolSpec / capabilities 的确切类型
- [ ] Provider 抽象形式（ABC 还是 Protocol）
- [ ] stop_reason 统一枚举的完整取值
- [ ] 首个实现的厂商（与 ROADMAP 一并定）
- [ ] 流式事件类型的完整清单
- [ ] 重试/超时/限速等网络层策略放本层还是交"重试模块"（初步：网络级基础重试可在本层，语义级重试交模块）
