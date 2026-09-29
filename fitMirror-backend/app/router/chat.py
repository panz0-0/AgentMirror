"""fitMirror customer chat API routes.

AgentFlow now observes both text and image/chat-compose boundaries while the
legacy domain services remain responsible for producing the business response.
"""
import json
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Path, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agentflow_adapter.memory_global import set_memory_manager
from app.agentflow_adapter.runtime import AgentFlowRuntime
from app.core.rate_limit import rate_limit
from app.core.success_response import success_response
from app.db.db_config import get_db
from app.schemas.models import ChatMessageRequest, ChatSessionCreate, UserProfileUpdate
from app.services import chat_service
from app.services.catalog_service import build_catalog

chat_router = APIRouter(prefix="/api/chat", tags=["chat"])
agentflow_runtime = AgentFlowRuntime()
# 注册全局 memory 单例，供 chat_service / pipeline_nodes 注入用户画像到 LLM prompt
set_memory_manager(agentflow_runtime.memory)


@chat_router.post("/session", summary="Create chat session")
async def create_session(body: ChatSessionCreate, db: AsyncSession = Depends(get_db)):
    session = await chat_service.create_session(db, body.user_id, body.title)
    return success_response(data={"session_id": session.id, "title": session.title})


@chat_router.get("/sessions", summary="List chat sessions")
async def list_sessions(
    user_id: Annotated[str, Query()] = "guest",
    db: AsyncSession = Depends(get_db),
):
    sessions = await chat_service.list_sessions(db, user_id)
    return success_response(data=[
        {
            "id": session.id,
            "title": session.title,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        }
        for session in sessions
    ])


@chat_router.delete("/session/{session_id}", summary="Delete chat session")
async def delete_session(
    session_id: Annotated[str, Path()],
    user_id: Annotated[str, Query()] = "guest",
    db: AsyncSession = Depends(get_db),
):
    deleted = await chat_service.delete_session(db, session_id, user_id)
    if not deleted:
        return success_response(message="Session not found", data=None)
    return success_response(message="Session deleted", data=None)


@chat_router.get("/session/{session_id}/history", summary="Get chat history")
async def session_history(
    session_id: Annotated[str, Path()],
    db: AsyncSession = Depends(get_db),
):
    messages = await chat_service.get_history(db, session_id)
    return success_response(data=[
        {
            "id": message.id,
            "role": message.role,
            "content": chat_service.normalize_legacy_chat_text(message.content),
            "metadata": message.metadata_ or {},
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
        for message in messages
    ])


@chat_router.get("/catalog", summary="Get product catalog")
async def get_catalog(db: AsyncSession = Depends(get_db)):
    catalog = await build_catalog(db)
    return success_response(data={
        "total": catalog["total"],
        "categories": catalog["categories"],
        "items": catalog["items"],
    })


@chat_router.post("/message", summary="Send text message")
async def send_message(body: ChatMessageRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Run the new runtime boundary while preserving the legacy business handler."""
    body.content = chat_service.fix_gbk_garbled(body.content)
    result = await agentflow_runtime.handle(
        body.content,
        lambda: chat_service.process_chat_message(
            db,
            body.session_id,
            body.user_id,
            body.content,
        ),
        session_id=body.session_id,
        user_id=body.user_id,
        context={"db": db},
    )
    # assistant 回复也可能携带 GBK 乱码（如商品数据、LLM 输出），统一修复后再返回
    if isinstance(result.get("reply"), str):
        result["reply"] = chat_service.fix_gbk_garbled(result["reply"])
    # 线上 badcase 异步采集：LLM 质检低分回复自动入库（不阻塞响应）
    try:
        from app.agentflow_adapter.online_badcase import collect_online_badcase
        from app.utils.factory import get_chat_model, has_llm_configured
        if has_llm_configured():
            reply = result.get("reply", "")
            route = result.get("executed_route", "")
            agentflow_executed = result.get("agentflow_executed", False)
            background_tasks.add_task(
                collect_online_badcase,
                body.content, reply, route, agentflow_executed,
                body.user_id, body.session_id, get_chat_model,
            )
    except Exception:
        pass  # 采集失败不影响主流程
    # 提取业务错误到 response header，供调用日志中间件捕获
    biz_error = result.pop("_business_error", None)
    response = success_response(data=result)
    if biz_error:
        response.headers["X-Business-Error"] = biz_error[:500]
    return response


@chat_router.post("/message/image", summary="Send image message")
async def send_image_message(
    session_id: Annotated[str, Form()],
    user_id: Annotated[str, Form()] = "guest",
    content: Annotated[str, Form()] = "",
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: None = rate_limit(10, 60),
):
    image_bytes = await image.read()
    result = await agentflow_runtime.handle(
        content,
        lambda: chat_service.process_combined_message(
            db,
            session_id,
            user_id,
            content,
            image_bytes,
            image.filename or "upload.png",
        ),
        has_image=True, session_id=session_id, user_id=user_id,
        context={"db": db},
    )
    if isinstance(result.get("reply"), str):
        result["reply"] = chat_service.fix_gbk_garbled(result["reply"])
    return success_response(data=result)


@chat_router.post("/message/compose", summary="Send optional text and image")
async def send_compose_message(
    session_id: Annotated[str, Form()],
    user_id: Annotated[str, Form()] = "guest",
    content: Annotated[str, Form()] = "",
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    _: None = rate_limit(10, 60),
):
    image_bytes = await image.read() if image else None
    filename = image.filename if image else "paste.png"
    if image_bytes is not None:
        result = await agentflow_runtime.handle(
            content,
            lambda: chat_service.process_combined_message(
                db,
                session_id,
                user_id,
                content,
                image_bytes,
                filename,
            ),
            has_image=True, session_id=session_id, user_id=user_id,
        context={"db": db},
    )
    else:
        result = await agentflow_runtime.handle(
            content,
            lambda: chat_service.process_combined_message(
                db,
                session_id,
                user_id,
                content,
                image_bytes,
                filename,
            ),
            session_id=session_id,
            user_id=user_id,
            context={"db": db},
        )
    if isinstance(result.get("reply"), str):
        result["reply"] = chat_service.fix_gbk_garbled(result["reply"])
    return success_response(data=result)


@chat_router.post("/product/{sku_id}", summary="Introduce product")
async def introduce_product(
    sku_id: Annotated[str, Path()],
    session_id: Annotated[str, Form()],
    user_id: Annotated[str, Form()] = "guest",
    db: AsyncSession = Depends(get_db),
):
    result = await chat_service.introduce_product(db, session_id, user_id, sku_id)
    return success_response(data=result)


@chat_router.post("/tryon", summary="Start virtual try-on")
async def start_tryon(
    session_id: Annotated[str, Form()],
    sku_id: Annotated[str, Form()],
    user_id: Annotated[str, Form()] = "guest",
    db: AsyncSession = Depends(get_db),
):
    result = await chat_service.start_tryon_for_sku(db, session_id, user_id, sku_id)
    return success_response(data=result)


@chat_router.post("/message/stream", summary="Stream text message")
async def send_message_stream(body: ChatMessageRequest, db: AsyncSession = Depends(get_db)):
    async def generate():
        yield "data: " + json.dumps(
            {"type": "thinking", "content": "Processing..."}, ensure_ascii=False
        ) + "\n\n"
        result = await agentflow_runtime.handle(
            body.content,
            lambda: chat_service.process_chat_message(
                db,
                body.session_id,
                body.user_id,
                body.content,
            ),
            session_id=body.session_id,
            user_id=body.user_id,
            context={"db": db},
        )
        reply = result.get("reply", "") if isinstance(result, dict) else ""
        for character in reply:
            yield "data: " + json.dumps(
                {"type": "response", "content": character}, ensure_ascii=False
            ) + "\n\n"
        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@chat_router.put("/profile", summary="Update user profile")
async def update_profile(body: UserProfileUpdate, db: AsyncSession = Depends(get_db)):
    profile = await chat_service.upsert_profile(
        db,
        body.user_id,
        body.height_cm,
        body.weight_kg,
    )
    return success_response(data={
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
    })

