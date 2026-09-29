from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.agentflow_adapter.schemas import AgentResponse
from app.agentflow_adapter.tool_gateway import DEFAULT_TOOL_GATEWAY, ToolGateway


_DEFAULT_GATEWAY = DEFAULT_TOOL_GATEWAY


class PolicyRAGAgent:
    """Agent boundary for policy/after-sales questions.

    Retrieval remains a provider/tool concern; the agent only turns the
    retrieved answer into the common AgentResponse contract.
    """

    name = "PolicyRAGAgent"

    async def handle(
        self,
        rag_provider: Callable[[], Awaitable[str]],
        gateway: ToolGateway | None = None,
    ) -> AgentResponse | None:
        answer = await _call_provider(gateway or _DEFAULT_GATEWAY, "rag.query", rag_provider)
        if not answer or self._is_no_result(answer):
            return None
        return AgentResponse(
            reply=answer,
            message_type="faq",
            routing={
                "primary_intent": "policy_faq",
                "intent_group": "customer_service",
                "primary_agent": self.name,
                "supporting_agents": [],
                "confidence": 1.0,
                "need_rag": True,
                "need_human": False,
                "entities": {},
                "evidence": {"source": "rag"},
            },
            citations=[],
        )

    @staticmethod
    def _is_no_result(answer: str) -> bool:
        return "暂未找到相关知识库" in answer


async def _call_provider(gateway: ToolGateway | None, name: str, provider):
    if gateway is None:
        return await provider()
    result = await gateway.call(name, provider)
    if not result.success:
        raise RuntimeError(result.error or "tool_failed")
    return result.data
