"""评测与 Badcase 回流闭环 API。

领域模型（独立枚举，不复用 type/status）：
- IntentCase：意图分类样本，status = passed / failed
- QualityCase：回复质量样本，judge_source = llm / rule
- Badcase：失败样本回流，case_type = intent / quality，status = open / resolved / ignored
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agentflow_adapter.feedback_engine import FeedbackEngine
from app.agentflow_adapter.intent_router import IntentRouter
from app.agentflow_adapter.runtime import route_consistency, _INTENT_ROUTE_PREFIXES
from app.agentflow_adapter.schemas import IntentDecision
from app.core.success_response import success_response
from app.utils.path_tool import STORAGE_ROOT

EVAL_DIR = STORAGE_ROOT / "evaluation"
EVAL_CASES = Path(__file__).resolve().parents[2] / "tests" / "eval_cases.json"
CACHE_FILE = EVAL_DIR / "eval_cache.json"
BADCASE_FILE = EVAL_DIR / "badcase_feedback.json"

evaluation_router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])
_router = IntentRouter()
_feedback = FeedbackEngine(router=_router)


# ---------- persistence helpers ----------

def _ensure_dir() -> None:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    _ensure_dir()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _case_id(case_type: str, text: str) -> str:
    return f"{case_type}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:12]}"


# ---------- intent evaluation (live, fast) ----------

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


def evaluate_intents() -> dict:
    cases = _read_json(EVAL_CASES, {}).get("intent_cases", [])
    rows, routes, results = [], [], []
    for case in cases:
        d = _router.classify(case["text"], has_image=case.get("has_image", False))
        exp = case["expected_intent"]
        correct = d.primary_intent == exp
        rows.append((exp, d.primary_intent))
        route_match = None
        if case.get("expected_route"):
            ed = IntentDecision(primary_intent=exp, intent_group="x", primary_agent="x", confidence=1.0)
            route_match = route_consistency(ed, case["expected_route"]) is True
            routes.append(route_match)
        results.append({
            "id": _case_id("intent", case["text"]),
            "text": case["text"],
            "expected_intent": exp,
            "expected_route": case.get("expected_route"),
            "predicted_intent": d.primary_intent,
            "predicted_agent": d.primary_agent,
            "predicted_route": _INTENT_ROUTE_PREFIXES.get(d.primary_intent, ("",))[0],
            "correct": correct,
            "route_match": route_match,
            "confidence": round(d.confidence, 3),
        })
    correct = sum(r["correct"] for r in results)
    return {
        "total": len(results),
        "correct": correct,
        "accuracy": correct / len(results) if results else 0.0,
        "macro_f1": _macro_f1(rows),
        "route_consistency": sum(routes) / len(routes) if routes else None,
        "cases": results,
    }


async def _llm_intent_judge(text: str, intent_list: list[str], has_llm, get_model):
    """LLM-as-Judge 意图分类，返回 {intent, confidence, reason} 或 None。"""
    if not has_llm():
        return None
    prompt = (
        "你是客服意图分类器。请将以下用户问题分类到给定意图集合中。\n"
        f"意图集合: {', '.join(intent_list)}\n"
        f"用户问题: {text}\n"
        '只返回 JSON {"intent": "...", "confidence": 0.0-1.0, "reason": "分类理由"}，不要解释。'
    )
    try:
        model = get_model()
        out = await asyncio.wait_for(asyncio.to_thread(model.invoke, prompt), timeout=10)
        raw = getattr(out, "content", out)
        text_out = raw if isinstance(raw, str) else str(raw)
        start, end = text_out.find("{"), text_out.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text_out[start:end + 1])
            return {
                "intent": obj.get("intent", ""),
                "confidence": float(obj.get("confidence", 0.5)),
                "reason": obj.get("reason", "")[:100],
            }
    except Exception:
        pass
    return None


# ---------- quality evaluation (cached, slow) ----------

async def _run_quality_evaluation() -> list[dict]:
    """调用真实客服接口获取回复，LLM-as-Judge 评分；LLM 不可用降级规则评分。"""
    import httpx

    from app.utils.factory import get_chat_model, has_llm_configured

    cases = _read_json(EVAL_CASES, {}).get("quality_cases", [])
    results = []
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=60) as client:
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
                data = {"reply": "", "executed_route": "error", "agentflow_executed": False}
            latency_ms = (time.perf_counter() - started) * 1000
            reply = data.get("reply", "")
            scores = await _llm_judge(case["query"], reply, case["expected_answer"], has_llm_configured, get_chat_model)
            judge_source = "llm" if scores else "rule"
            if not scores:
                scores = _rule_judge(reply, case.get("keywords", []))
            results.append({
                "id": _case_id("quality", case["query"]),
                "query": case["query"],
                "expected_route": case.get("expected_route"),
                "expected_answer": case.get("expected_answer"),
                "route": data.get("executed_route", ""),
                "agentflow": data.get("agentflow_executed", False),
                "reply": reply[:300],
                "relevance": scores["relevance"],
                "correctness": scores["correctness"],
                "completeness": scores["completeness"],
                "usefulness": scores["usefulness"],
                "failure_reason": scores.get("failure_reason", ""),
                "judge_source": judge_source,
                "latency_ms": round(latency_ms, 1),
            })
            # 兜底：低分但 LLM 未返回 failure_reason 时，根据最低分维度自动生成
            min_score = min(scores["relevance"], scores["correctness"], scores["completeness"], scores["usefulness"])
            if min_score < 4 and not results[-1]["failure_reason"]:
                dim_map = {"relevance": "相关性", "correctness": "正确性", "completeness": "完整性", "usefulness": "有用性"}
                lowest = min(dim_map, key=lambda k: scores[k])
                results[-1]["failure_reason"] = f"{dim_map[lowest]}不足（{lowest}={scores[lowest]}）"
    return results


async def _llm_judge(query, reply, expected, has_llm, get_model):
    if not has_llm():
        return None
    prompt = (
        "你是客服回复质量评审员。请对以下回复按四个维度打分（1-5 整数），"
        "若有维度低于 4 分，给出 failure_reason（一句话原因）。"
        "只返回 JSON {relevance, correctness, completeness, usefulness, failure_reason}，不要解释。\n"
        f"用户问题: {query}\n参考答案要点: {expected}\n实际回复: {reply[:600]}\n"
    )
    try:
        model = get_model()
        out = await asyncio.wait_for(asyncio.to_thread(model.invoke, prompt), timeout=15)
        raw = getattr(out, "content", out)
        text = raw if isinstance(raw, str) else str(raw)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text[start:end + 1])
            result = {k: float(obj.get(k, 3)) for k in ("relevance", "correctness", "completeness", "usefulness")}
            result["failure_reason"] = obj.get("failure_reason", "")[:100]
            return result
    except Exception:
        pass
    return None


def _rule_judge(reply, keywords):
    if not keywords:
        return {"relevance": 3.0, "correctness": 3.0, "completeness": 3.0, "usefulness": 3.0}
    hits = sum(1 for k in keywords if k in reply)
    ratio = hits / len(keywords)
    base = 2.0 + ratio * 3.0
    return {
        "relevance": round(base, 1), "correctness": round(base, 1),
        "completeness": round(base - 0.5, 1) if ratio < 1 else round(base, 1),
        "usefulness": round(base, 1),
    }


# ---------- badcase feedback ----------

class BadcaseFeedback(BaseModel):
    status: str = Field(..., description="open / resolved / ignored")
    feedback_note: str = Field("", description="反馈备注")
    reclassified_intent: str | None = Field(None, description="重分类意图（仅 intent 类型）")
    expected_reply: str = Field("", description="期望回复（仅 quality 类型）")


def _load_badcase_feedback() -> dict:
    return _read_json(BADCASE_FILE, {})


def _save_badcase_feedback(data: dict) -> None:
    _write_json(BADCASE_FILE, data)


def _build_badcases(intent_result: dict, quality_cases: list[dict]) -> list[dict]:
    """合并意图失败 + 低质量回复 + 线上采集为 badcase 列表，附带反馈状态和来源。"""
    feedback = _load_badcase_feedback()
    badcases = []
    # 意图失败（离线）
    for c in intent_result["cases"]:
        if not c["correct"]:
            fb = feedback.get(c["id"], {})
            badcases.append({
                "id": c["id"],
                "source": "offline",
                "case_type": "intent",
                "query": c["text"],
                "expected": c["expected_intent"],
                "actual": c["predicted_intent"],
                "route_expected": c["expected_route"],
                "route_actual": c["predicted_route"],
                "scores": None,
                "status": fb.get("status", "open"),
                "feedback_note": fb.get("feedback_note", ""),
                "reclassified_intent": fb.get("reclassified_intent"),
                "expected_reply": fb.get("expected_reply", ""),
                "updated_at": fb.get("updated_at"),
            })
    # 低质量回复（任一维度 < 4 视为 badcase，离线）
    for c in quality_cases:
        min_score = min(c["relevance"], c["correctness"], c["completeness"], c["usefulness"])
        if min_score < 4 or not c["agentflow"]:
            fb = feedback.get(c["id"], {})
            badcases.append({
                "id": c["id"],
                "source": "offline",
                "case_type": "quality",
                "query": c["query"],
                "expected": c["expected_route"],
                "actual": c["route"],
                "route_expected": c["expected_route"],
                "route_actual": c["route"],
                "scores": {
                    "relevance": c["relevance"], "correctness": c["correctness"],
                    "completeness": c["completeness"], "usefulness": c["usefulness"],
                },
                "reply": c.get("reply", ""),
                "judge_source": c.get("judge_source"),
                "failure_reason": c.get("failure_reason", ""),
                "status": fb.get("status", "open"),
                "feedback_note": fb.get("feedback_note", ""),
                "reclassified_intent": fb.get("reclassified_intent"),
                "expected_reply": fb.get("expected_reply", ""),
                "updated_at": fb.get("updated_at"),
            })
    # 线上采集的 badcase（source=online，直接来自 feedback 文件）
    for case_id, fb in feedback.items():
        if fb.get("source") == "online":
            badcases.append({
                "id": case_id,
                "source": "online",
                "case_type": fb.get("case_type", "quality"),
                "query": fb.get("query", ""),
                "expected": fb.get("expected", ""),
                "actual": fb.get("actual", ""),
                "route_expected": fb.get("route_expected", ""),
                "route_actual": fb.get("route_actual", ""),
                "scores": fb.get("scores"),
                "reply": fb.get("reply", ""),
                "judge_source": "llm",
                "failure_reason": fb.get("failure_reason", ""),
                "agentflow": fb.get("agentflow"),
                "user_id": fb.get("user_id"),
                "session_id": fb.get("session_id"),
                "collected_at": fb.get("collected_at"),
                "status": fb.get("status", "open"),
                "feedback_note": fb.get("feedback_note", ""),
                "reclassified_intent": fb.get("reclassified_intent"),
                "expected_reply": fb.get("expected_reply", ""),
                "updated_at": fb.get("updated_at"),
            })
    return badcases


# ---------- endpoints ----------

@evaluation_router.get("/summary", summary="评测总览指标")
async def evaluation_summary():
    intent_result = evaluate_intents()
    cache = _read_json(CACHE_FILE, {})
    quality_cases = cache.get("quality_cases", [])
    badcases = _build_badcases(intent_result, quality_cases)
    resolved = sum(1 for b in badcases if b["status"] == "resolved")
    ignored = sum(1 for b in badcases if b["status"] == "ignored")
    open_count = sum(1 for b in badcases if b["status"] == "open")

    quality_stats = {}
    if quality_cases:
        for dim in ("relevance", "correctness", "completeness", "usefulness"):
            quality_stats[f"{dim}_avg"] = round(statistics.mean(c[dim] for c in quality_cases), 2)
        lats = sorted(c["latency_ms"] for c in quality_cases)
        quality_stats["p95_latency_ms"] = round(lats[int(len(lats) * 0.95)], 1) if lats else 0
        quality_stats["fallback_rate"] = round(sum(1 for c in quality_cases if not c["agentflow"]) / len(quality_cases), 2)

    return success_response(data={
        "intent": {
            "total": intent_result["total"],
            "correct": intent_result["correct"],
            "accuracy": round(intent_result["accuracy"], 4),
            "macro_f1": round(intent_result["macro_f1"], 4),
            "route_consistency": round(intent_result["route_consistency"], 4) if intent_result["route_consistency"] else None,
        },
        "quality": quality_stats,
        "badcase": {
            "total": len(badcases),
            "open": open_count,
            "resolved": resolved,
            "ignored": ignored,
            "resolve_rate": round(resolved / len(badcases), 2) if badcases else 0,
            "online_count": sum(1 for b in badcases if b.get("source") == "online"),
            "offline_count": sum(1 for b in badcases if b.get("source") == "offline"),
        },
        "last_run_at": cache.get("run_at"),
    })


@evaluation_router.get("/intent-cases", summary="意图分类样本明细")
async def intent_cases():
    result = evaluate_intents()
    return success_response(data=result["cases"])


@evaluation_router.get("/quality-cases", summary="回复质量样本明细")
async def quality_cases():
    cache = _read_json(CACHE_FILE, {})
    return success_response(data=cache.get("quality_cases", []))


@evaluation_router.get("/badcases", summary="Badcase 列表（失败样本回流）")
async def list_badcases(status: str | None = None, source: str | None = None):
    intent_result = evaluate_intents()
    cache = _read_json(CACHE_FILE, {})
    quality_cases = cache.get("quality_cases", [])
    badcases = _build_badcases(intent_result, quality_cases)
    if status:
        badcases = [b for b in badcases if b["status"] == status]
    if source:
        badcases = [b for b in badcases if b.get("source") == source]
    return success_response(data=badcases)


@evaluation_router.post("/badcases/{badcase_id}/feedback", summary="提交 Badcase 反馈")
async def submit_badcase_feedback(badcase_id: str, body: BadcaseFeedback):
    if body.status not in ("open", "resolved", "ignored"):
        raise HTTPException(status_code=400, detail="status 必须是 open / resolved / ignored")
    feedback = _load_badcase_feedback()
    feedback[badcase_id] = {
        "status": body.status,
        "feedback_note": body.feedback_note,
        "reclassified_intent": body.reclassified_intent,
        "expected_reply": body.expected_reply,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_badcase_feedback(feedback)
    return success_response(data=feedback[badcase_id])


@evaluation_router.post("/run", summary="执行全量评测并缓存结果")
async def run_evaluation():
    intent_result = evaluate_intents()
    quality_cases = await _run_quality_evaluation()
    cache = {
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "intent": {
            "total": intent_result["total"],
            "correct": intent_result["correct"],
            "accuracy": intent_result["accuracy"],
            "macro_f1": intent_result["macro_f1"],
            "route_consistency": intent_result["route_consistency"],
        },
        "quality_cases": quality_cases,
    }
    _write_json(CACHE_FILE, cache)
    return success_response(data={"run_at": cache["run_at"], "intent": cache["intent"], "quality_count": len(quality_cases)})


@evaluation_router.post("/badcases/{badcase_id}/apply", summary="自动回流 Badcase 到意图规则/知识库/Skills")
async def apply_badcase_feedback(badcase_id: str):
    """根据 Badcase 类型自动选择回流路径，通过回归校验后才保留改动。"""
    from app.utils.factory import get_chat_model, has_llm_configured

    # 找到对应 badcase
    intent_result = evaluate_intents()
    cache = _read_json(CACHE_FILE, {})
    quality_cases = cache.get("quality_cases", [])
    badcases = _build_badcases(intent_result, quality_cases)
    target = next((b for b in badcases if b["id"] == badcase_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Badcase 不存在")

    result = await _feedback.apply_all(target, has_llm=has_llm_configured, get_model=get_chat_model)

    # 若改动成功，更新 badcase 状态为 resolved
    if result.get("applied"):
        feedback = _load_badcase_feedback()
        existing = feedback.get(badcase_id, {})
        note = existing.get("feedback_note", "")
        # 避免重复追加标记
        if "自动回流已应用" not in note:
            note = (note + " [自动回流已应用]").strip()
        applied_paths = [k for k, v in result.get("paths", {}).items() if v.get("applied")]
        feedback[badcase_id] = {
            **existing,
            "status": "resolved",
            "feedback_note": note,
            "applied_paths": applied_paths,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_badcase_feedback(feedback)

    return success_response(data=result)


@evaluation_router.get("/dynamic-rules", summary="自动回流生成的动态意图规则列表")
async def list_dynamic_rules():
    return success_response(data=_router.list_dynamic_rules())


@evaluation_router.delete("/dynamic-rules/{rule_id}", summary="回滚动态意图规则")
async def remove_dynamic_rule(rule_id: str):
    ok = _router.remove_dynamic_rule(rule_id)
    return success_response(data={"removed": ok, "rule_id": rule_id})
