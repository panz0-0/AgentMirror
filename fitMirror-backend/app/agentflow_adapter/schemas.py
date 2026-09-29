from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IntentDecision(BaseModel):
    primary_intent: str
    intent_group: str
    entities: Dict[str, Any] = Field(default_factory=dict)
    primary_agent: str
    supporting_agents: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    need_rag: bool = False
    need_human: bool = False
    evidence: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    success: bool
    data: Any = None
    error: Optional[str] = None
    latency_ms: float = 0
    cached: bool = False
    trace_id: Optional[str] = None


class AgentResponse(BaseModel):
    reply: str
    message_type: str = "text"
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    routing: Optional[IntentDecision] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    need_human: bool = False


class ChatRuntimeRequest(BaseModel):
    session_id: str
    user_id: str = "guest"
    content: str = ""
