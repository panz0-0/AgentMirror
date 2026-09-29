# AgentFlow × fitMirror 当前链路图

> 当前实现状态：AgentFlow 只做“影子意图路由”，不改变 fitMirror 原有业务执行分支。

## 1. 文本消息主链路

```mermaid
flowchart TD
    A[前端发送文本消息] --> B[POST /api/chat/message]
    B --> C[AgentFlowRuntime.handle]
    C --> D[IntentRouter.classify]
    D --> E[输出 IntentDecision\nprimary_intent / primary_agent / confidence]
    E -.影子结果，不接管执行.-> F
    B --> F[chat_service.process_chat_message]
    F --> G{原有业务路由}
    G -->|试穿| H[试穿业务]
    G -->|商品目录| I[商品目录业务]
    G -->|商品介绍/相似款| J[商品咨询业务]
    G -->|退款/退货/政策| K[FAQ / 政策处理]
    G -->|其他| L[LangGraph 客服兜底\n档案检查 / RAG / 通用聊天]
    H --> M[保留原业务返回字段]
    I --> M
    J --> M
    K --> M
    L --> M
    E --> N[写入 data.routing\n和 data.metadata.routing]
    M --> O[合并 routing 后返回前端]
    N --> O
    O --> P[保存业务消息]
```

### 这张图最关键的一点

```text
AgentFlow 当前回答：应该由哪个 Agent 处理？
fitMirror 当前决定：实际走原来的哪条业务分支？
```

所以当前并不是：

```text
AgentFlow 判断 → AgentFlow Agent 执行
```

而是：

```text
AgentFlow 判断（旁路记录） + fitMirror 原链路执行
```

## 2. 一个具体例子：用户说“我想找相似款”

```mermaid
sequenceDiagram
    participant U as 用户/前端
    participant R as /api/chat/message
    participant AF as AgentFlowRuntime
    participant IR as IntentRouter
    participant LS as legacy chat_service
    participant FE as fitMirror 业务分支

    U->>R: 我想找相似款
    R->>AF: handle(content, user_id, session_id)
    AF->>IR: classify(content)
    IR-->>AF: similar_product / ProductAdvisorAgent / confidence
    AF-->>R: routing 决策
    R->>LS: process_chat_message(...)
    LS->>FE: 执行原有商品咨询/相似商品逻辑
    FE-->>LS: reply + 商品/图片/动作等旧字段
    LS-->>R: legacy result
    R->>R: result.routing = decision
    R->>R: result.metadata.routing = decision
    R-->>U: 原有结果 + AgentFlow 路由信息
```

## 3. 图片与图文消息：当前不经过影子路由

```mermaid
flowchart TD
    A[图片消息] --> B[POST /api/chat/message/image]
    C[图文组合消息] --> D[POST /api/chat/message/compose]
    B --> E[chat_service.process_combined_message]
    D --> E
    E --> F[图片匹配 / 相似商品 / 文本兜底]
    F --> G[返回图片、商品或文本结果]
```

补充：`/api/chat/message/stream` 当前是先生成完整回复，再按字符发送 SSE，并不是模型 token 的实时生成流。

## 4. 当前已经接入的接口

```mermaid
flowchart LR
    A[客户端] --> B{接口}
    B -->|POST /api/chat/message| C[文本客服：AgentFlow 影子路由 + 旧链路]
    B -->|POST /api/agentflow/inspect-intent| D[只检查意图，不执行客服业务]
    B -->|POST /api/chat/message/image| E[图片链路：旧逻辑]
    B -->|POST /api/chat/message/compose| F[图文链路：旧逻辑]
    B -->|POST /api/chat/message/stream| G[旧业务生成后 SSE]
```

## 5. 下一步要变成的目标链路

```mermaid
flowchart TD
    A[用户消息] --> B[AgentFlowRuntime]
    B --> C[三路意图识别\nPattern + Embedding + LLM]
    C --> D[IntentDecision]
    D --> E{Orchestrator}
    E -->|高置信度| F[对应 Agent Handler]
    E -->|低置信度/异常| G[legacy fallback]
    F --> H[ToolGateway\n超时 / 熔断 / fallback]
    H --> I[fitMirror 原业务能力\n试穿 / 商品 / FAQ / RAG]
    G --> I
    I --> J[统一结果 + executed_route]
    J --> K[前端]
    J --> L[监控 / 评测 / Judge]
```

目标链路和当前链路的本质区别：

```text
当前：AgentFlow 只推荐，legacy 决定执行
目标：AgentFlow/Orchestrator 决定执行，legacy 作为 fallback
```

## 6. 建议下一步先加的观测字段

```json
{
  "routing": {
    "primary_intent": "product_tryon",
    "primary_agent": "TryOnAgent",
    "confidence": 0.68
  },
  "executed_route": "legacy_tryon"
}
```

其中：

- `routing`：AgentFlow 推荐的意图和 Agent。
- `executed_route`：fitMirror 实际执行的旧业务分支。
- 两者一致时，说明影子路由和旧路由判断一致。
- 两者不一致时，可以作为后续调优样本。
