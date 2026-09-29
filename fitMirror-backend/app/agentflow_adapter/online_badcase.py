"""线上真实用户 Badcase 异步采集。

在 /api/chat/message 返回回复后，后台异步调用 LLM Judge 对回复打分，
低分（任一维度 < 4）自动写入 badcase_feedback.json，标记 source=online。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

from app.utils.path_tool import STORAGE_ROOT

BADCASE_FILE = STORAGE_ROOT / "evaluation" / "badcase_feedback.json"

# 低于该分数视为 badcase
BADCASE_THRESHOLD = 4.0
# LLM Judge 超时（秒），避免后台任务拖垮服务
JUDGE_TIMEOUT = 12


def _case_id(text: str) -> str:
    return f"online-{hashlib.md5(text.encode('utf-8')).hexdigest()[:12]}"


def _load_feedback() -> dict:
    try:
        return json.loads(BADCASE_FILE.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_feedback(data: dict) -> None:
    BADCASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BADCASE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def _llm_judge_online(query: str, reply: str, get_model) -> dict | None:
    """线上轻量 LLM 评分，无 expected_answer 时用通用客服标准。"""
    prompt = (
        "你是电商客服回复质量评审员。请对以下客服回复按四个维度打分（1-5 整数）：\n"
        "relevance=是否回答了用户问题、correctness=信息是否正确、"
        "completeness=是否完整、usefulness=对用户是否有帮助。\n"
        "若有维度低于 4 分，给出 failure_reason（一句话原因）。\n"
        "只返回 JSON {relevance, correctness, completeness, usefulness, failure_reason}，不要解释。\n"
        f"用户问题: {query}\n客服回复: {reply[:600]}\n"
    )
    try:
        model = get_model()
        out = await asyncio.wait_for(asyncio.to_thread(model.invoke, prompt), timeout=JUDGE_TIMEOUT)
        raw = getattr(out, "content", out)
        text = raw if isinstance(raw, str) else str(raw)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text[start:end + 1])
            result = {k: float(obj.get(k, 3)) for k in ("relevance", "correctness", "completeness", "usefulness")}
            result["failure_reason"] = obj.get("failure_reason", "")[:120]
            return result
    except Exception:
        pass
    return None


async def collect_online_badcase(
    query: str,
    reply: str,
    route: str,
    agentflow_executed: bool,
    user_id: str,
    session_id: str,
    get_model,
) -> None:
    """异步采集线上 badcase。低分回复自动入库，标记 source=online。

    若 LLM 不可用或超时，静默跳过（不影响主流程）。
    """
    if not query or not reply:
        return

    scores = await _llm_judge_online(query, reply, get_model)
    if not scores:
        return

    min_score = min(scores["relevance"], scores["correctness"], scores["completeness"], scores["usefulness"])
    if min_score >= BADCASE_THRESHOLD:
        return

    # 低分 → 写入 badcase_feedback.json
    case_id = _case_id(query)
    feedback = _load_feedback()
    existing = feedback.get(case_id, {})

    # 若已存在且状态非 open，不覆盖（运营可能已处理）
    if existing.get("status") in ("resolved", "ignored"):
        return

    failure_reason = scores.get("failure_reason", "")
    if not failure_reason:
        dim_map = {"relevance": "相关性", "correctness": "正确性", "completeness": "完整性", "usefulness": "有用性"}
        lowest = min(dim_map, key=lambda k: scores[k])
        failure_reason = f"{dim_map[lowest]}不足（{lowest}={scores[lowest]}）"

    feedback[case_id] = {
        **existing,
        "source": "online",
        "case_type": "quality",
        "query": query,
        "reply": reply[:300],
        "expected": route,
        "actual": route,
        "route_expected": route,
        "route_actual": route,
        "scores": {
            "relevance": scores["relevance"],
            "correctness": scores["correctness"],
            "completeness": scores["completeness"],
            "usefulness": scores["usefulness"],
        },
        "failure_reason": failure_reason,
        "agentflow": agentflow_executed,
        "user_id": user_id,
        "session_id": session_id,
        "status": existing.get("status", "open"),
        "feedback_note": existing.get("feedback_note", ""),
        "reclassified_intent": existing.get("reclassified_intent"),
        "expected_reply": existing.get("expected_reply", ""),
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_feedback(feedback)
