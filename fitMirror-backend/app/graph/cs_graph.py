"""客服 LangGraph 编排：意图识别 → 试穿档案检查 / RAG 问答 / 闲聊回复。

图拓扑：
  START → intent_router
    ├─ tryon  → check_profile → (缺档案? ask_missing : chat_reply)
    ├─ faq    → rag_reply
    └─ chat   → chat_reply
  ask_missing / rag_reply / chat_reply → END
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.state import FitMirrorState


def build_cs_graph():
    """构建并编译客服对话图，使用 MemorySaver 按 session_id 保持多轮上下文。"""
    from app.graph.nodes.pipeline_nodes import (
        ask_missing_node,
        chat_reply_node,
        check_profile_node,
        intent_router_node,
        rag_reply_node,
    )

    g = StateGraph(FitMirrorState)
    g.add_node("intent_router", intent_router_node)
    g.add_node("check_profile", check_profile_node)
    g.add_node("ask_missing", ask_missing_node)
    g.add_node("rag_reply", rag_reply_node)
    g.add_node("chat_reply", chat_reply_node)

    g.add_edge(START, "intent_router")

    def route_intent(state: FitMirrorState) -> str:
        """根据 intent_router_node 写入的 intent 字段选择下游节点。"""
        intent = state.get("intent", "chat")
        if intent == "tryon":
            return "check_profile"
        if intent == "faq":
            return "rag_reply"
        return "chat_reply"

    g.add_conditional_edges("intent_router", route_intent, {
        "check_profile": "check_profile",
        "rag_reply": "rag_reply",
        "chat_reply": "chat_reply",
    })

    def route_profile(state: FitMirrorState) -> str:
        """试穿场景：缺少身高/体重时先追问，否则进入 chat_reply 生成试穿回复。"""
        if state.get("missing_fields"):
            return "ask_missing"
        return "chat_reply"

    g.add_conditional_edges("check_profile", route_profile, {
        "ask_missing": "ask_missing",
        "chat_reply": "chat_reply",
    })

    g.add_edge("ask_missing", END)
    g.add_edge("rag_reply", END)
    g.add_edge("chat_reply", END)

    return g.compile(checkpointer=MemorySaver())
