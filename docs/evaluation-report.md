# AgentFlow 离线评测报告

> 注意：本报告为离线评测结果，不是线上生产质量报告。

## 一、评测范围

- 意图分类样本：20 条
- 回复质量样本：10 条
- 评测方式：意图 = Pattern 直接分类；回复质量 = LLM-as-Judge（失败降级规则评分）
- 评测日期：2026-09-29

## 二、意图分类结果

| 指标 | 值 |
|------|-----|
| total | 20 |
| correct | 20 |
| accuracy | 100.00% |
| macro_f1 | 100.00% |
| route_consistency | 100.00% |

### 各意图准确率

| intent | total | correct | accuracy |
|--------|-------|---------|----------|
| general_chat | 3 | 3 | 100.00% |
| policy_faq | 6 | 6 | 100.00% |
| product_advice | 2 | 2 | 100.00% |
| product_catalog | 2 | 2 | 100.00% |
| product_intro | 2 | 2 | 100.00% |
| product_tryon | 2 | 2 | 100.00% |
| similar_product | 3 | 3 | 100.00% |

## 三、回复质量结果

| 指标 | 值 |
|------|-----|
| relevance_avg | 4.9 |
| correctness_avg | 5.0 |
| completeness_avg | 4.5 |
| usefulness_avg | 4.6 |
| fallback_rate | 10.00% |
| p95_latency_ms | 6882.6 |

### 各样本明细

| query | route | agentflow | rel | corr | comp | use | judge | latency(ms) |
|-------|-------|-----------|-----|------|------|-----|-------|-------------|
| 有哪些商品 | agent_catalog | True | 5.0 | 5.0 | 5.0 | 5.0 | llm | 2116.3 |
| 介绍一下 TOP-001 | agent_product_advisor | True | 5.0 | 5.0 | 5.0 | 5.0 | llm | 1768.9 |
| 我想试穿 TOP-001 | agent_tryon | True | 5.0 | 5.0 | 5.0 | 5.0 | llm | 1729.7 |
| 退货政策是什么 | agent_policy_rag | True | 5.0 | 5.0 | 3.0 | 4.0 | llm | 4359.7 |
| 发货物流政策 | agent_policy_rag | True | 5.0 | 5.0 | 5.0 | 5.0 | llm | 4362.7 |
| TOP-001 适合什么风格 | agent_product_advisor | True | 4.0 | 5.0 | 3.0 | 3.0 | llm | 2909.7 |
| 店里现在有什么 | agent_catalog | True | 5.0 | 5.0 | 5.0 | 5.0 | llm | 3102.1 |
| 介绍一下 DRESS-001 | agent_product_advisor | True | 5.0 | 5.0 | 4.0 | 4.0 | llm | 2535.7 |
| 我想试穿 DRESS-001 | agent_tryon | True | 5.0 | 5.0 | 5.0 | 5.0 | llm | 2170.4 |
| 你好 | legacy_langgraph_chat | False | 5.0 | 5.0 | 5.0 | 5.0 | llm | 6882.6 |

## 四、局限性说明

1. 意图分类仅 20 条样本，accuracy=100% 不代表线上准确率。
2. 回复质量评分由 LLM-as-Judge 给出，存在主观性；LLM 不可用时降级为关键词规则评分。
3. 评测在本地开发环境执行，延迟数据不代表生产环境。
4. 知识库仅 5 篇文档，FAQ 覆盖范围有限。
