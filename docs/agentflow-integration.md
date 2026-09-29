# AgentFlow 与 fitMirror 客服项目融合学习文档

> 记录从影子路由到部分业务真实接管的改造。

## 1. 总体链路

```text
POST /api/chat/message -> chat router -> AgentFlowRuntime
-> 三路意图识别（LLM / Embedding / Pattern）
-> AgentOrchestrator -> ToolGateway -> MySQL / 商品 / 试穿 / RAG
-> 适配原前端响应 -> 写入 chat_messages
```

## 2. 改造前链路

`chat router -> chat_service -> 关键词分支/LangGraph -> 商品、试穿、RAG -> 前端`。

## 3. 阶段一：AgentFlow 适配层

- 改造后：`AgentFlowRuntime.handle` 统一负责分类、执行、指标和 fallback。
- 代码：`app/router/chat.py`、`agentflow_adapter/runtime.py`、`orchestrator.py`。
- 自测：`compileall -q app tests` 通过；`.env` 为 `AGENTFLOW_EXECUTION_MODE=takeover`。
- 面试：在 HTTP 入口增加可回退的 AgentFlow 执行边界。
- 边界：当前为部分业务接管。

## 4. 阶段二：三路意图识别

- 改造后：`IntentRouter` 融合 Pattern、Embedding 和 LLM，输出意图、实体、置信度和可解释路由。
- 代码：`agentflow_adapter/intent_router.py`、`tests/evaluate_intents.py`。
- 结果：20 条离线样本 accuracy/macro-F1/route consistency 均为 1.0，不代表线上准确率。

## 5. 阶段三：Hybrid RAG

先做意图门控，仅业务问题进入改写、召回和重排。有结果时由 `PolicyRAGAgent` 执行，无结果回退旧 RAG。外部 DeepSeek 不可用时不宣称 LLM 在线。

## 6. 阶段四：记忆

保留 MySQL 会话、消息、用户画像和 SQL 记忆，增加工作记忆、历史摘要、用户画像分层抽象。阶段 12 接入运行时闭环，阶段 14 修复跨会话记忆（画像提取 name 字段 + 注入 LLM prompt + 异步化）。不能夸大为生产级 Redis + Milvus 集群。

## 7. 阶段五：动态 Skills

Skills 从 JSON 加载，按 Agent 隔离，fingerprint 变化后热重载，`utf-8-sig` 兼容 BOM，损坏文件保留上一个有效版本。这是本地文件原型，不是配置中心。

## 8. 阶段六：ToolGateway 与分布式网关

统一做参数校验、TTL 缓存、超时、熔断和 fallback。DistributedToolGateway 是应用层原型，不等于生产集群。

## 9. 阶段七至九：监控、降权、Judge

Prometheus 记录延迟、成功率、低置信度和路由一致性；Monitor 将失败和延迟转为 penalty 反馈给编排；LLM-as-Judge 按相关性、准确性、完整性、有用性打分。当前都是原型闭环，不宣称生产级能力。

## 10. 阶段十：真实接管

- **改造前：** AgentFlow 只建议路由，业务全部走旧分支。
- **改造后：** 商品目录 `CatalogAgent -> MySQL`；商品介绍/建议 `ProductAdvisorAgent`；文本试穿 `TryOnAgent`；有效 FAQ/RAG `PolicyRAGAgent`。闲聊、图片复合、无 SKU、无知识结果和工具异常仍 fallback。
- **代码：** `agentflow_adapter/agents/*.py`、`orchestrator.py`、`runtime.py`、`app/services/chat_service.py`。
- **自测结果：** `chat_service.py` 语法已修复；compileall 、adapter 28 项、deep capability 8 项通过。原 SQL 记忆未删除。
- **面试讲法：** AgentFlow 不再只是旁路评分器，它通过 Orchestrator 调用真实 Agent 和业务工具，旧链路作为明确 fallback。
- **边界：** 不是全量接管；历史乱码消息没有批量修改；外部 LLM 不可用时不宣称在线。

## 11. 启动与验证

```powershell
cd D:\IT\fit-mirror-main\fitMirror-backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

检查 `GET http://127.0.0.1:8000/api/health`，客服请求查看 HTTP 状态、`executed_route`、`agentflow_executed` 和 `fallback_reason`。

## 12. 阶段 0：启动、中文和 500 基线修复

### 改造前链路

`前端 -> POST /api/chat/message -> AgentFlowRuntime.handle -> orchestrator.execute / legacy_handler -> 异常时第二次调用 legacy_handler（未捕获） -> HTTP 500`。

存在 4 个阻断性问题：
1. **HTTP 500**：`runtime.py` 的 except 块中再次调用 `legacy_handler()`，若该调用也失败（如 session_id 不存在触发外键约束），异常未被捕获，直接击穿为 HTTP 500。
2. **试穿回复乱码**：`chat_service.py` 的 `start_tryon_for_sku` 中中文字符串曾被 GBK→UTF-8 错误解码，变成 `?`。
3. **FAQ 漏匹配**：`faq_kw` 只有"退换货""退款"，缺"退货"，导致"退货政策"绕过 FAQ 分支走 LangGraph。
4. **前端错误消息乱码**：`api/index.js` 3 处 `????` 是损坏的中文。

### 改造后链路

`前端 -> POST /api/chat/message -> AgentFlowRuntime.handle -> orchestrator.execute -> 异常时 legacy_handler -> 再异常时 safe_fallback（HTTP 200）`。

所有客服场景保证 HTTP 200，中文正常，无 500。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/runtime.py` | except 块中 `legacy_handler()` 调用包裹 try/except，失败时返回 `agentflow_safe_fallback` 安全响应 |
| `app/services/chat_service.py` | `start_tryon_for_sku` 全部 `?` 乱码字符串替换为正确中文；`faq_kw` 增加"退货""换货" |
| `frontend/src/api/index.js` | 3 处错误消息 `????` 替换为"请求失败""服务器开小差了，请稍后重试" |

### 自测方法

```powershell
# 1. 编译检查
cd D:\IT\fit-mirror-main\fitMirror-backend
.\.venv\Scripts\python.exe -m compileall -q app

# 2. 重启后端
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

# 3. 无效 session 测试（应返回 200 而非 500）
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/chat/message -Method POST -Body '{"session_id":"nonexistent","user_id":"guest","content":"你好"}' -ContentType "application/json; charset=utf-8"

# 4. 6 场景测试：你好 / 有哪些商品 / 介绍TOP-001 / 试穿TOP-001 / 退货政策 / 发货物流
```

### 运行结果

| 场景 | HTTP | executed_route | agentflow_executed | 中文正常 |
|------|------|----------------|--------------------|----------|
| 无效 session | 200 | agentflow_safe_fallback | false | 是 |
| 你好 | 200 | legacy_langgraph_chat | false | 是 |
| 有哪些商品 | 200 | agent_catalog | true | 是 |
| 介绍TOP-001 | 200 | agent_product_advisor | true | 是 |
| 试穿TOP-001 | 200 | agent_tryon | true | 是（无 `?` 乱码） |
| 退货政策 | 200 | legacy_faq_rag | false | 是 |
| 发货物流 | 200 | legacy_faq_rag | false | 是 |

- compileall 通过
- 历史消息接口返回中文正常
- AgentFlow 真实接管：catalog / product_advisor / tryon 均 `agentflow_executed=true`

### 面试讲法

在 HTTP 入口增加了双层异常防护：AgentFlow 执行失败 → legacy fallback → legacy 也失败 → safe fallback，确保客服接口永不因 AgentFlow 异常返回 500。同时修复了历史编码问题导致的试穿回复乱码和 FAQ 关键词漏匹配。

### 当前边界和不能夸大的地方

- "退货政策""发货物流"仍返回 `legacy_faq_rag` + `rag_no_result`，因为知识库索引中无退换货政策文档，且 InMemoryVectorStore 按空格分词不适合中文检索（阶段 3 修复）。
- "你好"走 legacy LangGraph 路径，依赖外部 DeepSeek LLM 可达性；LLM 不可用时返回兜底文案，不宣称在线。
- 仅修复了 `start_tryon_for_sku` 的乱码，其他历史乱码消息未批量修改（`normalize_legacy_chat_text` 仅做显示层修复）。
- 这是代码层异常防护，不是生产级全链路熔断。

## 13. 阶段 1：AgentFlow 真实接管验证

### 改造前链路

意图分类仅靠 Pattern 关键词，部分自然语言表达（如"TOP-001 适合什么风格""店里现在有什么"）无法命中关键词，被分类为 `general_chat` 走 legacy LangGraph，Agent 代码存在但不执行。

### 改造后链路

补充 Pattern 关键词后，商品目录、商品介绍、风格咨询、文本试穿均由对应 Agent 真实执行，调用 MySQL 商品数据和试穿服务。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/intent_router.py` | `product_catalog` 增加"有什么商品""现在有什么""在售"；`product_advice` 增加"适合什么风格""什么风格""适合什么" |

### 自测方法

```powershell
# 真实接管场景测试
POST /api/chat/message {"content":"有哪些商品"}       -> agent_catalog
POST /api/chat/message {"content":"介绍一下 TOP-001"} -> agent_product_advisor
POST /api/chat/message {"content":"TOP-001 适合什么风格"} -> agent_product_advisor
POST /api/chat/message {"content":"我想试穿 TOP-001"} -> agent_tryon
POST /api/chat/message {"content":"店里现在有什么"}   -> agent_catalog

# 离线意图评测
.\.venv\Scripts\python.exe tests/evaluate_intents.py
```

### 运行结果

| 场景 | executed_route | agentflow_executed | intent |
|------|----------------|--------------------|--------|
| 有哪些商品 | agent_catalog | true | product_catalog |
| 介绍 TOP-001 | agent_product_advisor | true | product_intro |
| TOP-001 适合什么风格 | agent_product_advisor | true | product_advice |
| 试穿 TOP-001 | agent_tryon | true | product_tryon |
| 店里现在有什么 | agent_catalog | true | product_catalog |
| 介绍 DRESS-001 | agent_product_advisor | true | product_intro |
| 试穿 DRESS-001 | agent_tryon | true | product_tryon |

- 离线意图评测：20 条样本全部 intent accuracy=1.0
- Agent 真实调用 MySQL（商品数据来自 `build_catalog`/`db.get(Sku, ...)`）和试穿服务（`get_tryon_gallery`）

### 面试讲法

AgentFlow 通过 IntentRouter 分类后，Orchestrator 直接调用 CatalogAgent/ProductAdvisorAgent/TryOnAgent，Agent 内部通过 ToolGateway 调用真实业务 provider（MySQL 商品查询、试穿图库），不再是影子路由。旧 `chat_service` 分支仅作为 fallback。

### 当前边界和不能夸大的地方

- 意图识别目前仅 Pattern 路径生效（LLM/Embedding 未启用），20 条离线样本 accuracy=1.0 不代表线上准确率。
- `product_advice`（风格咨询）当前复用 ProductAdvisorAgent 的商品介绍逻辑，未做独立的风格推荐生成。
- 闲聊、无 SKU、无知识结果仍走 legacy fallback。

## 14. 阶段 2：LLM + Embedding + Pattern 三路意图融合

### 改造前链路

意图分类仅 Pattern 关键词路径生效（`AGENTFLOW_INTENT_LLM_ENABLED` 未设置），`classify_async` 直接返回 Pattern 结果，evidence 仅含 `source: pattern`。

### 改造后链路

`IntentRouter.classify_async` 三路融合：
1. **Pattern**（权重 0.20）：关键词子串匹配，即时返回
2. **Embedding**（权重 0.35）：硅基流动 BAAI/bge-m3（1024 维），query 与各意图 prototype 做余弦相似度
3. **LLM**（权重 0.45）：DeepSeek，返回 JSON intent + confidence

三路分数加权融合，取最高分意图。LLM/Embedding 任一失败自动降级为 Pattern，不产生 500。

### 代码文件

| 文件 | 改动 |
|------|------|
| `.env` | 新增 `AGENTFLOW_INTENT_LLM_ENABLED=true` |
| `app/agentflow_adapter/intent_router.py` | 已有融合逻辑（`classify_async`），本次验证其真实运行 |

### 自测方法

```powershell
# 启用三路融合后重启
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

# 检查响应 evidence 字段
POST /api/chat/message {"content":"有哪些商品"}
# 期望 evidence.source = "llm_embedding_pattern", evidence.llm = true, evidence.embedding = true

# 离线评测（20 条样本）
$env:AGENTFLOW_INTENT_LLM_ENABLED="true"
.\.venv\Scripts\python.exe tests/evaluate_intents.py
```

### 运行结果

| 场景 | intent | confidence | evidence.source | llm | embedding |
|------|--------|-----------|-----------------|-----|-----------|
| 有哪些商品 | product_catalog | 0.801 | llm_embedding_pattern | true | true |
| TOP-001 适合什么风格 | product_advice | 0.849 | llm_embedding_pattern | true | true |
| 退货政策是什么 | policy_faq | 0.777 | llm_embedding_pattern | true | true |

离线评测（20 条样本）：
- accuracy: 1.0
- macro_f1: 1.0
- route_consistency: 1.0
- 7 个意图类别全部 accuracy=1.0

### 面试讲法

意图识别采用三路加权融合：Pattern 负责关键词和实体（低延迟），Embedding 负责语义相似度（BAAI/bge-m3），LLM 负责复杂语义判断（DeepSeek）。权重 0.45/0.35/0.20，任一路失败自动降级，保证主链路可用。evidence 字段暴露三路参与情况和权重，可解释。

### 当前边界和不能夸大的地方

- 20 条离线样本 accuracy=1.0 是小规模评测结果，不代表线上准确率。
- LLM 调用增加约 1-2 秒延迟，未做缓存优化。
- Embedding 仅与意图 prototype 做余弦相似度，未引入负样本或 hard negative mining。
- 当前为应用层融合原型，不是生产级意图平台。

## 15. 阶段 3：Hybrid RAG 与状态区分

### 改造前链路

`PolicyRAGAgent -> RAG 检索` 存在两个问题：
1. 知识库索引只有 4 篇文档，缺 `faq_退换货政策.md`，"退货政策"类查询 `rag_no_result`。
2. `InMemoryVectorStore.search` 按空白分词，中文无空格 query 被当作整词，匹配率极低。
3. Health 端点只有 `llm_configured`，无法区分"配置存在"和"接口可达"。

### 改造后链路

1. 退换货政策文档入库（5 篇），中文 bigram 搜索修复，RAG 可返回有效文档。
2. Health 端点增加 `llm_reachable`（LLM 探活，60s 缓存）和 `rag_available`（文档数 > 0）。
3. PolicyRAGAgent 在 RAG 有结果时真实接管（`agent_policy_rag`），无结果时 fallback。

### 代码文件

| 文件 | 改动 |
|------|------|
| `storage/vectors/kb_index.json` | 新增 `faq_退换货政策.md` 文档（mem_5_0） |
| `app/rag/milvus_store.py` | `InMemoryVectorStore.search` 增加中文字符 bigram 匹配 |
| `app/router/health.py` | 新增 `llm_reachable`（带缓存探活）和 `rag_available`/`rag_doc_count` |
| `app/agentflow_adapter/intent_router.py` | "尺码"从 product_intro 移到 policy_faq |

### 自测方法

```powershell
# Health 端点
GET /api/health
# 期望: llm_configured=true, llm_reachable=true, rag_available=true, rag_doc_count=5

# RAG 接管场景
POST /api/chat/message {"content":"退货政策是什么"}  -> agent_policy_rag
POST /api/chat/message {"content":"发货物流政策"}    -> agent_policy_rag

# RAG 无结果降级
POST /api/chat/message {"content":"你们有会员制度吗"} -> fallback, HTTP 200
```

### 运行结果

| 场景 | route | agentflow_executed | RAG 有结果 |
|------|-------|--------------------|-----------|
| 退货政策是什么 | agent_policy_rag | true | 是 |
| 发货物流政策 | agent_policy_rag | true | 是 |
| 尺码怎么选 | legacy_faq_rag | false | 是（经 legacy 路径） |
| 你们有会员制度吗 | legacy_langgraph_chat | false | 否 |

Health：`llm_configured=true`, `llm_reachable=true`, `rag_available=true`, `rag_doc_count=5`

### 面试讲法

RAG 采用混合检索：InMemoryVectorStore 支持中文 bigram 匹配（不依赖分词器），5 篇 FAQ/政策文档入库。Health 端点区分 `llm_configured`（配置存在）、`llm_reachable`（真实探活）、`rag_available`（有文档）。PolicyRAGAgent 在检索到知识时由 AgentFlow 接管，无结果时安全降级到 legacy，HTTP 始终 200。

### 当前边界和不能夸大的地方

- 当前为内存关键词 + bigram 检索，不是语义向量检索（Milvus 未启用，阶段 4 验证）。
- "尺码怎么选"被 LLM 分类为 product_advice，经 legacy 路径返回 RAG 内容，route 非 agent_policy_rag。
- LLM 探活有 60s 缓存，不能实时反映 LLM 状态。
- 知识库仅 5 篇文档，覆盖退货、发货、尺码、商品说明、客服话术。

## 16. 阶段 6：Prometheus /metrics 端点

### 改造前链路

`prometheus_metrics.py` 依赖 `prometheus_client` 库（未安装），`AVAILABLE=False`，`/api/agentflow/metrics/prometheus` 返回 503。根路径无 `/metrics` 端点。

### 改造后链路

重写 `prometheus_metrics.py` 为不依赖外部库的轻量实现（Counter/Gauge/Histogram 自行渲染 Prometheus text format），main.py 增加根级 `GET /metrics` 端点。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/prometheus_metrics.py` | 重写为内置实现，新增 `route_consistency`、`tool_failures` 指标 |
| `main.py` | 新增 `GET /metrics` 端点，返回 `text/plain; version=0.0.4` |

### 自测方法

```powershell
# 先发一条客服消息产生指标
POST /api/chat/message {"content":"有哪些商品"}

# 抓取指标
GET /metrics
# 期望: HTTP 200, Content-Type: text/plain; version=0.0.4
# 包含 agentflow_requests_total, agentflow_request_latency_seconds, agentflow_tool_calls_total, agentflow_fallback_total, agentflow_agent_penalty
```

### 运行结果

```
HTTP 200
Content-Type: text/plain; version=0.0.4

# HELP agentflow_requests_total AgentFlow requests
# TYPE agentflow_requests_total counter
agentflow_requests_total 1.0

# HELP agentflow_tool_calls_total AgentFlow tool calls
agentflow_tool_calls_total{tool="catalog.build",success="true"} 1.0

# HELP agentflow_request_latency_seconds AgentFlow request latency
agentflow_request_latency_seconds_bucket{le="2.5"} 1
agentflow_request_latency_seconds_sum 2.33
agentflow_request_latency_seconds_count 1
```

- 指标涵盖：请求数、延迟直方图、工具调用（含成功/失败标签）、fallback 次数、Agent penalty、路由一致性、工具失败率
- 请求后 `agentflow_requests_total` 从 0 变为 1

### 面试讲法

不依赖 prometheus_client 库，自行实现 Counter/Gauge/Histogram 并渲染 Prometheus text format，通过根级 `/metrics` 端点暴露。指标包括请求量、延迟分布、工具调用成功率、fallback 次数、Agent penalty 等，可被 Prometheus 直接抓取。

### 当前边界和不能夸大的地方

- 进程内内存指标，重启后清零，无持久化。
- Histogram 桶为默认值，未按业务延迟分布调优。
- 未配置 Prometheus Server 和 Grafana，仅提供抓取端点。

## 17. 阶段 7：Monitor 动态降权影响路由

### 改造前链路

`runtime.py` 第 127 行 `self.monitor.record(decision.primary_agent, success=True, ...)` 始终记录成功，Monitor 无法累积失败 penalty。且 `classify_async` 在 pattern-only 路径直接返回，未应用 monitor weight。

### 改造后链路

1. `runtime.py`：根据 `owned`（Agent 是否真实接管）记录成功/失败到 Monitor。
2. `intent_router.py`：pattern-only 路径也应用 `monitor.weight()` 降权，penalty 高的 Agent confidence 被压低。
3. 失败 Agent 的 penalty 增加 → 下一次路由 confidence 降低 → 触发 low_confidence fallback。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/runtime.py` | `monitor.record(success=owned)` 替代固定 `success=True` |
| `app/agentflow_adapter/intent_router.py` | pattern-only 路径应用 monitor weight 降权 |

### 自测方法

```powershell
# 连续 3 次发送无结果 FAQ（PolicyRAGAgent 失败）
POST /api/chat/message {"content":"你们有会员制度吗"}  x3

# 第 4 次检查 penalty
POST /api/chat/message {"content":"退货政策是什么"}
# 响应 metadata.monitor_penalty 应 > 0

# /metrics 查看 penalty gauge
GET /metrics | Select-String "agentflow_agent_penalty"
```

### 运行结果

直接测试（pattern-only）：
- 失败前：PolicyRAGAgent penalty=0.0, weight=1.00, confidence=0.680
- 3 次失败后：penalty=0.75, weight=0.25
- 失败后：confidence=0.170（0.680 × 0.25）

HTTP 链路：
- 3 次失败后：PolicyRAGAgent penalty=0.625
- `/metrics`: `agentflow_agent_penalty{agent="PolicyRAGAgent"} 0.625`

### 面试讲法

Monitor 基于滑动窗口（20 条事件）计算 failure_rate 和 slow_rate，penalty = failure_rate×0.75 + slow_rate×0.25，权重 = max(0.2, 1-penalty)。IntentRouter 在三路融合和 pattern-only 路径均应用 monitor weight，失败 Agent 的 confidence 被压低，低于阈值时触发 fallback，实现"失败→降权→路由变化"闭环。

### 当前边界和不能夸大的地方

- 滑动窗口仅 20 条事件，penalty 变化较快，不是生产级长时间健康度。
- min_weight=0.2 保证 Agent 不会被完全排除，仅降权。
- penalty 影响 confidence，但明确 pattern 匹配的意图仍可能命中（pattern fallback）。
- 这是应用层降权原型，不是分布式智能调度。

## 18. 阶段 8：LLM-as-Judge 离线评测报告

### 改造前链路

无评测样本和评测脚本，无法量化意图准确率和回复质量。

### 改造后链路

1. `tests/eval_cases.json`：20 条意图样本 + 10 条回复质量样本（含关键词和参考答案要点）。
2. `tests/run_evaluation.py`：意图分类评测 + 调用真实客服接口获取回复 + LLM-as-Judge 四维评分（LLM 不可用时降级关键词规则评分）。
3. `docs/evaluation-report.md`：自动生成评测报告。

### 代码文件

| 文件 | 改动 |
|------|------|
| `tests/eval_cases.json` | 新建，20 意图 + 10 质量样本 |
| `tests/run_evaluation.py` | 新建，评测脚本（意图 + LLM-as-Judge + 报告生成） |
| `docs/evaluation-report.md` | 自动生成的评测报告 |

### 自测方法

```powershell
cd D:\IT\fit-mirror-main\fitMirror-backend
.\.venv\Scripts\python.exe tests/run_evaluation.py
# 查看 docs/evaluation-report.md
```

### 运行结果

意图分类（20 条）：
- accuracy: 100.00%
- macro_f1: 100.00%
- route_consistency: 100.00%
- 7 个意图类别全部 100%

回复质量（10 条，LLM-as-Judge）：
- relevance_avg: 4.9
- correctness_avg: 5.0
- completeness_avg: 4.5
- usefulness_avg: 4.6
- fallback_rate: 10.00%（仅"你好"走 legacy）
- p95_latency: 6882.6ms

### 面试讲法

建立离线评测体系：20 条意图样本测分类准确率，10 条回复样本用 LLM-as-Judge 四维评分（相关性/正确性/完整性/有用性，1-5 分）。LLM 不可用时降级为关键词规则评分，保证评测可复现。报告明确标注为离线评测，不夸大生产质量。

### 当前边界和不能夸大的地方

- 20 条意图样本 accuracy=100% 是小规模结果，不代表线上准确率。
- LLM-as-Judge 评分存在主观性，未做多评审员一致性校验。
- 评测在本地开发环境，p95 延迟不代表生产性能。
- 知识库仅 5 篇文档，FAQ 覆盖有限。

## 19. 阶段 4：Redis + Milvus 三级记忆（降级模式验证）

### 改造前链路

无用户记忆层，每次对话无状态，无法复用历史偏好和摘要。

### 改造后链路

三级记忆架构：
1. **L1 工作记忆（Redis）**：最近 N 轮对话，TTL 滑动窗口。
2. **L2 摘要记忆（Redis）**：会话摘要，30 天 TTL。
3. **L3 用户画像（Milvus）**：长期偏好向量检索（当前安全禁用，需独立隔离存储）。

降级策略：Redis 不可用时自动回退进程内内存；Milvus 未启用时 profile 操作抛 NotImplementedError（安全护栏），不影响主链路。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/memory.py` | 三级记忆实现（Redis + 本地降级 + profile 安全禁用） |

### 自测方法

```powershell
cd D:\IT\fit-mirror-main\fitMirror-backend
.\.venv\Scripts\python.exe -c "
import asyncio, sys
sys.path.insert(0, '.')
from tests.test_agentflow_deep_capabilities import test_memory_local_tiers_and_truncation, test_memory_fake_redis
asyncio.run(test_memory_local_tiers_and_truncation())
print('PASS: local tiers + truncation')
asyncio.run(test_memory_fake_redis())
print('PASS: fake redis path')
"
```

### 运行结果

- 本地降级模式：working memory 截断为 max_working_turns=2，summary 可保存和召回，profile 抛 NotImplementedError。
- Fake Redis 模式：rpush/ltrim/lrange/set/get 全部走 Redis 路径，degraded=False。
- 运行时不泄漏内存：runtime 处理后 working memory 为空，metadata 中不含 memory 字段。

### 面试讲法

三级记忆分层：L1 工作记忆放 Redis（最近对话），L2 摘要放 Redis（30 天 TTL），L3 用户画像放 Milvus（长期偏好向量检索）。Redis 不可用时自动降级到进程内内存，Milvus 用户画像因数据隔离要求暂未启用（安全护栏），确保主链路不受外部存储影响。

### 当前边界和不能夸大的地方

- 当前本地无 Redis/Milvus 实例，Redis 路径仅用 fake client 验证，未连真实 Redis。
- 用户画像（L3）故意禁用，未接入真实 Milvus，避免与知识库共用 collection 导致数据泄漏。
- 本地降级模式下记忆不跨进程，重启即丢失。
- 生产环境需要 Redis 集群 + 独立 Milvus collection + 访问控制。

## 20. 阶段 5：Skills 热加载演示

### 改造前链路

Agent 行为规则硬编码在代码中，修改规则需重启服务。

### 改造后链路

每个 Agent 独立 JSON 技能文件，按 SHA256 指纹热加载：
- 文件未变更：返回缓存版本（零 I/O）。
- 文件变更：重新解析并更新缓存。
- 文件损坏：保留上一个有效版本（安全降级）。

技能规则通过 `skills.inject()` 注入到 LLM routing prompt 中。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/skills.py` | SkillRegistry：指纹缓存 + 热加载 + 损坏降级 |
| `skills/PolicyRAGAgent.json` | 退货政策规则 |
| `skills/ProductAdvisorAgent.json` | 商品顾问规则 |
| `skills/TryOnAgent.json` | 试穿规则 |

### 自测方法

```powershell
cd D:\IT\fit-mirror-main\fitMirror-backend
.\.venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, '.')
from tests.test_agentflow_deep_capabilities import test_skills_hot_reload_and_corrupt_fallback
test_skills_hot_reload_and_corrupt_fallback()
print('PASS: hot reload + corrupt fallback')
"
```

### 运行结果

- 初始加载 `{"rules":["old"]}` → inject 返回 "old"。
- 修改为 `{"rules":["new"]}` → inject 返回 "new"（热加载生效，无需重启）。
- 修改为损坏 JSON `{broken` → inject 仍返回 "new"（保留上一个有效版本）。

### 面试讲法

Skills 热加载：每个 Agent 一个 JSON 技能文件，运行时按文件指纹（SHA256）判断是否变更，变更则重新加载，不变则走缓存。文件损坏时保留上一个有效版本，不会导致服务崩溃。规则通过 prompt 注入影响 Agent 行为，实现"不改代码、不重启服务"的规则迭代。

### 当前边界和不能夸大的地方

- 热加载基于请求时懒加载（每次 classify 检查指纹），不是文件监听推送。
- 仅 PolicyRAGAgent 的规则在 intent_router 中被注入，其他 Agent 的技能文件存在但未在主链路注入。
- 技能文件无版本管理和回滚机制，损坏降级仅保留最近一个版本。
- 生产环境需要文件变更通知（inotify/fsnotify）替代轮询指纹。

## 21. 阶段 9：HTTP Distributed ToolGateway

### 改造前链路

工具调用直接在进程内执行，无超时/重试/熔断/降级，远程工具不可用时链路阻塞或崩溃。

### 改造后链路

两层工具网关：
1. **ToolGateway**（进程内可靠性边界）：timeout + retry + circuit_breaker + cache + fallback。
2. **DistributedToolGateway**（分布式扩展）：在 ToolGateway 之上加 trace_id + transport（HTTP/消息队列），本地 provider 与远程 transport 解耦。

关键特性：
- `trace_id`：全链路追踪 ID，自动生成或透传。
- `timeout`：按工具名配置默认超时（catalog 10s / rag 30s / tryon 90s）。
- `retries`：失败重试（默认 0，可配置）。
- `circuit_breaker`：连续失败达阈值（默认 3）后熔断 10 秒，直接走 fallback。
- `fallback`：熔断或失败时返回降级结果。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/tool_gateway.py` | ToolGateway：timeout/retry/circuit_breaker/cache/fallback + Prometheus 指标 |
| `app/agentflow_adapter/distributed_gateway.py` | DistributedToolGateway：trace_id + transport 解耦 |

### 自测方法

```powershell
cd D:\IT\fit-mirror-main\fitMirror-backend
.\.venv\Scripts\python.exe -c "
import asyncio, sys
sys.path.insert(0, '.')
from tests.test_agentflow_deep_capabilities import test_gateway_transport_trace
test_gateway_transport_trace()
print('PASS: gateway transport + trace_id')
"
```

### 运行结果

- transport 模式：`DistributedToolGateway(transport=transport).call('lookup', trace_id='trace-1', sku='x')` → 返回 `{'tool':'lookup','trace':'trace-1'}`，trace_id 透传成功。
- ToolGateway 内置：超时（asyncio.wait_for）、重试（for attempt）、熔断（_CircuitState.failures >= threshold）、缓存（_CacheEntry）、降级（_resolve_fallback）。

### 面试讲法

工具网关分两层：内层 ToolGateway 做进程内可靠性（超时/重试/熔断/缓存/降级），外层 DistributedToolGateway 加 trace_id 和 transport 抽象，支持把工具调用从本地 provider 切换到 HTTP 或消息队列远程执行。熔断阈值 3 次、熔断窗口 10 秒，超时按工具类型差异化配置（试穿 90s、RAG 30s、目录 10s）。所有工具调用自动上报 Prometheus 指标。

### 当前边界和不能夸大的地方

- DistributedToolGateway 的 transport 是注入式接口，当前测试用 fake transport，未接入真实 HTTP/MQ。
- 熔断和重试是进程内状态，多实例部署时不共享熔断状态（需 Redis 或配置中心同步）。
- 缓存是进程内 LRU，不支持分布式缓存。
- 生产环境需要接入真实 HTTP transport（如 httpx.AsyncClient）、分布式熔断（Redis）、分布式追踪（OpenTelemetry）。

## 22. 评测与 Badcase 回流闭环页面

### 改造前链路

评测结果仅输出为 `docs/evaluation-report.md` 静态文档，无法在运营后台量化展示，Badcase 无法标记和回流，评测与迭代之间没有闭环。

### 改造后链路

后端新增 `/api/evaluation/*` 六个端点，前端新增「评测」页面（四个 Tab）：

1. **总览指标**：意图准确率、Macro F1、回复质量四维均分、Badcase 解决率，质量维度条形图。
2. **意图样本**：20 条意图分类明细，展示期望/预测意图、路由匹配、置信度、通过/失败。
3. **质量样本**：10 条回复质量明细，展示四维评分（颜色编码）、评审来源、延迟。
4. **Badcase 回流**：自动汇总意图失败 + 低质量回复（任一维度 < 4 或 fallback），支持状态流转（open → resolved/ignored）、重分类意图、填写期望回复和备注，反馈持久化到 JSON。

闭环链路：执行评测 → 识别 Badcase → 提交反馈（状态/重分类/期望回复）→ 统计更新 → 指导下一轮迭代。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/router/evaluation.py` | 新建，6 个端点：summary/intent-cases/quality-cases/badcases/feedback/run |
| `main.py` | 注册 evaluation_router |
| `frontend/src/api/index.js` | 新增 evalSummary/evalIntentCases/evalQualityCases/evalBadcases/evalSubmitFeedback/evalRun |
| `frontend/src/views/ops/EvaluationDashboard.vue` | 新建，四 Tab 评测看板 + Badcase 反馈弹窗 |
| `frontend/src/router/index.js` | 新增 `/ops/evaluation` 路由 |
| `frontend/src/layouts/AppShell.vue` | 新增「评测」导航入口 |
| `storage/evaluation/eval_cache.json` | 评测结果缓存（自动生成） |
| `storage/evaluation/badcase_feedback.json` | Badcase 反馈持久化（自动生成） |

### 自测方法

1. 打开 `http://localhost:5174/ops/evaluation`
2. 点击「执行全量评测」按钮，等待约 1 分钟（调用 LLM-as-Judge）
3. 查看总览指标卡片和质量维度条形图
4. 切换「意图样本」Tab，查看 20 条分类结果
5. 切换「质量样本」Tab，查看四维评分
6. 切换「Badcase 回流」Tab，点击「反馈」按钮，修改状态并提交
7. 查看总览中 Badcase 解决率是否更新

API 自测：
```powershell
# 总览
Invoke-RestMethod http://127.0.0.1:8000/api/evaluation/summary
# Badcase 列表
Invoke-RestMethod http://127.0.0.1:8000/api/evaluation/badcases
# 提交反馈
Invoke-RestMethod http://127.0.0.1:8000/api/evaluation/badcases/{id}/feedback -Method Post -Body '{"status":"resolved","feedback_note":"已修复"}' -ContentType "application/json"
```

### 运行结果

- 意图分类：20/20 正确，accuracy=100%，macro_f1=100%
- 回复质量：relevance=4.9, correctness=4.9, completeness=4.65, usefulness=4.7, p95=6726ms, fallback_rate=0.1
- Badcase：自动识别 2 条（1 条完整性不足 + 1 条 fallback），反馈后 resolve_rate=0.5
- 反馈持久化：`badcase_feedback.json` 正确存储 UTF-8 中文备注

### 面试讲法

把评测从静态文档升级为运营后台可交互页面：总览量化四大指标（意图准确率、Macro F1、质量均分、Badcase 解决率），意图和质量样本可逐条下钻，Badcase 自动汇总并支持状态流转和重分类反馈，形成"评测→发现问题→反馈→迭代"的闭环。后端用 JSON 文件持久化反馈，避免引入额外 DB 依赖。

### 当前边界和不能夸大的地方

- 评测样本仅 30 条（20 意图 + 10 质量），指标是小规模结果。
- Badcase 反馈存储在本地 JSON 文件，不支持多用户协作和版本历史。
- 重分类意图和期望回复仅记录，未自动回流到训练集或意图规则。
- LLM-as-Judge 评分存在主观性，未做多评审员一致性校验。
- 生产环境需要将反馈存储迁移到数据库，并接入 CI 自动回归评测。

## 23. 阶段 10：LLM 自动评测 + Badcase 自动回流闭环

### 改造前链路

评测仅用 Pattern 分类意图（无 LLM Judge），Badcase 反馈只记录在 JSON，**不会自动改任何东西**。运营需要手动根据反馈去改代码/知识库/技能文件，无回归校验，容易引入回归。

### 改造后链路

两条主线：

**一、LLM 自动评测增强**
1. 意图分类新增 LLM-as-Judge：固定意图枚举 + 强制 JSON 输出（intent/confidence/reason），不可用时降级 Pattern。
2. 回复质量 LLM Judge 新增 `failure_reason` 字段，低分 case 自动归因。

**二、Badcase 自动回流引擎（三条路径 + 回归校验闸门）**
1. **路径 A 意图规则**：从 badcase query 提取关键词（LLM 优先，降级规则法），追加为低权重（0.6×）动态规则，带 source/badcase_id 可追溯。
2. **路径 B 知识库**：检查 KB 是否已覆盖，未覆盖则 LLM 生成候选文档入库，入库后校验检索命中。
3. **路径 C Agent Skills**：从 expected_reply 提取行为规则，追加到对应 Agent 的 skills JSON（去重）。
4. **回归校验闸门**：每次改动后跑全量意图评测集，accuracy 下降则回滚；知识库入库后检索未命中则回滚。

闭环链路：评测 → 识别 Badcase → 运营填写期望回复 → 点「自动回流」→ 引擎自动选路径 → 回归校验通过则合并 → Badcase 自动标记 resolved。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/feedback_engine.py` | 新建，FeedbackEngine：三条回流路径 + 回归校验 |
| `app/agentflow_adapter/intent_router.py` | 新增 `add_dynamic_rule/remove_dynamic_rule/list_dynamic_rules`，动态规则权重 0.6× |
| `app/router/evaluation.py` | 新增 `_llm_intent_judge`、`failure_reason`、`POST /badcases/{id}/apply`、`GET/DELETE /dynamic-rules` |
| `frontend/src/api/index.js` | 新增 `evalApplyBadcase/evalDynamicRules/evalRemoveRule` |
| `frontend/src/views/ops/EvaluationDashboard.vue` | Badcase 表格新增「失败原因」列 + 「自动回流」按钮 |
| `skills/ProductAdvisorAgent.json` | 自动回流追加规则示例 |

### 自测方法

1. 打开 `http://localhost:5174/ops/evaluation` → Badcase 回流 Tab
2. 对 open 状态的 badcase 点「反馈」，填写期望回复后提交
3. 点「自动回流」按钮，观察成功/失败提示
4. 查看 `skills/*.json` 是否追加了规则
5. 验证回归校验：故意添加错误规则应被拒绝

API 自测：
```powershell
# 提交反馈（填写期望回复）
Invoke-RestMethod http://127.0.0.1:8000/api/evaluation/badcases/{id}/feedback -Method Post -Body '{"status":"open","expected_reply":"..."}' -ContentType "application/json"
# 自动回流
Invoke-RestMethod http://127.0.0.1:8000/api/evaluation/badcases/{id}/apply -Method Post
# 查看动态规则
Invoke-RestMethod http://127.0.0.1:8000/api/evaluation/dynamic-rules
```

### 运行结果

意图回流验证：
- query="支付异常" → 提取关键词["支付异常"] → 动态规则追加 → 回归 100%→100% 通过 → 应用成功
- query="你好"→policy_faq（错误）→ 回归 100%→95% → **拒绝并回滚**（闸门生效）

质量回流验证：
- badcase "TOP-001 适合什么风格" → 填写期望回复 → 自动回流
- 知识库路径：检测到已有文档，跳过（不重复入库）
- Skills 路径：提取规则"推荐服装时需说明品类、风格、适用场景和搭配建议" → 追加到 ProductAdvisorAgent.json → 成功
- Badcase 状态自动变为 resolved

### 面试讲法

把评测闭环从"手动记录"升级为"自动回流"：LLM-as-Judge 对意图和回复质量自动打分并给出失败原因；Badcase 回流引擎分三条路径——意图规则自动提取关键词生成低权重动态规则、知识库自动补充文档、Agent Skills 自动追加行为规则。每条路径都有回归校验闸门：意图规则改动后必须跑全量评测集，accuracy 不下降才合并，否则回滚；知识库入库后必须检索命中才保留。动态规则权重打 6 折且带 source 追溯，防止误学习覆盖人工规则。

### 当前边界和不能夸大的地方

- 回流是"半自动"：运营仍需先填写期望回复/重分类意图，引擎才执行自动回流，不是全自动无人值守。
- 动态规则存储在进程内存，服务重启后丢失（需持久化到 DB 或配置文件）。
- 回归校验仅覆盖意图 accuracy，未覆盖回复质量回归（质量回归需重跑 LLM Judge，成本高）。
- LLM 提取关键词/规则存在不稳定性，可能提取出无效规则（虽有回归闸门兜底）。
- 知识库回流用 expected_reply 生成文档，质量依赖 LLM 生成能力，可能引入不准确信息。
- 生产环境需要：动态规则持久化、定时自动评测调度、多 Judge 一致性校验、回流操作审计日志。

## 24. 评测数据来源说明：离线评测 vs 线上采集

### 当前状态（阶段 10）

评测样本全部来自 `tests/eval_cases.json` 人工编写的固定样本集（20 条意图 + 10 条质量），属于**离线评测（offline evaluation）**。

| 数据 | 来源 | 是否实时 |
|------|------|---------|
| 意图样本 | `eval_cases.json` 人工编写 | 固定 |
| 质量样本 | `eval_cases.json` 人工编写 | 固定 |
| 客服回复 | 评测时实时调用 `/api/chat/message` | 实时 |
| LLM 评分 | 评测时实时调用 LLM Judge | 实时 |
| Badcase | 从固定样本评测结果中筛选 | 基于固定样本 |

### 离线评测的边界和局限

1. **覆盖范围有限**：仅 30 条人工样本，无法发现真实用户遇到的新问题（长尾 query、口语化表达、图片输入等）。
2. **不可发现新 badcase**：真实用户对话中的坏回复不会自动进入评测集，运营只能靠人工反馈。
3. **样本偏差**：人工编写的样本可能偏向"理想输入"，与真实用户输入分布不一致。
4. **回归校验局限**：回归校验只能保证固定样本集不退化，不能保证真实场景不退化。
5. **无线上反馈闭环**：badcase 回流只针对离线样本，线上真实 badcase 无自动采集链路。

### 线上采集能力（阶段 11 新增）

在 `/api/chat/message` 接口中增加异步 LLM 质检：用户收到回复后，后台异步调用 LLM Judge 对回复打分，低分自动写入 Badcase 列表，标记 `source=online`，与离线评测的 `source=offline` 区分。详见阶段 11。

## 25. 阶段 11：线上真实 Badcase 自动采集

### 改造前链路

只有离线评测（固定 30 条样本）能产出 badcase，真实用户对话中的坏回复无法被自动发现，运营只能靠人工反馈，长尾问题无人知晓。

### 改造后链路

```
用户发送消息 → /api/chat/message
    ↓
客服回复返回给用户（不阻塞）
    ↓ 后台 BackgroundTasks 异步执行
LLM Judge 对回复四维打分
    ↓ min_score < 4
写入 badcase_feedback.json，标记 source=online
    ↓
运营在 Badcase 列表「线上」筛选中看到
    ↓
填写期望回复 → 自动回流（同阶段 10 流程）
```

线上 badcase 与离线 badcase 共用同一套回流引擎和回归校验闸门。

### 代码文件

| 文件 | 改动 |
|------|------|
| `app/agentflow_adapter/online_badcase.py` | 新建，`collect_online_badcase`：异步 LLM 质检 + 低分入库 |
| `app/router/chat.py` | `send_message` 加入 `BackgroundTasks`，回复后异步触发采集 |
| `app/router/evaluation.py` | `_build_badcases` 增加 `source` 字段和线上 badcase 合并；`/badcases` 支持 `?source=online/offline`；summary 增加 online_count/offline_count |
| `frontend/src/views/ops/EvaluationDashboard.vue` | Badcase 列表增加「来源」列 + 来源筛选 tab（线上/离线/全部来源）；总览卡增加线上/离线计数 |

### 自测方法

1. 打开客服对话页，发送一条客服可能答不好的问题（如"这件衣服面料成分是什么会不会起球"）
2. 等待约 15 秒（后台 LLM Judge 打分）
3. 打开 `http://localhost:5174/ops/evaluation` → Badcase 回流 Tab
4. 点「线上」筛选，应看到刚才的对话被自动采集为 badcase
5. 验证 API：`GET /api/evaluation/badcases?source=online`

### 运行结果

测试 query="这件衣服的面料成分是什么，会不会起球，能机洗吗"：
- 客服回复：询问具体哪件衣服 + 一般性面料说明
- LLM Judge 打分：relevance=3.0, correctness=4.0, completeness=2.0, usefulness=3.0
- 自动采集为线上 badcase，failure_reason="客服未针对用户询问的具体衣服给出确切面料成分、起球和机洗建议，仅提供一般性说明。"
- Badcase 列表「线上」筛选可见

### 面试讲法

离线评测只能覆盖固定样本，无法发现真实用户的长尾问题。我在 chat 接口加了一条异步质检链路：用户收到回复后，后台用 BackgroundTasks 异步调 LLM Judge 对回复四维打分，低于阈值的自动写入 badcase 库，标记 source=online 与离线样本区分。这样运营在 Badcase 页面能同时看到「离线样本失败」和「线上真实用户踩坑」两类问题，统一走回流引擎修复。关键设计是异步不阻塞用户响应、LLM 超时静默跳过不影响主流程、已处理的 badcase 不覆盖。

### 当前边界和不能夸大的地方

- 线上采集依赖 LLM Judge，每条用户对话多一次 LLM 调用（后台异步，不阻塞响应，但增加 LLM 成本）。
- LLM Judge 主观性：可能把好回复误判为 badcase（假阳性），也可能漏掉真 badcase（假阴性）。
- 线上 badcase 存储在 JSON 文件，高频对话下可能有并发写入问题（生产需迁移 DB + 分布式锁）。
- 未做采样策略：当前每条对话都质检，高 QPS 下 LLM 成本高，生产应按比例采样或只质检低置信路由。
- 线上 badcase 的回流同样走回归校验闸门，但回归校验只覆盖离线意图样本集，不能保证线上场景不退化。

---

## 25. 基础设施现状与部署规划（待实施）

> 本节记录当前运行时的基础设施状态，以及启用 Redis、Milvus、Docker 后能获得的能力。实际部署留待后续实施。

### 改造前链路（当前实际运行状态）

```
用户请求
   ↓
后端 (uvicorn, 直连宿主机)
   ├── MySQL (localhost:3306)        ← 业务数据：会话/消息/知识库元数据/SKU
   ├── AgentFlow 记忆 → 进程内内存    ← Redis 未启用，重启丢失
   └── RAG 检索 → InMemoryVectorStore ← Milvus 未启用，JSON 文件 + 关键词匹配
```

**当前 `.env` 实际配置：**
- `DB_TYPE=mysql`，`MYSQL_HOST=localhost:3306` → MySQL ✅ 在用
- 无 `AGENTFLOW_MEMORY_REDIS_ENABLED` / `REDIS_URL` → Redis ❌ 未启用（降级内存）
- 无 `USE_MILVUS` → Milvus ❌ 未启用（降级 JSON 关键词匹配）
- 项目无 `Dockerfile` / `docker-compose.yml` → Docker ❌ 未使用

### 改造后链路（部署启用后）

```
用户请求
   ↓
Nginx (负载均衡)
   ↓
后端 × N (多实例)
   ├── MySQL (Docker)          ← 业务数据
   ├── Redis (Docker)          ← AgentFlow 三级记忆持久化 + 分布式锁
   └── Milvus (Docker)         ← 语义向量检索
```

### 代码文件

| 组件 | 涉及文件 | 启用开关 |
|------|---------|---------|
| Redis 记忆 | `app/agentflow_adapter/memory.py` | `AGENTFLOW_MEMORY_REDIS_ENABLED=true` + `REDIS_URL` |
| Milvus 向量库 | `app/rag/milvus_store.py` | `USE_MILVUS=true` + `MILVUS_HOST/PORT/COLLECTION` |
| Docker 编排 | 待创建 `docker-compose.yml` | — |

### 各组件启用后能做的事

#### Redis（优先级：高，最易实施）

| 能力 | 当前问题 | 启用后 |
|------|---------|--------|
| 记忆持久化 | 对话摘要存进程内存，重启丢失 | 存 Redis，重启可恢复长对话 |
| 多实例共享记忆 | 多实例各有各的内存，负载均衡丢上下文 | 共享同一份会话记忆 |
| 自动过期 | 无 TTL，内存只增不减 | Redis key 带 TTL 自动清理 |
| 分布式锁 | 知识库重建/badcase 回流无锁，并发冲突 | 基于 Redis 的分布式锁 |

#### Milvus 向量库（优先级：中，需 embedding 成本）

| 能力 | 当前问题 | 启用后 |
|------|---------|--------|
| 语义检索 | 关键词重叠匹配，"起球"匹配不到"面料成分" | embedding 向量相似度，语义相关即命中 |
| 大规模知识库 | JSON 文件几百条到顶 | 百万级向量毫秒级检索 |
| 持久化 | 向量存 JSON，与后端进程耦合 | 独立存储，重启不丢 |
| 增量索引 | 上传新文档可能需重建 | 直接插入向量，增量更新 |

> 前置：需要 embedding 模型（硅基流动 `bge-m3`，已在配置中）。

#### Docker 容器化（优先级：低，环境编排）

| 能力 | 当前问题 | 启用后 |
|------|---------|--------|
| 一键启动 | 每个组件手动装 | `docker-compose up` 一键拉起全部 |
| 环境一致 | 开发/生产环境靠手动对齐 | 镜像保证完全一致 |
| 水平扩展 | 单实例 | 后端多实例 + Nginx 负载均衡 |
| 资源隔离 | 组件共用宿主机 | 独立容器，互不影响 |

### 自测方法（明天实施时验证）

1. **Redis**：起 Redis 容器 → 配置 `.env` → 重启后端 → 长对话后重启后端，验证记忆是否恢复
2. **Milvus**：起 Milvus 容器 → 配置 `.env` → 重启后端 → 上传文档后用语义相近但字面不同的 query 测试检索
3. **Docker Compose**：`docker-compose up -d` → 验证 MySQL/Redis/Milvus/后端/前端全部健康

### 运行结果

待实施后补充。

### 面试讲法

> "项目的 Redis 和 Milvus 在代码层已经做了完整支持，但当前演示环境为了降低部署门槛，降级为内存存储和 JSON 关键词匹配。生产部署时只需改 `.env` 开关即可启用 Redis 持久化记忆和 Milvus 语义检索，无需改代码。"

### 当前边界和不能夸大的地方

- **不能说"项目已经用了 Redis 和 Milvus"**：代码有支持，但当前环境未启用，实际跑的是降级方案。
- **不能说"已经容器化部署"**：项目没有 Dockerfile，所有服务直连宿主机。
- **不能夸大当前 RAG 能力**：当前是关键词匹配，不是语义检索，检索质量有限。
- **启用 Milvus 需要成本**：embedding 调用要花钱，且需重新入库所有文档。
- **Docker 部署是计划，不是已完成**：还没有 docker-compose.yml，需要从零写。

---

## 26. 记忆系统接入与 Docker 容器化（阶段 12）

### 改造前链路

```
用户请求
    ↓
AgentFlowRuntime.handle()
    ├── 路由分类（IntentRouter）
    ├── 执行业务（legacy_handler / orchestrator）
    ├── 监控记录（Monitor + Prometheus）
    └── 返回结果
    ❌ MemoryManager 实例存在但从未调用
    ❌ 无工作记忆存储、无摘要、无用户画像
    ❌ 无 Dockerfile / docker-compose.yml
```

### 改造后链路

```
用户请求
    ↓
AgentFlowRuntime.handle()
    ├── 1. 对话前回忆：memory.recall(user_id, session_id)
    │     → 获取 working（最近 N 轮）+ summaries（历史摘要）+ profiles（用户画像）
    │     → Redis 未启用时三层均降级为进程内存
    ├── 2. 路由分类 + 执行业务（不变）
    ├── 3. 对话后存储：memory.append_turn(user + assistant)
    │     → 工作记忆追加，超过 max_working_turns 自动截断
    ├── 4. 每 10 轮触发摘要 + 画像提取：
    │     ├── _generate_summary() → LLM 生成会话摘要 → save_summary()
    │     └── _extract_profile() → LLM 提取画像属性 → save_profile()
    └── 5. 返回结果 + memory 字段 {recall, store, summary, profile}

三层记忆存储设计：
    ├── L1 工作记忆  → Redis List（RPUSH + LTRIM 保留最近 20 轮）
    ├── L2 会话摘要  → Redis String（SET 带 30 天 TTL）
    └── L3 用户画像  → Redis Hash（HSET 带 90 天 TTL，LLM 提取结构化属性）

Docker 部署（docker-compose up）:
    ├── MySQL 8.0（业务数据）
    ├── Redis 7（三层记忆持久化，.env 开关控制）
    ├── Backend（FastAPI，直连 MySQL + Redis）
    └── Frontend（Vite build → Nginx 静态托管 + 反代 /api）
```

### 代码文件

| 文件 | 改动 |
|------|------|
| [runtime.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/agentflow_adapter/runtime.py) | `handle()` 接入 `recall` → `append_turn` → `_generate_summary` + `_extract_profile`；每 10 轮触发摘要和画像 |
| [memory.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/agentflow_adapter/memory.py) | `save_profile` 从 `NotImplementedError` 改为 Redis Hash + 内存降级实现；新增 `get_profile()`；`recall` 接入画像查询 |
| [docker-compose.yml](file:///D:/IT/fit-mirror-main/docker-compose.yml) | 新建：MySQL + Redis + backend + frontend 四服务编排 |
| [fitMirror-backend/Dockerfile](file:///D:/IT/fit-mirror-main/fitMirror-backend/Dockerfile) | 新建：Python 3.11-slim + 依赖安装 |
| [frontend/Dockerfile](file:///D:/IT/fit-mirror-main/frontend/Dockerfile) | 新建：多阶段构建（node build → nginx 托管） |
| [frontend/nginx.conf](file:///D:/IT/fit-mirror-main/frontend/nginx.conf) | 新建：静态文件 + /api 反代到 backend:8000 |

### 自测方法

**记忆系统**：
1. 启动后端，发送对话 `POST /api/chat/message`
2. 检查返回结果中 `memory` 字段：`store` 应为 `"ok"`
3. 连续对话多次，验证 `recall` 为 `true`（降级模式，因为没 Redis）
4. 达到 10 轮时 `summary` 应变为 `"generated"`

**Docker 部署**：
1. `docker-compose up -d` 拉起全部服务
2. `docker-compose ps` 验证四个服务都 healthy
3. 访问 `http://localhost:5174` 验证前端
4. 访问 `http://localhost:8000/docs` 验证后端 Swagger

### 运行结果

记忆系统验证（内存降级模式）：
```json
// 第 1 轮对话
"memory": { "recall": true, "store": "ok", "summary": null }

// 第 3 轮对话（工作记忆已累积）
"memory": { "recall": true, "store": "ok", "summary": null }

// 第 10 轮对话（触发摘要生成）
"memory": { "recall": true, "store": "ok", "summary": "generated" }
```

- `recall: true` = 降级模式（Redis 未启用，用进程内存）
- `store: "ok"` = 每轮对话成功写入工作记忆
- `summary: null` → `"generated"` = 10 轮后触发 LLM 摘要

Docker 配置已完成，待服务器部署验证。

### 面试讲法

> "项目的三级记忆系统（工作记忆/会话摘要/用户画像）在 MemoryManager 中实现了完整的存储和检索逻辑。我在 AgentFlowRuntime 的 handle 方法中接入了对前回忆 + 对话后存储 + 定时摘要的闭环。当前 Redis 未启用时降级为进程内存，Docker 部署时通过 .env 开关启用 Redis 即可获得持久化和多实例共享能力，代码无需修改。Docker Compose 编排了 MySQL + Redis + 后端 + 前端四服务，一键部署。"

### 当前边界和不能夸大的地方

- **记忆降级模式**：当前 Redis 未启用，三层记忆均存进程内存，服务重启丢失。不能说"记忆已持久化"。
- **用户画像非语义检索**：L3 用户画像用 Redis Hash / 内存存储，不是 Milvus 向量语义检索。LLM 从对话中提取结构化属性（身高/体重/风格/尺码/话题），按 user_id 存取。不能说"语义画像"。
- **画像 + 摘要每 10 轮触发**：`_extract_profile` 和 `_generate_summary` 在同一阈值触发，LLM 不可用时静默跳过。不能说"画像一定更新"。
- **摘要依赖 LLM**：`_generate_summary` 调用 DeepSeek 做摘要，LLM 不可用时静默跳过。不能说"摘要一定生成"。
- **Docker 未实际部署**：Dockerfile 和 compose 已写好，但未在服务器上实际运行验证。不能说"已经容器化上线"。
- **摘要质量未做评估**：LLM 生成的摘要和画像没有做人工质量检查，可能不够准确。
- **工作记忆截断**：只保留最近 20 轮（`max_working_turns=20`），更早的对话不在工作记忆中，只在摘要中保留。

---

## 27. API 调用链路日志系统（阶段 13）

### 改造前链路

```
用户请求 → FastAPI 路由 → 业务处理 → 返回
    ❌ 无请求级日志记录
    ❌ 无法追溯哪个接口出过什么错误
    ❌ 无法知道接口延迟分布
    ❌ 客服"暂时无法连接服务"无法定位根因
```

### 改造后链路

```
用户请求
    ↓
call_log_middleware（main.py）
    ├── 记录 method / path / client_ip / 请求参数
    ├── 调用业务处理
    ├── 记录 status_code / latency_ms / error_msg
    └── 写入 storage/logs/call_log_YYYYMMDD.jsonl + logger 输出

查询接口 GET /api/logs/calls
    ├── 按 limit / status_filter / path_filter 筛选
    └── 返回最近 N 条调用记录

前端 /ops/logs 页面
    ├── 状态码筛选（全部/2xx/4xx/5xx）
    ├── 路径关键词筛选
    └── 表格展示：时间、方法、路径、状态码、延迟、参数、错误
```

### 代码文件

| 文件 | 改动 |
|------|------|
| [main.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/main.py) | 替换原 `add_process_time` 为 `call_log_middleware`，记录全量调用日志 |
| [app/router/call_log.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/router/call_log.py) | 新建：`GET /api/logs/calls` 查询接口，支持状态码和路径筛选 |
| [frontend/src/views/ops/CallLogView.vue](file:///D:/IT/fit-mirror-main/frontend/src/views/ops/CallLogView.vue) | 新建：调用日志查看页面 |
| [frontend/src/api/index.js](file:///D:/IT/fit-mirror-main/frontend/src/api/index.js) | 新增 `getCallLogs` API |
| [frontend/src/router/index.js](file:///D:/IT/fit-mirror-main/frontend/src/router/index.js) | 新增 `/ops/logs` 路由 |
| [frontend/src/layouts/AppShell.vue](file:///D:/IT/fit-mirror-main/frontend/src/layouts/AppShell.vue) | 侧边栏新增"调用日志"入口 |

### 自测方法

1. 访问任意 API（如 `/api/health`、`/api/sku`）
2. 打开 `http://localhost:5174/ops/logs`
3. 验证表格展示调用记录：时间、方法、路径、状态码、延迟
4. 用状态码筛选"5xx"看错误请求，用路径筛选"chat"看客服调用
5. 查看日志文件 `storage/logs/call_log_YYYYMMDD.jsonl`

### 运行结果

```
GET /api/health        200  1334ms  (LLM 探活较慢)
GET /api/sku           200    28ms
POST /api/chat/message 200  4378ms  (LLM 调用 + fallback)
GET /api/logs/calls    200     1ms  (日志查询本身极快)
```

通过日志定位到客服"暂时无法连接服务"的根因：DeepSeek API 返回 402 Insufficient Balance（余额不足），runtime 安全兜底返回固定文案。日志文件中可看到完整调用链路。

### 面试讲法

> "项目实现了请求级调用链路日志中间件，每个 API 请求都会记录方法、路径、状态码、延迟和错误信息，写入 JSONL 日志文件。前端有专门的调用日志查看页面，支持按状态码和路径筛选。这样在排查问题时，比如客服回复'暂时无法连接服务'，可以直接在日志页面看到是哪个接口、什么状态码、什么错误原因，而不需要去翻服务器终端。"

### 当前边界和不能夸大的地方

- **仅记录 API 层调用**：不记录前端内部调用链路（如组件间通信），只记录 HTTP 请求级别。
- **日志按天文件存储**：自动清理超 7 天的日志文件（每次查询时触发 `_cleanup_old_logs`）。
- **不记录请求体原文**：出于安全考虑只记录 query params，不记录 POST body。
- **无分布式追踪**：单机日志，多实例部署时各实例日志独立，没有 trace_id 串联。
- **业务错误捕获**：runtime fallback 时通过 `X-Business-Error` response header 传递错误信息，中间件读取写入日志的 `error` 字段。
- **排除自引用**：`/api/logs/calls` 路径不被记录，避免日志查询产生日志。
- **前端分页**：每页 20 条，支持页码跳转，筛选切换自动回到第 1 页。
- **DeepSeek 余额不足**：当前客服 fallback 是因为 LLM API 余额耗尽，不是代码 bug。

---

## 28. 跨会话记忆修复（阶段 14）

> 修复"用户在 A 会话告诉 AI 名字，换到 B 会话 AI 不记得"的问题。

### 改造前链路

```
用户在 Session A 说"我叫小红"
    ↓
AgentFlowRuntime.handle()
    ├── _extract_profile() 提取画像
    │     ❌ JSON schema 没有 name 字段 → 名字从未被提取
    ├── memory.save_profile() 存储画像（缺 name）
    └── 返回响应

用户在 Session B 问"你还记得我叫什么吗"
    ↓
AgentFlowRuntime.handle()
    ├── memory.recall() 拿到画像（无 name）
    ├── chat_reply_node 生成回复
    │     ❌ 画像未注入 LLM system prompt → 模型看不到任何历史信息
    └── 回复"我没有记忆功能"或"第一次对话"

附加问题：
    ❌ _extract_profile 与 _generate_summary 同步执行（120s 超时）
       → LLM 接口抖动时阻塞对话响应，甚至超时失败
```

三个断裂点：**画像缺 name 字段**、**画像未注入 LLM prompt**、**同步提取阻塞响应**。

### 改造后链路

```
用户在 Session A 说"我叫小红，身高165，体重50"
    ↓
AgentFlowRuntime.handle()
    ├── 1. 对话前回忆：memory.recall() → working + summary + profile
    ├── 2. 路由分类 + 执行业务（生成回复）
    ├── 3. 对话后存储：memory.append_turn(user + assistant)  ← 同步，内存操作
    ├── 4. 后台异步任务（asyncio.create_task）：
    │     ├── _generate_summary() → 每 10 轮触发，LLM 15s 超时
    │     └── _extract_profile() → 每轮执行，JSON schema 含 name 字段
    │           → memory.save_profile(user_id, text, metadata={name,height,weight,style,...})
    └── 5. 立即返回响应（不等待后台任务）

用户在 Session B 问"你还记得我叫什么吗"
    ↓
AgentFlowRuntime.handle()
    ├── 1. 对话前回忆：memory.recall() → profile.metadata = {name:"小红", height:165, ...}
    ├── 2. chat_service 把 memory_profile 传入 LangGraph state
    ├── 3. chat_reply_node 把画像注入 LLM system prompt：
    │     【用户长期画像（跨会话回忆）】
    │     用户称呼：小红
    │     身高：165cm  体重：50kg
    │     风格偏好：甜美风格
    │     请在回复中自然地使用这些信息，让用户感到被记住。
    └── 4. LLM 回复"您是小红，身高165cm..."
```

关键设计：画像提取改为**后台异步任务**，LLM 超时从 120s 缩到 15s，对话响应不再被记忆提取阻塞。

### 代码文件

| 文件 | 改动 |
|------|------|
| [runtime.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/agentflow_adapter/runtime.py) | `_extract_profile` JSON schema 增加 `name` 字段；画像提取改为每轮执行（解耦摘要触发）；摘要+画像提取用 `asyncio.create_task` 后台执行 |
| [memory_global.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/agentflow_adapter/memory_global.py) | 新建：全局 memory 访问器 `get_memory_manager()`，避免 chat_service → runtime → chat_service 循环导入 |
| [factory.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/utils/factory.py) | `get_chat_model(timeout: int = 120)` 增加 timeout 参数，画像/摘要提取传 `timeout=15` |
| [chat_service.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/services/chat_service.py) | `process_message` 中 `get_memory_manager().get_profile(user_id)` 回忆画像，传入 LangGraph state |
| [state.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/graph/state.py) | `FitMirrorState` 增加 `memory_profile: Optional[dict]` 字段 |
| [pipeline_nodes.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/graph/nodes/pipeline_nodes.py) | `chat_reply_node` 把 `memory_profile` 注入 LLM system prompt |
| [chat.py](file:///D:/IT/fit-mirror-main/fitMirror-backend/app/router/chat.py) | 注册 `memory_manager` 单例到全局访问器 |

### 自测方法

```powershell
# 1. 启动后端
cd D:\IT\fit-mirror-main\fitMirror-backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

# 2. Python 端到端测试（避免 PowerShell 中文编码问题）
.\.venv\Scripts\python.exe -c "
import requests, time
uid, base = 'u_e2e', 'http://127.0.0.1:8000'

# Session A：告知名字和信息
sa = requests.post(f'{base}/api/chat/session', json={'user_id': uid, 'title': 'A'}).json()
sidA = sa['data']['session_id']
r1 = requests.post(f'{base}/api/chat/message', json={'session_id': sidA, 'user_id': uid, 'content': '你好，我叫李明，身高175，体重70公斤，喜欢运动休闲风格'}, timeout=60).json()
print('A1:', r1['data']['reply'][:80])

# 等待后台画像提取完成（LLM 调用约需 6-7 秒）
time.sleep(10)

# Session B：跨会话验证记忆
sb = requests.post(f'{base}/api/chat/session', json={'user_id': uid, 'title': 'B'}).json()
sidB = sb['data']['session_id']
r2 = requests.post(f'{base}/api/chat/message', json={'session_id': sidB, 'user_id': uid, 'content': '你还记得我叫什么名字吗？我的身高体重和风格偏好是什么？'}, timeout=60).json()
print('B1:', r2['data']['reply'])
"
```

### 运行结果

```
A1: 亲，您好李明～根据您提供的身高175cm、体重70kg，喜欢运动休闲风格...
B1: 当然记得呀，亲～您是李明，身高 175cm，体重 70kg，喜欢运动休闲风格，常穿 L/XL 码。今天想咨询商品、尺码还是搭配呢？

✅ 跨会话记忆验证通过：AI 成功回忆出姓名、身高、体重、风格
```

| 指标 | 值 |
|------|-----|
| A1 响应耗时 | ~11s（意图分类 + 对话 LLM） |
| B1 响应耗时 | ~7s |
| 画像提取 LLM 耗时 | ~6-7s（后台异步，不阻塞响应） |
| 跨会话回忆准确率 | 姓名/身高/体重/风格全部正确 |

### 面试讲法

> "项目的三级记忆系统在阶段 12 接入了运行时闭环，但实际测试发现跨会话记忆不生效。排查后定位到三个断裂点：一是画像提取的 JSON schema 没有 name 字段，用户名字从未被提取；二是回忆的画像没有注入到 LLM 的 system prompt，模型看不到历史信息；三是画像和摘要提取是同步执行的，LLM 超时 120 秒会阻塞对话响应。修复方案：给画像提取 schema 加上 name 字段并改为每轮执行（解耦摘要触发），把回忆的画像注入 chat_reply_node 的 system prompt，同时把画像和摘要提取改成 asyncio.create_task 后台任务，LLM 超时缩到 15 秒。这样对话响应不再被记忆提取阻塞，用户在新会话也能被 AI 叫出名字。"

### 当前边界和不能夸大的地方

- **画像提取异步延迟**：画像提取在后台执行（LLM 调用约 6-7 秒），如果用户在响应后立即开新会话，画像可能还没存完。实际场景中用户跨会话间隔通常远大于此，不影响体验。不能说"记忆实时生效"。
- **内存降级模式**：当前 Redis 未启用，画像存进程内存，服务重启丢失。不能说"跨重启记忆持久化"。
- **画像质量依赖 LLM**：`_extract_profile` 用 DeepSeek 提取结构化属性，LLM 可能提取错误或遗漏。不能说"画像 100% 准确"。
- **非语义检索**：L3 用户画像按 user_id 精确存取（Redis Hash / 内存 dict），不是 Milvus 向量语义检索。不能说"语义画像匹配"。
- **同步 append_turn 仍在响应路径**：工作记忆的 `append_turn` 是内存操作（快速），保持同步以确保下一轮 recall 能拿到本轮内容。只有 LLM 相关的摘要/画像提取是异步的。
- **后台任务无重试机制**：`asyncio.create_task` 的异常被静默捕获，画像提取失败不会重试。不能说"记忆一定更新成功"。
- **生产环境需要 Redis**：当前降级模式下单机内存，多实例部署时各实例记忆独立，负载均衡会丢上下文。

