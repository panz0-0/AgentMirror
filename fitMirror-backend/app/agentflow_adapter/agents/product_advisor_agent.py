from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.agentflow_adapter.schemas import AgentResponse
from app.agentflow_adapter.tool_gateway import DEFAULT_TOOL_GATEWAY, ToolGateway


_DEFAULT_GATEWAY = DEFAULT_TOOL_GATEWAY


class ProductAdvisorAgent:
    """Agent boundary for product introduction and size advice.

    Domain lookup and reply generation stay in the provider; this agent
    adapts that result to the shared AgentResponse contract.
    """

    name = "ProductAdvisorAgent"

    async def handle(
        self,
        product_provider: Callable[[], Awaitable[dict[str, Any]]],
        gateway: ToolGateway | None = None,
    ) -> AgentResponse:
        result = await _call_provider(gateway or _DEFAULT_GATEWAY, "product.advisor", product_provider)
        metadata = dict(result.get("metadata") or {})
        metadata.setdefault("type", "product_intro")
        return AgentResponse(
            reply=str(result.get("reply") or ""),
            message_type=str(metadata.get("type") or "product_intro"),
            artifacts=[metadata],
            routing={
                "primary_intent": str(result.get("intent") or "product_intro"),
                "intent_group": "shopping_assistance",
                "primary_agent": self.name,
                "supporting_agents": [],
                "confidence": 1.0,
                "need_rag": False,
                "need_human": False,
                "entities": {"sku_id": metadata.get("sku_id")} if metadata.get("sku_id") else {},
                "evidence": {"source": "product_advisor_provider"},
            },
        )


async def _call_provider(gateway: ToolGateway | None, name: str, provider):
    if gateway is None:
        return await provider()
    result = await gateway.call(name, provider)
    if not result.success:
        raise RuntimeError(result.error or "tool_failed")
    return result.data
