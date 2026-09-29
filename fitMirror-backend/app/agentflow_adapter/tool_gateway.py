from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.agentflow_adapter.metrics import RuntimeMetrics
from app.agentflow_adapter.schemas import ToolResult
from app.agentflow_adapter.prometheus_metrics import DEFAULT_PROMETHEUS


@dataclass
class _CacheEntry:
    expires_at: float
    value: Any


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0.0


class ToolGateway:
    """Async reliability boundary for AgentFlow tools (process-local v1)."""

    def __init__(self, *, clock: Callable[[], float] | None = None,
                 failure_threshold: int = 3, circuit_open_seconds: float = 10.0,
                 metrics: RuntimeMetrics | None = None,
                 default_timeouts: dict[str, float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self.default_timeouts = default_timeouts or {
            "catalog.build": 10.0,
            "rag.query": 30.0,
            "tryon.generate": 90.0,
            "product.advisor": 10.0,
        }
        self.failure_threshold = max(1, failure_threshold)
        self.circuit_open_seconds = max(0.0, circuit_open_seconds)
        self.metrics = metrics
        self._cache: dict[str, _CacheEntry] = {}
        self._circuits: dict[str, _CircuitState] = {}

    async def call(self, name: str, provider: Callable[[], Any], *, timeout: float | None = None,
                   cache_ttl: float = 0.0, cache_key: str | None = None,
                   retries: int = 0, fallback: Any = None) -> ToolResult:
        started = self._clock()
        if timeout is None:
            timeout = self.default_timeouts.get(name)
        key = cache_key or name
        cached = self._cache.get(key) if cache_ttl > 0 else None
        if cached and cached.expires_at > self._clock():
            result = ToolResult(success=True, data=cached.value, latency_ms=self._elapsed_ms(started), cached=True)
            self._record(name, result)
            return result
        if cached:
            self._cache.pop(key, None)
        circuit = self._circuits.setdefault(name, _CircuitState())
        now = self._clock()
        if circuit.opened_until > now:
            data = await self._resolve_fallback(fallback)
            result = ToolResult(success=False, data=data, error="circuit_open", latency_ms=self._elapsed_ms(started))
            self._record(name, result, fallback=data is not None)
            return result
        if circuit.opened_until:
            circuit.opened_until = 0.0
            circuit.failures = 0
        last_error = "tool_failed"
        for attempt in range(max(0, retries) + 1):
            try:
                value = provider()
                if inspect.isawaitable(value):
                    value = await asyncio.wait_for(value, timeout=timeout) if timeout is not None else await value
                if cache_ttl > 0:
                    self._cache[key] = _CacheEntry(self._clock() + cache_ttl, value)
                circuit.failures = 0
                circuit.opened_until = 0.0
                result = ToolResult(success=True, data=value, latency_ms=self._elapsed_ms(started))
                self._record(name, result)
                return result
            except asyncio.TimeoutError:
                last_error = "timeout"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:240]
            if attempt < retries:
                await asyncio.sleep(0)
        circuit.failures += 1
        if circuit.failures >= self.failure_threshold:
            circuit.opened_until = self._clock() + self.circuit_open_seconds
        data = await self._resolve_fallback(fallback)
        result = ToolResult(success=False, data=data, error=last_error, latency_ms=self._elapsed_ms(started))
        self._record(name, result, fallback=data is not None)
        return result

    async def _resolve_fallback(self, fallback: Any) -> Any:
        if fallback is None:
            return None
        value = fallback() if callable(fallback) else fallback
        return await value if inspect.isawaitable(value) else value

    def _record(self, name: str, result: ToolResult, fallback: bool = False) -> None:
        if self.metrics:
            self.metrics.record_tool(name, success=result.success, latency_ms=result.latency_ms, fallback=fallback)
        DEFAULT_PROMETHEUS.record_tool(name, result.success, result.latency_ms)

    def _elapsed_ms(self, started: float) -> float:
        return round(max(0.0, self._clock() - started) * 1000, 3)

    def reset(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear(); self._circuits.clear(); return
        self._circuits.pop(name, None); self._cache.pop(name, None)


DEFAULT_RUNTIME_METRICS = RuntimeMetrics()
DEFAULT_TOOL_GATEWAY = ToolGateway(metrics=DEFAULT_RUNTIME_METRICS)

__all__ = ["ToolGateway", "DEFAULT_TOOL_GATEWAY", "DEFAULT_RUNTIME_METRICS"]
