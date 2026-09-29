from __future__ import annotations

from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agentflow_adapter.agents import (
    CatalogAgent,
    PolicyRAGAgent,
    ProductAdvisorAgent,
    TryOnAgent,
)
from app.agentflow_adapter.schemas import AgentResponse, IntentDecision
from app.agentflow_adapter.tool_gateway import DEFAULT_TOOL_GATEWAY
from app.models.chat_history import ChatSession
from app.services import chat_service
from app.services.catalog_service import build_catalog


class AgentOrchestrator:
    """Own the text-chat execution boundary while reusing domain providers.

    The orchestrator selects an Agent from the already classified intent. The
    existing chat service is deliberately used only through narrow domain
    providers or as an explicit fallback; it is never called recursively as
    the main dispatcher.
    """

    def __init__(self, gateway=None):
        self.gateway = gateway or DEFAULT_TOOL_GATEWAY
        self.catalog_agent = CatalogAgent()
        self.policy_agent = PolicyRAGAgent()
        self.product_agent = ProductAdvisorAgent()
        self.tryon_agent = TryOnAgent()

    async def execute(
        self,
        decision: IntentDecision,
        *,
        db: AsyncSession,
        session_id: str,
        user_id: str,
        content: str,
        legacy_fallback: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        intent = decision.primary_intent
        if intent == "product_catalog":
            response = await self.catalog_agent.handle(lambda: build_catalog(db), self.gateway)
            return await self._persist_agent_response(db, session_id, content, response, "agent_catalog")

        if intent == "policy_faq":
            from app.rag.rag_service import RagService

            response = await self.policy_agent.handle(
                lambda: RagService().aquery(content), self.gateway
            )
            if response is not None:
                return await self._persist_agent_response(
                    db, session_id, content, response, "agent_policy_rag"
                )
            return await self._fallback(legacy_fallback, "rag_no_result")

        if intent in {"product_intro", "product_advice"}:
            sku = await chat_service.find_sku_by_text(db, content)
            if sku is None:
                # 文本未命中具体商品名时，从对话上下文兜底（如"这件裙子多少钱"）
                sku = await chat_service.find_sku_from_context(db, session_id)
            if sku is None:
                return await self._fallback(legacy_fallback, "sku_not_found")
            profile = await chat_service.get_user_profile(db, user_id)

            async def provider() -> dict[str, Any]:
                body = chat_service.resolve_user_body(profile, sku)
                return {
                    "reply": chat_service.build_product_intro_reply(sku, body),
                    "metadata": chat_service.build_product_intro_meta(sku, body),
                    "intent": intent,
                }

            response = await self.product_agent.handle(provider, self.gateway)
            return await self._persist_agent_response(
                db, session_id, content, response, "agent_product_advisor"
            )

        if intent == "product_tryon":
            sku = await chat_service.find_sku_by_text(db, content)
            if sku is None:
                sku = await chat_service.find_sku_from_context(db, session_id)
            if sku is None:
                return await self._fallback(legacy_fallback, "sku_not_found")

            # Keep the existing message persistence semantics: save the user
            # turn before the provider writes the assistant result.
            await chat_service.save_message(db, session_id, "user", content)

            async def provider() -> dict[str, Any]:
                return await chat_service.start_tryon_for_sku(
                    db, session_id, user_id, sku.id, skip_user_save=True
                )

            response = await self.tryon_agent.handle(provider, self.gateway)
            result = self._response_dict(response, "agent_tryon")
            result["metadata"]["agentflow_owned"] = True
            return result

        return await self._fallback(legacy_fallback, "intent_not_owned")

    async def _persist_agent_response(
        self,
        db: AsyncSession,
        session_id: str,
        content: str,
        response: AgentResponse,
        route: str,
    ) -> dict[str, Any]:
        await chat_service.save_message(db, session_id, "user", content)
        result = self._response_dict(response, route)
        await chat_service.save_message(
            db, session_id, "assistant", result["reply"], metadata=result["metadata"]
        )
        return result

    async def _fallback(self, legacy_fallback, reason: str) -> dict[str, Any]:
        result = dict(await legacy_fallback())
        metadata = dict(result.get("metadata") or {})
        metadata["agentflow_fallback_reason"] = reason
        result["metadata"] = metadata
        result["fallback_reason"] = reason
        return result

    @staticmethod
    def _response_dict(response: AgentResponse, route: str) -> dict[str, Any]:
        result = response.model_dump(mode="json")
        result["metadata"] = dict(result.get("metadata") or {})
        result["metadata"]["executed_route"] = route
        result["metadata"]["agent"] = result.get("routing", {}).get("primary_agent")
        result["executed_route"] = route
        result["tool_calls"] = result.get("tool_calls", [])
        return result
