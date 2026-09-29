from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.agentflow_adapter.schemas import AgentResponse
from app.agentflow_adapter.tool_gateway import DEFAULT_TOOL_GATEWAY, ToolGateway


_DEFAULT_GATEWAY = DEFAULT_TOOL_GATEWAY


class TryOnAgent:
    """Agent boundary for virtual try-on requests.

    The provider owns SKU lookup, profile loading, gallery retrieval and
    persistence. The agent only adapts the domain result to the common
    AgentResponse contract.
    """

    name = "TryOnAgent"

    async def handle(
        self,
        tryon_provider: Callable[[], Awaitable[dict[str, Any]]],
        gateway: ToolGateway | None = None,
    ) -> AgentResponse:
        result = await _call_provider(gateway or _DEFAULT_GATEWAY, "tryon.generate", tryon_provider)
        metadata = dict(result.get("metadata") or {})
        route = result.get("executed_route") or "agent_tryon"
        return AgentResponse(
            reply=str(result.get("reply") or ""),
            message_type=str(metadata.get("type") or "tryon_result"),
            artifacts=[metadata] if metadata else [],
            routing={
                "primary_intent": "product_tryon",
                "intent_group": "shopping_assistance",
                "primary_agent": self.name,
                "supporting_agents": [],
                "confidence": 1.0,
                "need_rag": False,
                "need_human": False,
                "entities": {"sku_id": metadata.get("sku_id")} if metadata.get("sku_id") else {},
                "evidence": {"source": "tryon_provider", "provider_route": route},
            },
        )


async def _call_provider(gateway: ToolGateway | None, name: str, provider):
    if gateway is None:
        return await provider()
    result = await gateway.call(name, provider)
    if not result.success:
        raise RuntimeError(result.error or "tool_failed")
    return result.data
