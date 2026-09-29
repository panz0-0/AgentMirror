from __future__ import annotations

from typing import Any, Optional

from app.agentflow_adapter.schemas import ToolResult


def ok(data: Any, *, trace_id: Optional[str] = None, latency_ms: float = 0) -> ToolResult:
    return ToolResult(success=True, data=data, trace_id=trace_id, latency_ms=latency_ms)


def fail(message: str, *, trace_id: Optional[str] = None, latency_ms: float = 0) -> ToolResult:
    return ToolResult(success=False, error=message, trace_id=trace_id, latency_ms=latency_ms)
