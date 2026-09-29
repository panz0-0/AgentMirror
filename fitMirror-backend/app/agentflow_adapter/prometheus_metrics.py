"""轻量 Prometheus 指标导出器。

不依赖 prometheus_client 库，自行实现 Counter / Gauge / Histogram 并渲染
Prometheus text format（text/plain; version=0.0.4），供 /metrics 端点抓取。
"""
from __future__ import annotations

import threading
import time
from typing import Any


class _Counter:
    def __init__(self, name: str, help_text: str, labels: list[str] | None = None):
        self.name = name
        self.help = help_text
        self.labels = labels or []
        self._values: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **label_values):
        key = tuple(label_values.get(l, "") for l in self.labels) if self.labels else ()
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            for key, val in self._values.items():
                if self.labels:
                    label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                    lines.append(f"{self.name}{{{label_str}}} {val}")
                else:
                    lines.append(f"{self.name} {val}")
        return lines


class _Gauge:
    def __init__(self, name: str, help_text: str, labels: list[str] | None = None):
        self.name = name
        self.help = help_text
        self.labels = labels or []
        self._values: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **label_values):
        key = tuple(label_values.get(l, "") for l in self.labels) if self.labels else ()
        with self._lock:
            self._values[key] = float(value)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        with self._lock:
            for key, val in self._values.items():
                if self.labels:
                    label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                    lines.append(f"{self.name}{{{label_str}}} {val}")
                else:
                    lines.append(f"{self.name} {val}")
        return lines


class _Histogram:
    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self, name: str, help_text: str, labels: list[str] | None = None,
                 buckets: tuple[float, ...] = DEFAULT_BUCKETS):
        self.name = name
        self.help = help_text
        self.labels = labels or []
        self.buckets = buckets
        self._counts: dict[tuple, list[int]] = {}
        self._sums: dict[tuple, float] = {}
        self._totals: dict[tuple, int] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **label_values):
        key = tuple(label_values.get(l, "") for l in self.labels) if self.labels else ()
        with self._lock:
            if key not in self._counts:
                self._counts[key] = [0] * len(self.buckets)
                self._sums[key] = 0.0
                self._totals[key] = 0
            for i, b in enumerate(self.buckets):
                if value <= b:
                    self._counts[key][i] += 1
            self._sums[key] += value
            self._totals[key] += 1

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with self._lock:
            for key, counts in self._counts.items():
                label_prefix = ""
                if self.labels:
                    label_prefix = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                for i, b in enumerate(self.buckets):
                    if self.labels:
                        lines.append(f'{self.name}_bucket{{le="{b}",{label_prefix}}} {counts[i]}')
                    else:
                        lines.append(f'{self.name}_bucket{{le="{b}"}} {counts[i]}')
                if self.labels:
                    lines.append(f'{self.name}_bucket{{le="+Inf",{label_prefix}}} {self._totals[key]}')
                    lines.append(f'{self.name}_sum{{{label_prefix}}} {self._sums[key]}')
                    lines.append(f'{self.name}_count{{{label_prefix}}} {self._totals[key]}')
                else:
                    lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._totals[key]}')
                    lines.append(f'{self.name}_sum {self._sums[key]}')
                    lines.append(f'{self.name}_count {self._totals[key]}')
        return lines


class PrometheusExporter:
    """聚合所有 AgentFlow 指标并渲染为 Prometheus text format。"""

    def __init__(self):
        self.available = True  # 内置实现，始终可用
        self.requests = _Counter("agentflow_requests_total", "AgentFlow requests")
        self.tools = _Counter("agentflow_tool_calls_total", "AgentFlow tool calls", ["tool", "success"])
        self.fallbacks = _Counter("agentflow_fallback_total", "AgentFlow fallbacks")
        self.latency = _Histogram("agentflow_request_latency_seconds", "AgentFlow request latency")
        self.penalty = _Gauge("agentflow_agent_penalty", "Agent penalty", ["agent"])
        self.tool_latency = _Histogram("agentflow_tool_latency_seconds", "AgentFlow tool latency", ["tool"])
        self.route_consistency = _Counter(
            "agentflow_route_consistency_total", "AgentFlow route consistency", ["consistent"]
        )
        self.tool_failures = _Counter("agentflow_tool_failures_total", "AgentFlow tool failures", ["tool"])

    def record_request(self, latency_ms: float = 0, success: bool = True, fallback: bool = False):
        self.requests.inc()
        self.latency.observe(max(0, latency_ms) / 1000)
        if fallback:
            self.fallbacks.inc()

    def record_route_consistency(self, consistent: bool):
        self.route_consistency.inc(consistent=str(bool(consistent)).lower())

    def record_tool(self, tool: str, success: bool = True, latency_ms: float = 0):
        self.tools.inc(tool=tool, success=str(bool(success)).lower())
        self.tool_latency.observe(max(0, latency_ms) / 1000, tool=tool)
        if not success:
            self.tool_failures.inc(tool=tool)

    def set_penalty(self, agent: str, value: float):
        self.penalty.set(float(value), agent=agent)

    def render(self) -> tuple[str, bool]:
        lines: list[str] = []
        for metric in (self.requests, self.tools, self.fallbacks, self.latency,
                       self.penalty, self.tool_latency, self.route_consistency,
                       self.tool_failures):
            lines.extend(metric.render())
        return "\n".join(lines) + "\n", True


DEFAULT_PROMETHEUS = PrometheusExporter()
