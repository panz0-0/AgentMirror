# AgentFlow x fitMirror 客服项目改造任务书

> 交给其他 AI 执行。只允许围绕“AgentFlow 多智能体编排运行时真实接管 fitMirror 在线客服”改造，不得扩展无关功能。

## 一、固定范围与约束

- 工作目录：D:\IT\fit-mirror-main；后端目录：fitMirror-backend。
- 保留 MySQL 原有数据、SQL 记忆和表：chat_sessions、chat_messages、user_profiles、商品数据。
- Redis、Milvus 只能作为增强层，不能替代 MySQL 事实存储和聊天审计。
- 不要大范围重写 pp/services/chat_service.py，只做增量修复。
- 不得引入无关业务；不要删除数据；不要伪造线上指标；不要把原型包装成生产级。
- 每个阶段必须更新 docs/agentflow-integration.md，使用 UTF-8，严禁乱码。

## 二、目标真实链路

`	ext
前端客服 -> POST /api/chat/message -> AgentFlowRuntime
-> LLM + Embedding + Pattern 三路意图识别
-> AgentOrchestrator -> Agent / ToolGateway
-> MySQL 商品/聊天数据、RAG、试穿
-> 原前端响应契约 -> chat_messages
`

AgentFlow 必须执行真实业务，不能只是影子路由。目标配置：AGENTFLOW_EXECUTION_MODE=takeover。

## 三、按顺序执行

### 阶段 0：启动、中文和 500 基线

启动：

`powershell
cd D:\IT\fit-mirror-main\fitMirror-backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
`

检查 /api/health，用真实浏览器测试：你好、有哪些商品、商品介绍、实际 SKU 试穿、退货政策、历史会话。必须 HTTP 200、中文正常、无 Request failed with status code 500，查看 executed_route、gentflow_executed、
outing.primary_intent、fallback_reason。

### 阶段 1：AgentFlow 真实接管

验证：有哪些商品 -> gent_catalog；介绍商品/风格咨询 -> gent_product_advisor；试穿 SKU -> gent_tryon；有效退货政策 -> gent_policy_rag。确认 Agent 真实调用 MySQL、试穿和 RAG 工具，聊天仍写入 chat_messages。允许 fallback 但必须有 fallback_reason。

### 阶段 2：LLM + Embedding + Pattern 三路融合

Pattern 处理关键词和实体，Embedding 处理相似度，LLM 在可用时参与语义判断；不可用时安全降级。三路要真实参与加权融合，输出 primary_intent、intent_group、entities、confidence、各路分数和路由解释。至少 20 条离线样本，输出 accuracy、Macro-F1、route consistency，不能外推为线上准确率。

### 阶段 3：Hybrid RAG

实现：意图门控 -> 查询改写 -> 多子查询召回 -> 向量/关键词混合召回 -> 重排 -> PolicyRAGAgent。无结果或 LLM 不可用不能 500。区分 llm_configured、llm_reachable、
ag_available。

### 阶段 4：Redis + Milvus 三级记忆

MySQL=事实存储/审计/原 SQL 记忆；Redis=当前会话工作记忆和 TTL；Milvus=历史摘要、用户画像语义召回。验证 Redis 读写 TTL、Milvus 写入召回。依赖不可用时主链路仍 HTTP 200，回退 MySQL 或空记忆。

### 阶段 5：动态 Skills 热加载

按 Agent 隔离 JSON Skills；修改后无需重启生效；用 fingerprint/mtime 检测；兼容 UTF-8/BOM；错误 JSON 保留上次有效版本。这是本地文件原型，不是生产配置中心。

### 阶段 6：Prometheus 在线监控

提供 GET /metrics，包含 gentflow_requests_total、gentflow_request_latency_ms、gentflow_route_consistency_total、gentflow_fallback_total、gentflow_tool_calls_total、gentflow_tool_failures_total、gentflow_agent_penalty。请求前后要能看到变化，不要宣称完整生产监控平台。

### 阶段 7：Monitor 动态降权

完成：Agent 连续失败/超时 -> penalty 增加 -> Orchestrator 下次降低权重 -> 备用 Agent 或 fallback -> 指标记录。penalty 要有上限、衰减或清理。用可控 mock/failure 演示，不修改真实用户数据。

### 阶段 8：LLM-as-Judge 评测

完善 	ests/eval_cases.json、docs/evaluation-report.md；至少 20 条意图样本、10 条回复质量样本，评分相关性/准确性/完整性/有用性，统计 accuracy、Macro-F1、route consistency、fallback rate、平均延迟、p95。LLM 不可用可用 Mock/规则 Judge，但必须标注。

### 阶段 9：HTTP Distributed ToolGateway

实现 Agent -> POST /internal/tools/{tool_name} -> ToolGateway -> 业务工具；至少包含 request_id、参数校验、timeout、有限 retry、circuit breaker、fallback和结果 metadata。只做应用层 HTTP 原型，不引入无必要 MQ。

## 四、每阶段学习文档格式

在 docs/agentflow-integration.md 追加以下小节，不能只写“已完成”：

`markdown
## 阶段 X：阶段名称
### 改造前链路
### 改造后链路
### 代码文件
### 自测方法
### 运行结果
### 面试讲法
### 当前边界和不能夸大的地方
`

## 五、最终验收

- [ ] 后端健康、浏览器中文正常、客服无 500
- [ ] MySQL 原有数据、聊天记录、SQL 记忆仍在
- [ ] Catalog/ProductAdvisor/TryOn/有效 PolicyRAG 真实接管
- [ ] 三路意图有融合证据
- [ ] Redis 有读写 TTL、Milvus 有召回或明确降级
- [ ] Skills 无需重启热加载
- [ ] /metrics 可访问且请求后变化
- [ ] penalty 会影响后续路由
- [ ] Judge 评测报告存在且不夸大
- [ ] HTTP ToolGateway 可演示
- [ ] 每阶段文档完整

## 六、汇报格式

每阶段完成后只按以下格式汇报，禁止添加无关项目内容：

`markdown
# 阶段 X 完成
## 本阶段目标
## 实际修改文件
## 改造前链路
## 改造后链路
## 自测命令
## 自测结果
## 面试讲法
## 当前边界和不能夸大的地方
## 下一阶段
`

最终必须区分真实运行、降级、原型和未完成项。