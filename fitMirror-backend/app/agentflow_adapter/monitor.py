from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
from typing import Any

@dataclass
class _Health:
    events: deque = field(default_factory=lambda: deque(maxlen=20))
    penalty: float = 0.0

class AgentHealthMonitor:
    """基于滑动窗口的 Agent 健康度与动态降权。"""
    def __init__(self, window_size: int = 20, min_weight: float = 0.2):
        self.window_size = window_size; self.min_weight = min_weight; self._items: dict[str, _Health] = {}
    def record(self, agent: str, *, success: bool, latency_ms: float = 0.0):
        h=self._items.setdefault(agent,_Health()); h.events.append((bool(success), max(0.0, latency_ms)))
        failures=sum(not ok for ok,_ in h.events); failure_rate=failures/len(h.events)
        slow=sum(lat > 3000 for ok,lat in h.events)/len(h.events)
        h.penalty=min(1.0, failure_rate*0.75 + slow*0.25)
    def penalty(self, agent: str) -> float: return self._items.get(agent,_Health()).penalty
    def weight(self, agent: str, base_weight: float = 1.0) -> float: return max(self.min_weight, base_weight*(1-self.penalty(agent)))
    def snapshot(self): return {a:{"penalty":h.penalty,"calls":len(h.events),"success_rate":sum(ok for ok,_ in h.events)/len(h.events) if h.events else None} for a,h in self._items.items()}

