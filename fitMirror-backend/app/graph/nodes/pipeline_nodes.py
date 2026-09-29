"""LangGraph nodes for ops and customer service flows."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.graph.state import FitMirrorState
from app.pipeline.json_utils import read_json, write_json
from app.pipeline.runner import run_sku
from app.services.job_progress import set_job_progress
from app.utils.factory import get_chat_model
from app.utils.pipeline_settings import build_pipeline_config, sku_to_product_input

logger = logging.getLogger(__name__)

CS_SYSTEM_PROMPT = (
    "\u4f60\u662f fitMirror \u667a\u80fd\u5728\u7ebf\u5ba2\u670d\uff08AI \u52a9\u624b\uff09\uff0c\u5f53\u524d\u4eba\u5de5\u5ba2\u670d\u4e0d\u5728\u7ebf\uff0c\u7531\u4f60\u5168\u7a0b\u63a5\u5f85\u3002\n"
    "\u8bed\u6c14\u4eb2\u5207\u4e13\u4e1a\uff0c\u53ef\u9002\u5f53\u4f7f\u7528\u201c\u4eb2\u201d\u3002\n"
    "\u4f60\u80fd\u5e2e\u52a9\u7528\u6237\uff1a\u5546\u54c1\u54a8\u8be2\u3001\u5c3a\u7801\u63a8\u8350\u3001\u53d1\u8d27\u67e5\u8be2\u3001\u9000\u6362\u8d27\u653f\u7b56\u3001\u865a\u62df\u8bd5\u7a7f\u548c\u642d\u914d\u5efa\u8bae\u3002\n"
    "\u56de\u7b54\u7b80\u6d01\u660e\u4e86\uff0c\u4e00\u6b21\u8bf4\u6e05\u91cd\u70b9\uff1b\u4e0d\u786e\u5b9a\u65f6\u8bf7\u5efa\u8bae\u8054\u7cfb\u4eba\u5de5\u5ba2\u670d\u3002"
)


def load_sku_node(state: FitMirrorState, sku_record: Any, workspace: Path) -> dict:
    """加载 workspace 已有产物 JSON，作为后续 stage 的输入。"""
    ws = workspace
    product = campaign = prompts = None
    if (ws / "product.json").exists():
        product = read_json(ws / "product.json")
    if (ws / "campaign.json").exists():
        campaign = read_json(ws / "campaign.json")
    if (ws / "prompts.json").exists():
        prompts = read_json(ws / "prompts.json")
    return {
        "workspace_path": str(ws),
        "product_json": product,
        "campaign_json": campaign,
        "prompts_json": prompts,
        "current_node": "load_sku",
    }


def stage1_node(state: FitMirrorState, sku_record: Any, workspace: Path) -> dict:
    """Stage1 产品分析：调用 run_sku 生成 product.json。"""
    """Stage1 产品分析：调用 run_sku 生成 product.json。"""
    job_id = state.get("job_id", "")
    set_job_progress(job_id, stage="stage1", status="running")
    cfg = build_pipeline_config(output_root=workspace.parent, generation_mode="__stage2__", force=False)
    cfg.output_root = str(workspace.parent)
    product_input = sku_to_product_input(sku_record, workspace)
    result = run_sku(cfg, product_input, progress_callback=lambda s, d: set_job_progress(job_id, stage=s, **d))
    set_job_progress(job_id, stage="stage1", status="done")
    return {
        "product_json": result.get("product") or read_json(workspace / "product.json"),
        "campaign_json": result.get("campaign"),
        "current_node": "stage1",
        "current_stage": "stage1",
    }


def stage2_node(state: FitMirrorState, sku_record: Any, workspace: Path) -> dict:
    """Stage2 营销策略：生成 campaign.json，完成后暂停等待运营确认。"""
    """Stage2 营销策略：生成 campaign.json，完成后暂停等待运营确认。"""
    job_id = state.get("job_id", "")
    set_job_progress(job_id, stage="stage2", status="running")

    if (workspace / "campaign.json").exists():
        campaign = read_json(workspace / "campaign.json")
        set_job_progress(job_id, stage="stage2", status="cached")
        return {
            "campaign_json": campaign,
            "current_node": "stage2",
            "current_stage": "stage2",
            "awaiting_confirm": "campaign",
        }

    cfg = build_pipeline_config(output_root=workspace.parent, generation_mode="__stage2__")
    cfg.output_root = str(workspace.parent)
    product_input = sku_to_product_input(sku_record, workspace)
    result = run_sku(cfg, product_input)
    campaign = result.get("campaign") or read_json(workspace / "campaign.json")
    set_job_progress(job_id, stage="stage2", status="done")
    return {
        "campaign_json": campaign,
        "current_node": "stage2",
        "current_stage": "stage2",
        "awaiting_confirm": "campaign",
    }


def stage3_node(state: FitMirrorState, sku_record: Any, workspace: Path) -> dict:
    """Stage3 提示词生成：按出图模式生成 prompts.json，完成后暂停等待确认。"""
    """Stage3 提示词生成：按出图模式生成 prompts.json，完成后暂停等待确认。"""
    job_id = state.get("job_id", "")
    mode = state.get("generation_mode", "hero")
    set_job_progress(job_id, stage="stage3", status="running")

    cfg = build_pipeline_config(output_root=workspace.parent, generation_mode=mode)
    cfg.output_root = str(workspace.parent)
    product_input = sku_to_product_input(sku_record, workspace)
    from app.pipeline.client import build_client
    from app.pipeline.cache import PromptCache
    from app.pipeline.stage3 import stage3_generate_prompts

    client = build_client(cfg)
    cache = PromptCache(workspace / "prompt_cache.json")
    product = state.get("product_json") or read_json(workspace / "product.json")
    campaign = state.get("campaign_json") or read_json(workspace / "campaign.json")
    prompts = stage3_generate_prompts(
        client,
        cfg,
        product,
        campaign,
        category=product_input.category,
        style=product_input.style,
        additional_requirements=product_input.additional_requirements,
        platform=product_input.platform,
        language=product_input.language,
        generation_mode=cfg.generation_mode,
        model_attrs=product_input.model_attrs,
        model_scene=product_input.model_scene,
        shooting_style=product_input.shooting_style,
        face_visible=product_input.face_visible,
        cache=cache,
    )
    write_json(workspace / "prompts.json", prompts)
    set_job_progress(job_id, stage="stage3", status="done", count=len(prompts))
    return {
        "prompts_json": prompts,
        "current_node": "stage3",
        "current_stage": "stage3",
        "awaiting_confirm": "prompts",
    }


def generate_images_node(
    state: FitMirrorState,
    sku_record: Any,
    workspace: Path,
    output_dir: Path,
) -> dict:
    """批量出图：已有 PNG 时仅同步文件，否则调用图像 API 逐张生成。"""
    """批量出图：已有 PNG 时仅同步文件，否则调用图像 API 逐张生成。"""
    from app.pipeline.client import build_image_client
    from app.pipeline.image_gen import generate_all_images
    from app.pipeline.prompt_templates import get_modules_for_mode
    from app.services.workspace_service import compute_image_progress, sync_workspace_images_to_job

    job_id = state.get("job_id", "")
    mode = state.get("generation_mode", "hero")
    prompts = state.get("prompts_json")
    if not prompts and (workspace / "prompts.json").exists():
        prompts = read_json(workspace / "prompts.json")
    if not prompts:
        raise ValueError("prompts.json 不存在，请先生成提示词")

    image_progress = compute_image_progress(workspace, mode, prompts)
    total = image_progress["total"]
    done_count = image_progress["done"]

    def progress_callback(code, status, path, done=None):
        current = done if done is not None else compute_image_progress(workspace, mode, prompts)["done"]
        set_job_progress(
            job_id,
            stage="image_done",
            code=code,
            status=status,
            done=current,
            total=total,
        )

    set_job_progress(job_id, stage="images", status="running", done=done_count, total=total)

    # 全部已生成: 仅同步文件, 不调用图像 API
    if image_progress["complete"]:
        paths = sync_workspace_images_to_job(workspace, output_dir, mode)
        set_job_progress(
            job_id,
            stage="images",
            status="done",
            done=done_count,
            total=total,
            count=len(paths),
            generated=0,
            skipped=done_count,
            failed=0,
        )
        return {
            "generated_image_paths": paths,
            "current_node": "generate_images",
            "current_stage": "done",
            "awaiting_confirm": None,
        }

    cfg = build_pipeline_config(output_root=workspace.parent, generation_mode=mode, enable_images=True)
    cfg.output_root = str(workspace.parent)
    cfg.enable_generate_images = True
    cfg.force = False
    product_input = sku_to_product_input(sku_record, workspace)

    image_client = build_image_client(cfg)

    stats = generate_all_images(
        image_client,
        cfg,
        prompts,
        product_input.image,
        workspace,
        progress_callback=progress_callback,
        category=product_input.category,
    )

    paths = sync_workspace_images_to_job(workspace, output_dir, mode)

    final_done = compute_image_progress(workspace, mode, prompts)["done"]
    set_job_progress(
        job_id,
        stage="images",
        status="done",
        done=final_done,
        total=total,
        count=len(paths),
        **stats,
    )
    return {
        "generated_image_paths": paths,
        "current_node": "generate_images",
        "current_stage": "done",
        "awaiting_confirm": None,
    }


def extract_profile_from_text(text: str) -> dict:
    height = weight = None
    hm = re.search(r"身高\s*[:：]?\s*(\d{2,3})", text)
    wm = re.search(r"体重\s*[:：]?\s*(\d{2,3})", text)
    if hm:
        height = float(hm.group(1))
    if wm:
        weight = float(wm.group(1))
    if height is None:
        hm2 = re.search(r"(\d{3})\s*cm", text, re.I)
        if hm2:
            height = float(hm2.group(1))
    if weight is None:
        wm2 = re.search(r"(\d{2,3})\s*kg", text, re.I)
        if wm2:
            weight = float(wm2.group(1))
    return {"height_cm": height, "weight_kg": weight}


def intent_router_node(state: FitMirrorState) -> dict:
    """客服意图分类：试穿 / FAQ / 闲聊，结果写入 state.intent 供条件路由。"""
    last = ""
    for msg in reversed(state.get("messages", [])):
        content = msg.content if hasattr(msg, "content") else str(msg.get("content", ""))
        last = content
        break
    lower = last.lower()
    if any(k in last for k in ("试穿", "试试", "上身", "效果图", "穿搭", "穿上")):
        intent = "tryon"
    elif any(k in last for k in ("退货", "退换", "政策", "发货", "物流", "几天", "运费", "保修", "售后", "尺码表", "包邮", "换货", "退款")):
        intent = "faq"
    else:
        intent = "chat"
    return {"intent": intent, "current_node": "intent_router"}


def check_profile_node(state: FitMirrorState) -> dict:
    """试穿前检查用户身高体重，从消息文本中提取并标记缺失字段。"""
    profile = dict(state.get("user_profile") or {})
    for msg in state.get("messages", []):
        content = msg.content if hasattr(msg, "content") else str(msg.get("content", ""))
        extracted = extract_profile_from_text(content)
        if extracted.get("height_cm"):
            profile["height_cm"] = extracted["height_cm"]
        if extracted.get("weight_kg"):
            profile["weight_kg"] = extracted["weight_kg"]
    missing = []
    if not profile.get("height_cm"):
        missing.append("height_cm")
    if not profile.get("weight_kg"):
        missing.append("weight_kg")
    return {"user_profile": profile, "missing_fields": missing, "current_node": "check_profile"}


def ask_missing_node(state: FitMirrorState) -> dict:
    missing = state.get("missing_fields") or []
    if "height_cm" in missing and "weight_kg" in missing:
        text = "亲，请告诉我您的身高（cm）和体重（kg），方便为您生成更准确的试穿效果图哦～"
    elif "height_cm" in missing:
        text = "亲，请告诉我您的身高（cm）哦～"
    else:
        text = "亲，请告诉我您的体重（kg）哦～"
    return {"reply_text": text, "current_node": "ask_missing"}


def rag_reply_node(state: FitMirrorState) -> dict:
    """FAQ intent: retrieve knowledge and fall back to the general reply path."""
    from app.rag.rag_service import RagService

    last = ""
    for msg in reversed(state.get("messages", [])):
        last = msg.content if hasattr(msg, "content") else str(msg.get("content", ""))
        break
    try:
        answer = RagService().query(last)
    except Exception:
        logger.exception("RAG node failed; falling back to chat reply")
        return chat_reply_node(state)
    if "\u6682\u672a\u627e\u5230\u76f8\u5173\u77e5\u8bc6\u5e93" in answer:
        return chat_reply_node(state)
    return {"reply_text": answer, "current_node": "rag_reply"}


def chat_reply_node(state: FitMirrorState) -> dict:
    """通用闲聊回复：取最近 12 条消息调用 LLM，使用客服系统提示词。"""
    model = get_chat_model()
    if not model:
        return {"reply_text": "亲亲，系统暂时繁忙，请稍后再试或留言人工客服。", "current_node": "chat_reply"}
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    system_prompt = CS_SYSTEM_PROMPT
    # 注入跨会话回忆的用户画像（姓名/偏好等），让 AI 能记住用户
    memory_profile = state.get("memory_profile")
    if memory_profile:
        profile_text = memory_profile.get("text", "")
        meta = memory_profile.get("meta", {}) or {}
        name = meta.get("name")
        style = meta.get("style_preference")
        size = meta.get("size")
        height = meta.get("height_cm")
        weight = meta.get("weight_kg")
        parts = []
        if name and name != "null":
            parts.append(f"用户称呼：{name}")
        if height and height != "null":
            parts.append(f"身高：{height}cm")
        if weight and weight != "null":
            parts.append(f"体重：{weight}kg")
        if style and style != "null":
            parts.append(f"风格偏好：{style}")
        if size and size != "null":
            parts.append(f"尺码：{size}")
        if profile_text:
            parts.append(f"画像摘要：{profile_text}")
        if parts:
            system_prompt += "\n\n【用户长期画像（跨会话回忆）】\n" + "\n".join(parts) + "\n请在回复中自然地使用这些信息，让用户感到被记住。"

    msgs = [SystemMessage(content=system_prompt)]
    for m in state.get("messages", [])[-12:]:
        role = m.type if hasattr(m, "type") else m.get("role", "human")
        content = m.content if hasattr(m, "content") else m.get("content", "")
        if role in ("human", "user"):
            msgs.append(HumanMessage(content=content))
        elif role in ("ai", "assistant"):
            msgs.append(AIMessage(content=content))
    try:
        resp = model.invoke(msgs)
        reply = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception:
        # LLM ????????????????? HTTP ???? 500?
        logger.exception("LLM request failed in customer chat; using fallback")
        reply = "\u4eb2\u4eb2\uff0c\u5f53\u524d\u667a\u80fd\u5ba2\u670d\u6682\u65f6\u65e0\u6cd5\u8fde\u63a5\u670d\u52a1\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u6216\u7559\u8a00\u4eba\u5de5\u5ba2\u670d\u3002"
    return {"reply_text": reply, "current_node": "chat_reply"}
