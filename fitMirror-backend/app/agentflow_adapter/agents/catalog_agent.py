from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.agentflow_adapter.schemas import AgentResponse
from app.agentflow_adapter.tool_gateway import DEFAULT_TOOL_GATEWAY, ToolGateway


_DEFAULT_GATEWAY = DEFAULT_TOOL_GATEWAY


class CatalogAgent:
    """First extracted Agent boundary for product-catalog questions.

    The agent owns response composition, while ``catalog_provider`` remains a
    tool boundary. This keeps database access out of orchestration code and
    makes the implementation keeps reliability policies centralized in ToolGateway.
    """

    name = "CatalogAgent"

    async def handle(
        self,
        catalog_provider: Callable[[], Awaitable[dict[str, Any]]],
        gateway: ToolGateway | None = None,
    ) -> AgentResponse:
        catalog = await _call_provider(gateway or _DEFAULT_GATEWAY, "catalog.build", catalog_provider)
        categories = catalog.get("categories") or []
        total = int(catalog.get("total") or 0)
        lines = [f"当前共有 **{total}** 件商品。"]
        for category in categories[:8]:
            names = "、".join(
                str(item.get("name") or item.get("sku_code") or "")
                for item in (category.get("items") or [])[:4]
            )
            if names:
                lines.append(f"- **{category.get('name', '未分类')}**（{category.get('count', 0)}件）：{names}")
        lines.append("你可以继续告诉我想了解的商品，或直接发送商品图片。")
        return AgentResponse(
            reply="\n".join(lines),
            message_type="catalog",
            artifacts=[{"type": "catalog", "total": total, "categories": categories}],
            routing={
                "primary_intent": "product_catalog",
                "intent_group": "shopping_assistance",
                "primary_agent": self.name,
                "supporting_agents": [],
                "confidence": 1.0,
                "need_rag": False,
                "need_human": False,
                "entities": {},
                "evidence": {"source": "catalog_agent"},
            },
        )


async def _call_provider(gateway: ToolGateway | None, name: str, provider):
    if gateway is None:
        return await provider()
    result = await gateway.call(name, provider)
    if not result.success:
        raise RuntimeError(result.error or "tool_failed")
    return result.data
