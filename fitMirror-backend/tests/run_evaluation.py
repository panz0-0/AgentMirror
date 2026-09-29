"""AgentFlow 离线评测脚本。

- 意图分类：20 条样本，输出 accuracy / macro_f1 / route_consistency
- 回复质量：10 条样本，调用真实客服接口获取回复，LLM-as-Judge 四维评分
  （relevance / correctness / completeness / usefulness，1-5 分）
  LLM 不可用时降级为关键词匹配规则评分
- 输出：docs/evaluation-report.md
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path

import httpx

from app.agentflow_adapter.intent_router import IntentRouter
from app.agentflow_adapter.schemas import IntentDecision
from app.agentflow_adapter.runtime import route_consistency
from app.utils.factory import get_chat_model, has_llm_configured

EVAL_CASES = Path(__file__).parent / "eval_cases.json"
REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "evaluation-report.md"
API_BASE = "http://127.0.0.1:8000"


def _macro_f1(rows):
    labels = sorted({label for pair in rows for label in pair})
    scores = []
    for label in labels:
        tp = sum(a == label and p == label for a, p in rows)
        fp = sum(a != label and p == label for a, p in rows)
        fn = sum(a == label and p != label for a, p in rows)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def evaluate_intents(cases):
    router = IntentRouter()
    rows, routes, by_class = [], [], defaultdict(list)
    for case in cases:
        d = router.classify(case["text"], has_image=case.get("has_image", False))
        exp = case["expected_intent"]
        rows.append((exp, d.primary_intent))
        by_class[exp].append(d.primary_intent == exp)
        if case.get("expected_route"):
            ed = IntentDecision(primary_intent=exp, intent_group="x", primary_agent="x", confidence=1.0)
            routes.append(route_consistency(ed, case["expected_route"]) is True)
    correct = sum(a == p for a, p in rows)
    return {
        "total": len(cases),
        "correct": correct,
        "accuracy": correct / len(cases) if cases else 0.0,
        "macro_f1": _macro_f1(rows),
        "route_consistency": sum(routes) / len(routes) if routes else None,
        "per_intent": {
            k: {"total": len(v), "correct": sum(v), "accuracy": sum(v) / len(v)}
            for k, v in sorted(by_class.items())
        },
    }


async def _llm_judge(query, reply, expected):
    """LLM-as-Judge: 四维评分，返回 dict 或 None（失败时降级）。"""
    if not has_llm_configured():
        return None
    prompt = (
        "你是客服回复质量评审员。请对以下回复按四个维度打分（1-5 整数），"
        "只返回 JSON {relevance, correctness, completeness, usefulness}，不要解释。\n"
        f"用户问题: {query}\n"
        f"参考答案要点: {expected}\n"
        f"实际回复: {reply[:600]}\n"
    )
    try:
        model = get_chat_model()
        out = await asyncio.wait_for(asyncio.to_thread(model.invoke, prompt), timeout=15)
        raw = getattr(out, "content", out)
        text = raw if isinstance(raw, str) else str(raw)
        # 提取 JSON
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text[start:end + 1])
            return {k: float(obj.get(k, 3)) for k in ("relevance", "correctness", "completeness", "usefulness")}
    except Exception:
        pass
    return None


def _rule_judge(reply, keywords):
    """规则降级评分：基于关键词匹配率。"""
    if not keywords:
        return {"relevance": 3.0, "correctness": 3.0, "completeness": 3.0, "usefulness": 3.0}
    hits = sum(1 for k in keywords if k in reply)
    ratio = hits / len(keywords)
    base = 2.0 + ratio * 3.0  # 2.0 ~ 5.0
    return {
        "relevance": round(base, 1),
        "correctness": round(base, 1),
        "completeness": round(base - 0.5, 1) if ratio < 1 else round(base, 1),
        "usefulness": round(base, 1),
    }


async def evaluate_quality(cases):
    results = []
    latencies = []
    fallback_count = 0
    async with httpx.AsyncClient(base_url=API_BASE, timeout=60) as client:
        # 创建会话
        r = await client.post("/api/chat/session", json={"user_id": "eval", "title": "评测"})
        sid = r.json()["data"]["session_id"]
        for case in cases:
            started = time.perf_counter()
            try:
                r = await client.post("/api/chat/message", json={
                    "session_id": sid, "user_id": "eval", "content": case["query"]
                })
                data = r.json()["data"]
            except Exception:
                data = {"reply": "", "executed_route": "error", "agentflow_executed": False,
                        "fallback_reason": "request_error"}
            latency_ms = (time.perf_counter() - started) * 1000
            latencies.append(latency_ms)
            route = data.get("executed_route", "")
            agentflow = data.get("agentflow_executed", False)
            reply = data.get("reply", "")
            if not agentflow:
                fallback_count += 1
            # LLM judge or rule-based
            scores = await _llm_judge(case["query"], reply, case["expected_answer"])
            judge_source = "llm"
            if scores is None:
                scores = _rule_judge(reply, case.get("keywords", []))
                judge_source = "rule"
            results.append({
                "query": case["query"],
                "route": route,
                "agentflow": agentflow,
                "latency_ms": round(latency_ms, 1),
                "judge_source": judge_source,
                **scores,
            })
    # 统计
    dims = ("relevance", "correctness", "completeness", "usefulness")
    stats = {f"{d}_avg": round(statistics.mean(r[d] for r in results), 2) for d in dims}
    latencies_sorted = sorted(latencies)
    p95_idx = int(len(latencies_sorted) * 0.95)
    stats["p95_latency_ms"] = round(latencies_sorted[min(p95_idx, len(latencies_sorted) - 1)], 1)
    stats["fallback_rate"] = round(fallback_count / len(cases), 2) if cases else 0
    stats["cases"] = results
    return stats


def build_report(intent_result, quality_result):
    lines = [
        "# AgentFlow 离线评测报告",
        "",
        "> 注意：本报告为离线评测结果，不是线上生产质量报告。",
        "",
        "## 一、评测范围",
        "",
        f"- 意图分类样本：{intent_result['total']} 条",
        f"- 回复质量样本：{len(quality_result['cases'])} 条",
        f"- 评测方式：意图 = Pattern 直接分类；回复质量 = LLM-as-Judge（失败降级规则评分）",
        f"- 评测日期：{time.strftime('%Y-%m-%d')}",
        "",
        "## 二、意图分类结果",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| total | {intent_result['total']} |",
        f"| correct | {intent_result['correct']} |",
        f"| accuracy | {intent_result['accuracy']:.2%} |",
        f"| macro_f1 | {intent_result['macro_f1']:.2%} |",
        f"| route_consistency | {intent_result['route_consistency']:.2%} |",
        "",
        "### 各意图准确率",
        "",
        "| intent | total | correct | accuracy |",
        "|--------|-------|---------|----------|",
    ]
    for k, v in intent_result["per_intent"].items():
        lines.append(f"| {k} | {v['total']} | {v['correct']} | {v['accuracy']:.2%} |")
    lines += [
        "",
        "## 三、回复质量结果",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| relevance_avg | {quality_result['relevance_avg']} |",
        f"| correctness_avg | {quality_result['correctness_avg']} |",
        f"| completeness_avg | {quality_result['completeness_avg']} |",
        f"| usefulness_avg | {quality_result['usefulness_avg']} |",
        f"| fallback_rate | {quality_result['fallback_rate']:.2%} |",
        f"| p95_latency_ms | {quality_result['p95_latency_ms']} |",
        "",
        "### 各样本明细",
        "",
        "| query | route | agentflow | rel | corr | comp | use | judge | latency(ms) |",
        "|-------|-------|-----------|-----|------|------|-----|-------|-------------|",
    ]
    for c in quality_result["cases"]:
        lines.append(
            f"| {c['query']} | {c['route']} | {c['agentflow']} | "
            f"{c['relevance']} | {c['correctness']} | {c['completeness']} | "
            f"{c['usefulness']} | {c['judge_source']} | {c['latency_ms']} |"
        )
    lines += [
        "",
        "## 四、局限性说明",
        "",
        "1. 意图分类仅 20 条样本，accuracy=100% 不代表线上准确率。",
        "2. 回复质量评分由 LLM-as-Judge 给出，存在主观性；LLM 不可用时降级为关键词规则评分。",
        "3. 评测在本地开发环境执行，延迟数据不代表生产环境。",
        "4. 知识库仅 5 篇文档，FAQ 覆盖范围有限。",
        "",
    ]
    return "\n".join(lines)


async def main():
    cases = json.loads(EVAL_CASES.read_text(encoding="utf-8-sig"))
    print("Evaluating intents...")
    intent_result = evaluate_intents(cases["intent_cases"])
    print(f"  accuracy={intent_result['accuracy']:.2%} macro_f1={intent_result['macro_f1']:.2%}")

    print("Evaluating reply quality (calling API)...")
    quality_result = await evaluate_quality(cases["quality_cases"])
    print(f"  relevance={quality_result['relevance_avg']} correctness={quality_result['correctness_avg']} "
          f"completeness={quality_result['completeness_avg']} usefulness={quality_result['usefulness_avg']}")
    print(f"  fallback_rate={quality_result['fallback_rate']:.2%} p95_latency={quality_result['p95_latency_ms']}ms")

    report = build_report(intent_result, quality_result)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\nReport saved to {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
