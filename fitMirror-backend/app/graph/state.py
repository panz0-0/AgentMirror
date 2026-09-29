"""LangGraph 共享状态定义，供客服图（cs_graph）与运营流水线（ops_graph）复用。"""
from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class FitMirrorState(TypedDict, total=False):
    # --- 会话与任务标识 ---
    thread_id: str
    sku_id: Optional[str]
    job_id: Optional[str]
    # --- LangGraph 消息历史 ---
    messages: Annotated[list, add_messages]
    # --- 流水线产物 JSON（与 workspace 文件同步）---
    product_json: Optional[dict]
    campaign_json: Optional[dict]
    prompts_json: Optional[dict]
    # --- 客服上下文 ---
    user_profile: Optional[dict]
    memory_profile: Optional[dict]  # 跨会话回忆的用户画像（姓名/偏好等），注入到 LLM 系统提示词
    intent: Optional[str]
    missing_fields: list[str]
    # --- 出图结果 ---
    generated_image_paths: list[str]
    # --- 流水线控制 ---
    current_stage: str
    current_node: str
    generation_mode: str
    stop_at_stage: int
    awaiting_confirm: Optional[str]  # 暂停等待人工确认的节点名
    # --- 输出 ---
    reply_text: str
    error: Optional[str]
    workspace_path: str