"""健康检查与生成图片静态访问 API。"""
import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, Path as PathParam
from fastapi.responses import FileResponse

from app.core.success_response import success_response
from app.db.db_config import check_db_connection, get_db_info
from app.utils.factory import get_chat_model, has_llm_configured

health_router = APIRouter(prefix="/api/health", tags=["health"])
images_router = APIRouter(prefix="/api/images", tags=["images"])

# LLM 可达性缓存：避免每次 health 都调用外部 API
_llm_reach_cache: dict[str, float | bool] = {"ts": 0.0, "ok": False}
_LLM_REACH_TTL = 60.0


async def _check_llm_reachable() -> bool:
    """轻量 LLM 探活：发送一个 token 级请求，带超时，结果缓存 60 秒。"""
    now = time.time()
    if now - float(_llm_reach_cache.get("ts", 0)) < _LLM_REACH_TTL:
        return bool(_llm_reach_cache.get("ok", False))
    if not has_llm_configured():
        _llm_reach_cache.update(ts=now, ok=False)
        return False
    try:
        model = get_chat_model()
        await asyncio.wait_for(
            asyncio.to_thread(model.invoke, "ping"), timeout=8.0
        )
        _llm_reach_cache.update(ts=now, ok=True)
        return True
    except Exception:
        _llm_reach_cache.update(ts=now, ok=False)
        return False


@health_router.get(
    "",
    summary="健康检查",
    description="检查 API 服务、MySQL 数据库连通性及 LLM 是否已配置。前端启动时可调用此接口探测后端状态。",
)
async def health():
    from app.rag.milvus_store import get_vector_store, InMemoryVectorStore

    store = get_vector_store()
    rag_count = store.count() if isinstance(store, InMemoryVectorStore) else -1
    return success_response(data={
        "status": "ok",
        "db": await check_db_connection(),
        "db_info": get_db_info(),
        "llm_configured": has_llm_configured(),
        "llm_reachable": await _check_llm_reachable(),
        "rag_available": rag_count > 0,
        "rag_doc_count": rag_count,
    })


@images_router.get(
    "/{job_id}/{code}",
    summary="获取生成任务图片",
    description="根据生成任务 ID 与图片编码（如 H1、M2）返回 PNG 文件。用于运营流水线产出图访问。",
    responses={200: {"description": "图片文件"}, 404: {"description": "图片不存在"}},
)
async def get_image(
    job_id: str = PathParam(..., description="生成任务 ID"),
    code: str = PathParam(..., description="图片编码，如 H1、H2、M1"),
):
    from app.utils.path_tool import GENERATED_DIR, safe_filename, safe_resolve_under

    if ".." in job_id or "/" in job_id or "\\" in job_id:
        return success_response(message="not found", data=None)

    safe_code = safe_filename(code, "image")
    path = safe_resolve_under(GENERATED_DIR, job_id, f"{safe_code}.png")
    if not path or not path.is_file():
        path = safe_resolve_under(GENERATED_DIR, job_id, safe_code)
    if path and path.is_file():
        return FileResponse(path)
    return success_response(message="not found", data=None)
