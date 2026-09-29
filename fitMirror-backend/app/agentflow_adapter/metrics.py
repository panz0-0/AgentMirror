from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Stats:
    calls: int = 0
    success: int = 0
    failure: int = 0
    total_latency_ms: float = 0.0
    fallback: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "success": self.success,
            "failure": self.failure,
            "fallback": self.fallback,
            "success_rate": self.success / self.calls if self.calls else None,
            "avg_latency_ms": self.total_latency_ms / self.calls if self.calls else None,
        }


class RuntimeMetrics:
    """Process-local observability seam for the migration.

    The shape is intentionally exporter-friendly, but this is not a Prometheus
    client or a distributed metrics store yet.
    """

    def __init__(self) -> None:
        self.routes: dict[str, _Stats] = {}
        self.agents: dict[str, _Stats] = {}
        self.tools: dict[str, _Stats] = {}

    def _record(self, store: dict[str, _Stats], name: str, *, success: bool, latency_ms: float, fallback: bool = False) -> None:
        stats = store.setdefault(name, _Stats())
        stats.calls += 1
        stats.success += int(success)
        stats.failure += int(not success)
        stats.fallback += int(fallback)
        stats.total_latency_ms += max(0.0, latency_ms)

    def record_route(self, route: str, *, consistent: bool | None, latency_ms: float = 0.0, fallback: bool = False) -> None:
        self._record(self.routes, route, success=consistent is not False, latency_ms=latency_ms, fallback=fallback)

    def record_agent(self, agent: str, *, success: bool, latency_ms: float, fallback: bool = False) -> None:
        self._record(self.agents, agent, success=success, latency_ms=latency_ms, fallback=fallback)

    def record_tool(self, tool: str, *, success: bool, latency_ms: float, fallback: bool = False) -> None:
        self._record(self.tools, tool, success=success, latency_ms=latency_ms, fallback=fallback)

    def snapshot(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            "routes": {name: stats.snapshot() for name, stats in self.routes.items()},
            "agents": {name: stats.snapshot() for name, stats in self.agents.items()},
            "tools": {name: stats.snapshot() for name, stats in self.tools.items()},
        }

    def reset(self) -> None:
        self.routes.clear()
        self.agents.clear()
        self.tools.clear()
