"""知识库管理 API：文档上传、列表、预览、删除与向量库统计。"""
"""知识库管理 API：文档上传、列表、预览、删除与向量库统计。"""
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path as PathParam, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failed_response import AppException
from app.core.rate_limit import rate_limit
from app.core.success_response import success_response
from app.db.db_config import get_db
from app.rag.milvus_store import vector_count
from app.services.knowledge_service import DOC_TYPES, KnowledgeService

knowledge_router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def get_knowledge_service(db: AsyncSession = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(db)


@knowledge_router.get(
    "/types",
    summary="文档类型列表",
    description="返回知识库支持的文档类型：FAQ、话术、政策、商品说明。",
)
async def knowledge_types():
    return success_response(data=[
        {"value": "all", "label": "全部"},
        {"value": "faq", "label": "FAQ"},
        {"value": "script", "label": "话术"},
        {"value": "policy", "label": "政策"},
        {"value": "product", "label": "商品说明"},
    ])


@knowledge_router.get(
    "/list",
    summary="知识库文档列表",
    description="按类型筛选已上传文档，返回向量库条目总数。",
)
async def list_knowledge(
    doc_type: Annotated[str, Query(description="文档类型：all / faq / script / policy / product")] = "all",
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    docs = await svc.list_docs(None if doc_type == "all" else doc_type)
    return success_response(data={
        "items": [svc.doc_to_dict(d) for d in docs],
        "total": len(docs),
        "vector_count": vector_count(),
        "filter": doc_type,
    })


@knowledge_router.get(
    "/{doc_id}/preview",
    summary="预览文档内容",
    description="在线预览知识库文档正文（解析后的文本/Markdown）。",
)
async def preview_knowledge(
    doc_id: Annotated[str, PathParam(description="文档 ID")],
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    try:
        data = await svc.get_preview(doc_id)
        return success_response(data=data)
    except ValueError as e:
        raise AppException(str(e), 404)


@knowledge_router.get(
    "/{doc_id}/download",
    summary="下载原始文件",
    description="下载知识库文档的原始上传文件。",
    responses={200: {"description": "原始文件"}, 404: {"description": "文档不存在"}},
)
async def download_knowledge(
    doc_id: Annotated[str, PathParam(description="文档 ID")],
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    doc = await svc.get_doc(doc_id)
    if not doc:
        raise AppException("文件不存在", 404)
    from app.utils.path_tool import resolve_storage_path

    path = resolve_storage_path(doc.file_path)
    if not path or not path.exists():
        raise AppException("文件不存在", 404)
    return FileResponse(path, filename=doc.title)


@knowledge_router.post(
    "/upload",
    summary="上传知识库文档",
    description=(
        "上传 txt / md / pdf / docx 文档，自动解析分块并写入向量索引。"
        "上传后 AI 客服 FAQ 路径可检索到相关内容。限流：5 次/分钟。"
    ),
)
async def upload_knowledge(
    file: UploadFile = File(..., description="文档文件"),
    doc_type: Annotated[str, Form(description="文档类型：faq / script / policy / product")] = "faq",
    svc: KnowledgeService = Depends(get_knowledge_service),
    _: None = rate_limit(5, 60),
):
    content = await file.read()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".txt", ".md", ".markdown", ".pdf", ".docx", ".doc"):
        raise AppException("仅支持 txt / md / pdf / docx 格式", 400)
    try:
        doc = await svc.upload_file(file.filename, content, doc_type)
    except ValueError as e:
        raise AppException(str(e), 400)
    return success_response(data=svc.doc_to_dict(doc))


@knowledge_router.delete(
    "/{doc_id}",
    summary="删除知识库文档",
    description="删除文档文件及对应向量索引条目。",
)
async def delete_knowledge(
    doc_id: Annotated[str, PathParam(description="文档 ID")],
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    ok = await svc.delete_doc(doc_id)
    if not ok:
        raise AppException("文档不存在", 404)
    return success_response(message="已删除文档及向量", data={"vector_count": vector_count()})
