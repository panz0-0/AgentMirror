from app.agentflow_adapter import AgentFlowRuntime, IntentRouter
from app.agentflow_adapter.runtime import RouteMetrics


def test_intent_router_business_policy():
    decision = IntentRouter().classify("我想退货，几天能退款")
    assert decision.primary_intent == "policy_faq"
    assert decision.primary_agent == "PolicyRAGAgent"
    assert decision.need_rag is True
    assert decision.confidence >= 0.7


def test_intent_router_tryon():
    decision = IntentRouter().classify("我想试穿这件衣服")
    assert decision.primary_intent == "product_tryon"
    assert decision.primary_agent == "TryOnAgent"


def test_intent_router_image_fallback():
    decision = IntentRouter().classify("", has_image=True)
    assert decision.primary_intent == "similar_product"
    assert decision.evidence["source"] == "image"


def test_intent_router_general_fallback():
    decision = IntentRouter().classify("你好")
    assert decision.primary_intent == "general_chat"
    assert decision.primary_agent == "GeneralCustomerServiceAgent"


def test_runtime_preserves_legacy_payload_and_adds_routing():
    async def legacy_handler():
        return {
            "reply": "已为你找到商品",
            "metadata": {"type": "catalog", "actions": [{"type": "message"}]},
            "catalog": {"total": 3},
        }

    import asyncio

    result = asyncio.run(AgentFlowRuntime().handle("有哪些商品", legacy_handler))
    assert result["catalog"] == {"total": 3}
    assert result["metadata"]["type"] == "catalog"
    assert result["metadata"]["routing"]["primary_intent"] == "product_catalog"
    assert result["routing"]["primary_agent"] == "CatalogAgent"


def test_runtime_classifies_image_and_reports_consistency():
    async def legacy_handler():
        return {
            "reply": "???????",
            "metadata": {"type": "similar_product"},
            "executed_route": "legacy_similar_product",
        }

    import asyncio

    result = asyncio.run(AgentFlowRuntime().handle("", legacy_handler, has_image=True))
    assert result["routing"]["primary_intent"] == "similar_product"
    assert result["routing_consistent"] is True
    assert result["metadata"]["routing_consistent"] is True


def test_runtime_marks_uninstrumented_legacy_handler_as_unknown():
    async def legacy_handler():
        return {"reply": "ok", "metadata": {"type": "text"}}

    import asyncio

    result = asyncio.run(AgentFlowRuntime().handle("??", legacy_handler))
    assert result["routing_consistent"] is None


def test_runtime_marks_low_confidence_route_for_safe_fallback():
    async def legacy_handler():
        return {"reply": "ok", "metadata": {"type": "text"}, "executed_route": "legacy_langgraph_chat"}

    import asyncio

    result = asyncio.run(AgentFlowRuntime().handle("??", legacy_handler))
    assert result["routing_fallback"] is True
    assert result["fallback_reason"] == "low_confidence_intent"
    assert result["metadata"]["routing_fallback"] is True


def test_runtime_does_not_mark_strong_route_as_fallback():
    async def legacy_handler():
        return {"reply": "ok", "metadata": {"type": "text"}, "executed_route": "legacy_tryon"}

    import asyncio

    result = asyncio.run(AgentFlowRuntime().handle("\u8bf7\u5e2e\u6211\u8bd5\u7a7f\u8fd9\u4ef6\u8863\u670d", legacy_handler))
    assert result["routing_fallback"] is False
    assert result["fallback_reason"] is None


def test_route_metrics_snapshot():
    metrics = RouteMetrics()
    metrics.record(True, False)
    metrics.record(False, False)
    metrics.record(None, True)
    snapshot = metrics.snapshot()
    assert snapshot["total"] == 3
    assert snapshot["consistent"] == 1
    assert snapshot["inconsistent"] == 1
    assert snapshot["unknown"] == 1
    assert snapshot["fallback"] == 1
    assert snapshot["consistency_rate"] == 0.5
from app.agentflow_adapter import AgentFlowRuntime, IntentRouter
from app.agentflow_adapter.agents import CatalogAgent
from app.agentflow_adapter.runtime import RouteMetrics


def test_catalog_agent_composes_catalog_response():
    import asyncio

    async def provider():
        return {
            "total": 2,
            "categories": [{
                "name": "上衣",
                "count": 2,
                "items": [{"name": "风衣"}, {"sku_code": "TOP-001"}],
            }],
        }

    response = asyncio.run(CatalogAgent().handle(provider))
    assert response.message_type == "catalog"
    assert "2" in response.reply
    assert "风衣" in response.reply
    assert response.routing.primary_agent == "CatalogAgent"


def test_catalog_feature_flag_defaults_off_and_can_be_enabled():
    import os
    from app.agentflow_adapter.config import catalog_agent_enabled

    old = os.environ.pop("AGENTFLOW_CATALOG_ENABLED", None)
    try:
        assert catalog_agent_enabled() is False
        os.environ["AGENTFLOW_CATALOG_ENABLED"] = "true"
        assert catalog_agent_enabled() is True
    finally:
        if old is None:
            os.environ.pop("AGENTFLOW_CATALOG_ENABLED", None)
        else:
            os.environ["AGENTFLOW_CATALOG_ENABLED"] = old


def test_agent_catalog_route_is_consistent():
    from app.agentflow_adapter.runtime import route_consistency

    decision = IntentRouter().classify("有哪些商品")
    assert route_consistency(decision, "agent_catalog") is True


def test_policy_rag_agent_returns_faq_response():
    import asyncio
    from app.agentflow_adapter.agents import PolicyRAGAgent

    async def provider():
        return "退货后将在 3-5 个工作日内退款。"

    response = asyncio.run(PolicyRAGAgent().handle(provider))
    assert response is not None
    assert response.message_type == "faq"
    assert response.routing.primary_agent == "PolicyRAGAgent"


def test_policy_rag_agent_returns_none_when_knowledge_missing():
    import asyncio
    from app.agentflow_adapter.agents import PolicyRAGAgent

    async def provider():
        return "暂未找到相关知识库内容"

    assert asyncio.run(PolicyRAGAgent().handle(provider)) is None


def test_tryon_agent_composes_response():
    import asyncio
    from app.agentflow_adapter.agents import TryOnAgent

    async def provider():
        return {
            "reply": "试穿效果已准备好",
            "metadata": {"type": "tryon_result", "sku_id": "sku-1", "gallery_urls": []},
            "executed_route": "legacy_tryon",
        }

    response = asyncio.run(TryOnAgent().handle(provider))
    assert response.message_type == "tryon_result"
    assert response.routing.primary_agent == "TryOnAgent"
    assert response.routing.entities["sku_id"] == "sku-1"


def test_tryon_feature_flag_defaults_off_and_can_be_enabled():
    import os
    from app.agentflow_adapter.config import tryon_agent_enabled

    old = os.environ.pop("AGENTFLOW_TRYON_ENABLED", None)
    try:
        assert tryon_agent_enabled() is False
        os.environ["AGENTFLOW_TRYON_ENABLED"] = "true"
        assert tryon_agent_enabled() is True
    finally:
        if old is None:
            os.environ.pop("AGENTFLOW_TRYON_ENABLED", None)
        else:
            os.environ["AGENTFLOW_TRYON_ENABLED"] = old


def test_agent_tryon_route_is_consistent():
    from app.agentflow_adapter.runtime import route_consistency

    decision = IntentRouter().classify("请帮我试穿这件衣服")
    assert route_consistency(decision, "agent_tryon") is True


def test_product_advisor_agent_composes_product_response():
    import asyncio
    from app.agentflow_adapter.agents import ProductAdvisorAgent

    async def provider():
        return {
            "reply": "??????????",
            "metadata": {"type": "product_intro", "sku_id": "sku-1"},
            "intent": "product_intro",
        }

    response = asyncio.run(ProductAdvisorAgent().handle(provider))
    assert response.message_type == "product_intro"
    assert response.routing.primary_agent == "ProductAdvisorAgent"
    assert response.routing.entities["sku_id"] == "sku-1"


def test_product_advisor_feature_flag_defaults_off_and_can_be_enabled():
    import os
    from app.agentflow_adapter.config import product_advisor_agent_enabled

    old = os.environ.pop("AGENTFLOW_PRODUCT_ADVISOR_ENABLED", None)
    try:
        assert product_advisor_agent_enabled() is False
        os.environ["AGENTFLOW_PRODUCT_ADVISOR_ENABLED"] = "true"
        assert product_advisor_agent_enabled() is True
    finally:
        if old is None:
            os.environ.pop("AGENTFLOW_PRODUCT_ADVISOR_ENABLED", None)
        else:
            os.environ["AGENTFLOW_PRODUCT_ADVISOR_ENABLED"] = old


def test_product_advisor_route_is_consistent():
    from app.agentflow_adapter.runtime import route_consistency

    decision = IntentRouter().classify("\u4ecb\u7ecd\u4e00\u4e0b\u8fd9\u4ef6\u8863\u670d")
    assert route_consistency(decision, "agent_product_advisor") is True
import asyncio
from pathlib import Path

from app.agentflow_adapter.metrics import RuntimeMetrics
from app.agentflow_adapter.tool_gateway import ToolGateway


def test_tool_gateway_cache_and_metrics():
    async def run():
        calls = 0
        metrics = RuntimeMetrics()
        gateway = ToolGateway(metrics=metrics)

        async def provider():
            nonlocal calls
            calls += 1
            return {"ok": True}

        first = await gateway.call("catalog.build", provider, cache_ttl=30)
        second = await gateway.call("catalog.build", provider, cache_ttl=30)
        assert first.success and not first.cached
        assert second.success and second.cached
        assert calls == 1
        assert metrics.snapshot()["tools"]["catalog.build"]["success"] == 2

    asyncio.run(run())


def test_tool_gateway_timeout_retry_and_fallback():
    async def run():
        attempts = 0
        gateway = ToolGateway(failure_threshold=5)

        async def provider():
            nonlocal attempts
            attempts += 1
            await asyncio.sleep(0.02)
            return "never"

        result = await gateway.call("rag.query", provider, timeout=0.001, retries=1, fallback="legacy-answer")
        assert not result.success
        assert result.error == "timeout"
        assert result.data == "legacy-answer"
        assert attempts == 2

    asyncio.run(run())


def test_tool_gateway_cache_expires_and_uses_explicit_key():
    async def run():
        now = [100.0]
        calls = 0
        gateway = ToolGateway(clock=lambda: now[0])

        async def provider():
            nonlocal calls
            calls += 1
            return calls

        first = await gateway.call("catalog.build", provider, cache_ttl=5, cache_key="user-a")
        second = await gateway.call("catalog.build", provider, cache_ttl=5, cache_key="user-b")
        assert first.data == 1 and second.data == 2
        now[0] += 6
        third = await gateway.call("catalog.build", provider, cache_ttl=5, cache_key="user-a")
        assert third.data == 3

    asyncio.run(run())


def test_tool_gateway_opens_circuit_after_failures():
    async def run():
        calls = 0
        gateway = ToolGateway(failure_threshold=2, circuit_open_seconds=60)

        async def provider():
            nonlocal calls
            calls += 1
            raise RuntimeError("down")

        one = await gateway.call("tryon.generate", provider, fallback="fallback")
        two = await gateway.call("tryon.generate", provider, fallback="fallback")
        three = await gateway.call("tryon.generate", provider, fallback="fallback")
        assert one.data == two.data == three.data == "fallback"
        assert two.error != "circuit_open"
        assert three.error == "circuit_open"
        assert calls == 2

    asyncio.run(run())


def test_runtime_metrics_groups_routes_agents_and_tools():
    metrics = RuntimeMetrics()
    metrics.record_route("product_catalog", consistent=True, latency_ms=10)
    metrics.record_agent("CatalogAgent", success=True, latency_ms=11)
    metrics.record_tool("catalog.build", success=False, latency_ms=12, fallback=True)
    snapshot = metrics.snapshot()
    assert snapshot["routes"]["product_catalog"]["success_rate"] == 1.0
    assert snapshot["agents"]["CatalogAgent"]["calls"] == 1
    assert snapshot["tools"]["catalog.build"]["fallback"] == 1


def test_learning_document_contains_tool_gateway_section():
    text = Path(__file__).resolve().parents[2].joinpath("docs", "agentflow-integration.md").read_text(encoding="utf-8")
    assert "ToolGateway" in text




def test_all_agents_route_provider_calls_through_injected_gateway():
    from app.agentflow_adapter.agents.catalog_agent import CatalogAgent
    from app.agentflow_adapter.agents.policy_rag_agent import PolicyRAGAgent
    from app.agentflow_adapter.agents.product_advisor_agent import ProductAdvisorAgent
    from app.agentflow_adapter.agents.tryon_agent import TryOnAgent

    class RecordingGateway:
        def __init__(self):
            self.names = []

        async def call(self, name, provider, **kwargs):
            from app.agentflow_adapter.schemas import ToolResult
            self.names.append(name)
            return ToolResult(success=True, data=await provider(), latency_ms=0)

    async def run():
        gateway = RecordingGateway()
        await CatalogAgent().handle(lambda: _async_value({"categories": [], "total": 0}), gateway)
        await PolicyRAGAgent().handle(lambda: _async_value("answer"), gateway)
        await TryOnAgent().handle(lambda: _async_value({"reply": "try-on", "metadata": {}}), gateway)
        await ProductAdvisorAgent().handle(lambda: _async_value({"reply": "intro", "metadata": {}}), gateway)
        assert gateway.names == ["catalog.build", "rag.query", "tryon.generate", "product.advisor"]

    async def _async_value(value):
        return value

    asyncio.run(run())
