from __future__ import annotations

import time
from typing import Any

from app.agentflow_adapter.config import execution_mode
from app.agentflow_adapter.intent_router import IntentRouter
from app.agentflow_adapter.memory import MemoryManager
from app.agentflow_adapter.monitor import AgentHealthMonitor
from app.agentflow_adapter.orchestrator import AgentOrchestrator
from app.agentflow_adapter.prometheus_metrics import DEFAULT_PROMETHEUS
from app.agentflow_adapter.tool_gateway import DEFAULT_RUNTIME_METRICS

LOW_CONFIDENCE_THRESHOLD = 0.60
SUMMARY_TRIGGER_TURNS = 10  # 每积累 10 轮对话触发一次摘要
_INTENT_ROUTE_PREFIXES = {
    "product_tryon": ("legacy_tryon", "legacy_tryon_not_found", "agent_tryon"),
    "product_intro": ("legacy_product_intro", "agent_product_advisor"),
    "product_advice": ("legacy_langgraph_chat", "agent_product_advisor"),
    "product_catalog": ("legacy_catalog", "agent_catalog"),
    "policy_faq": ("legacy_faq_rag", "agent_policy_rag"),
    "similar_product": ("legacy_similar_product", "legacy_image_match"),
    "general_chat": ("legacy_langgraph_chat", "legacy_empty_message"),
}


def route_consistency(decision, executed_route):
    if not executed_route:
        return None
    return executed_route.startswith(_INTENT_ROUTE_PREFIXES.get(decision.primary_intent, ()))


class RouteMetrics:
    def __init__(self):
        self.total = self.consistent = self.inconsistent = self.unknown = self.fallback = 0

    def record(self, consistency, fallback):
        self.total += 1
        self.consistent += consistency is True
        self.inconsistent += consistency is False
        self.unknown += consistency is None
        self.fallback += bool(fallback)

    def snapshot(self):
        comparable = self.consistent + self.inconsistent
        return {
            "total": self.total,
            "consistent": self.consistent,
            "inconsistent": self.inconsistent,
            "unknown": self.unknown,
            "fallback": self.fallback,
            "consistency_rate": self.consistent / comparable if comparable else None,
        }


class AgentFlowRuntime:
    """Classify, execute and observe a request at the AgentFlow boundary."""

    def __init__(self, router=None, metrics=None, memory=None, monitor=None, orchestrator=None):
        self.monitor = monitor or AgentHealthMonitor()
        self.router = router or IntentRouter.from_environment()
        self.router.monitor = self.monitor
        self.metrics = metrics or RouteMetrics()
        self.memory = memory or MemoryManager.from_environment()
        self.execution_mode = execution_mode()
        self.orchestrator = orchestrator or AgentOrchestrator()

    def classify(self, content, *, has_image=False):
        return self.router.classify(content, has_image=has_image)

    async def handle(
        self,
        content,
        legacy_handler,
        *,
        has_image=False,
        session_id="",
        user_id="guest",
        context: dict[str, Any] | None = None,
    ):
        started = time.perf_counter()
        try:
            decision = await self.router.classify_async(content, has_image=has_image)
        except Exception:
            decision = self.router.classify(content, has_image=has_image)

        # —— 记忆层：对话前回忆 ——
        memory_ctx = {"working": [], "summaries": [], "profiles": [], "degraded": True}
        try:
            if session_id:
                memory_ctx = await self.memory.recall(user_id, session_id, content)
        except Exception:
            pass  # 记忆失败不影响主流程

        owned = False
        execution_error = None
        try:
            if self.execution_mode == "takeover" and context and not has_image:
                result = await self.orchestrator.execute(
                    decision,
                    db=context["db"],
                    session_id=session_id,
                    user_id=user_id,
                    content=content,
                    legacy_fallback=legacy_handler,
                )
                owned = str(result.get("executed_route", "")).startswith("agent_")
            else:
                result = dict(await legacy_handler())
        except Exception as exc:
            execution_error = f"{type(exc).__name__}: {exc}"[:240]
            # orchestrator 执行失败后 session 可能处于 pending rollback 状态，
            # 必须先 rollback，否则 fallback 再用同一 session 会触发 PendingRollbackError
            if context and context.get("db") is not None:
                try:
                    await context["db"].rollback()
                except Exception:
                    pass
            try:
                result = dict(await legacy_handler())
            except Exception as fallback_exc:
                execution_error = (
                    f"fallback also failed: {type(fallback_exc).__name__}: "
                    f"{fallback_exc}"
                )[:240]
                result = {
                    "reply": "亲亲，当前客服服务暂时不可用，请稍后再试或联系人工客服。",
                    "metadata": {"type": "text", "executed_route": "agentflow_safe_fallback"},
                    "executed_route": "agentflow_safe_fallback",
                }

        latency = (time.perf_counter() - started) * 1000
        executed_route = result.get("executed_route") or (result.get("metadata") or {}).get("executed_route")
        consistency = route_consistency(decision, executed_route)
        low_confidence = decision.confidence < LOW_CONFIDENCE_THRESHOLD
        fallback = (not owned) or low_confidence or execution_error is not None

        # Agent 真实接管记成功，fallback 记失败，供 Monitor 动态降权影响下一次路由
        self.monitor.record(decision.primary_agent, success=owned, latency_ms=latency)
        DEFAULT_PROMETHEUS.record_request(latency, owned, fallback)
        DEFAULT_RUNTIME_METRICS.record_route(
            decision.primary_intent,
            consistent=consistency,
            latency_ms=latency,
            fallback=fallback,
        )
        DEFAULT_PROMETHEUS.set_penalty(
            decision.primary_agent, self.monitor.penalty(decision.primary_agent)
        )

        routing = decision.model_dump(mode="json")
        self.metrics.record(consistency, fallback)
        meta = dict(result.get("metadata") or {})
        meta.update(
            routing=routing,
            routing_consistent=consistency,
            routing_fallback=low_confidence,
            execution_mode=self.execution_mode,
            agentflow_executed=owned,
            monitor_penalty=self.monitor.penalty(decision.primary_agent),
        )
        if execution_error:
            meta["agentflow_execution_error"] = execution_error
        fallback_reason = result.get("fallback_reason")
        if not fallback_reason and low_confidence:
            fallback_reason = "low_confidence_intent"
        if fallback_reason:
            meta["fallback_reason"] = fallback_reason
        result.update(
            metadata=meta,
            routing=routing,
            routing_consistent=consistency,
            routing_fallback=low_confidence,
            execution_mode=self.execution_mode,
            agentflow_executed=owned,
            fallback_reason=fallback_reason,
        )
        # 标记业务层错误，供调用日志中间件捕获
        if execution_error:
            result["_business_error"] = execution_error

        # —— 记忆层：对话后存储 ——
        reply_text = result.get("reply", "")
        memory_status = {"recall": memory_ctx.get("degraded", True), "store": None, "summary": None, "profile": None}
        if session_id and reply_text:
            # append_turn 是内存操作，快速完成，保持同步（确保下一轮 recall 能拿到本轮内容）
            try:
                await self.memory.append_turn(session_id, "user", content, user_id=user_id)
                await self.memory.append_turn(session_id, "assistant", reply_text, user_id=user_id)
                memory_status["store"] = "ok"
            except Exception:
                memory_status["store"] = "error"

            working = memory_ctx.get("working", [])

            # 摘要生成 + 画像提取涉及 LLM 调用，改为后台任务，避免阻塞对话响应
            # （LLM 接口抖动时不应让用户等待）
            async def _persist_memory_async():
                try:
                    if len(working) > 0 and len(working) % SUMMARY_TRIGGER_TURNS == 0:
                        summary = await self._generate_summary(session_id, user_id, working)
                        if summary:
                            await self.memory.save_summary(session_id, summary, user_id=user_id)
                except Exception:
                    pass
                try:
                    profile = await self._extract_profile(user_id, working + [
                        {"role": "user", "content": content},
                        {"role": "assistant", "content": reply_text},
                    ])
                    if profile:
                        await self.memory.save_profile(user_id, profile["text"], metadata=profile["meta"])
                except Exception:
                    pass

            import asyncio as _asyncio
            _asyncio.create_task(_persist_memory_async())
            memory_status["summary"] = "pending"
            memory_status["profile"] = "pending"

        result["memory"] = memory_status
        return result

    async def _generate_summary(self, session_id: str, user_id: str, working: list) -> str:
        """用 LLM 对工作记忆做摘要，用于跨会话回忆。"""
        try:
            from app.utils.factory import get_chat_model, has_llm_configured
            if not has_llm_configured():
                return ""
            model = get_chat_model(timeout=15)
            if not model:
                return ""
            turns_text = "\n".join(
                f"{'用户' if t.get('role') == 'user' else '客服'}: {t.get('content', '')[:200]}"
                for t in working[-SUMMARY_TRIGGER_TURNS:]
            )
            prompt = (
                "请用 2-3 句话总结以下客服对话的关键信息（用户需求、偏好、已解决的问题）：\n"
                f"{turns_text}\n\n摘要："
            )
            resp = await model.ainvoke(prompt)
            summary = resp.content if hasattr(resp, "content") else str(resp)
            return summary[:500]
        except Exception:
            return ""

    async def _extract_profile(self, user_id: str, working: list) -> dict:
        """从对话中提取用户画像（姓名/身高/体重/风格偏好/尺码/咨询偏好）。"""
        try:
            from app.utils.factory import get_chat_model, has_llm_configured
            if not has_llm_configured():
                return {}
            model = get_chat_model(timeout=15)
            if not model:
                return {}
            turns_text = "\n".join(
                f"{'用户' if t.get('role') == 'user' else '客服'}: {t.get('content', '')[:200]}"
                for t in working[-SUMMARY_TRIGGER_TURNS:]
            )
            prompt = (
                "从以下客服对话中提取用户画像信息，以 JSON 格式返回：\n"
                '{"name": "用户姓名或昵称或null", "height_cm": "身高cm或null", '
                '"weight_kg": "体重kg或null", "style_preference": "风格偏好或null", '
                '"size": "尺码或null", "topics": "常咨询的话题，逗号分隔或null", '
                '"summary": "一句话用户画像，需包含称呼"}\n\n'
                f"{turns_text}\n\nJSON："
            )
            import json as _json
            resp = await model.ainvoke(prompt)
            raw = resp.content if hasattr(resp, "content") else str(resp)
            # 提取 JSON
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start < 0 or end <= 0:
                return {}
            data = _json.loads(raw[start:end])
            return {"text": data.get("summary", ""), "meta": data}
        except Exception:
            return {}
