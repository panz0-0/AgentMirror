from __future__ import annotations

from fastapi import APIRouter, Response

from app.agentflow_adapter import IntentRouter
from app.agentflow_adapter.schemas import ChatRuntimeRequest
from app.core.success_response import success_response
from app.agentflow_adapter.prometheus_metrics import DEFAULT_PROMETHEUS
from app.agentflow_adapter.tool_gateway import DEFAULT_RUNTIME_METRICS

agentflow_router = APIRouter(prefix="/api/agentflow", tags=["agentflow"])
_router = IntentRouter()


@agentflow_router.post("/inspect-intent", summary="查看 AgentFlow 意图路由")
async def inspect_intent(body: ChatRuntimeRequest):
    """Migration endpoint: verify the new routing contract without changing chat behavior."""
    decision = _router.classify(body.content)
    return success_response(data=decision.model_dump(mode="json"))


@agentflow_router.get("/metrics", summary="?? AgentFlow ????")
async def metrics_snapshot():
    return success_response(data={"runtime": DEFAULT_RUNTIME_METRICS.snapshot(), "prometheus_available": DEFAULT_PROMETHEUS.available})

@agentflow_router.get("/metrics/prometheus", summary="Prometheus ??")
async def prometheus_metrics():
    payload, available = DEFAULT_PROMETHEUS.render()
    if not available:
        return Response(content="# prometheus-client is not installed\n", media_type="text/plain", status_code=503)
    return Response(content=payload, media_type="text/plain; version=0.0.4")
