"""视觉生成 API：启动/恢复流水线、查询任务状态、SSE 进度推送。

后台任务通过 asyncio.create_task 在独立 DB Session 中执行，
避免与 HTTP 请求 Session 生命周期冲突。
"""
"""视觉生成 API：启动/恢复流水线、查询任务状态、SSE 进度推送。

后台任务通过 asyncio.create_task 在独立 DB Session 中执行，
避免与 HTTP 请求 Session 生命周期冲突。
"""
import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limit
from app.core.success_response import success_response
from app.db.db_config import AsyncSessionLocal, get_db
from app.models.sku import GenerationJob
from app.schemas.models import GenerationEnsureRequest, GenerationResumeRequest, GenerationStartRequest
from app.services import generation_service, sku_service
from app.services.job_progress import get_job_progress

generation_router = APIRouter(prefix="/api/generation", tags=["generation"])


@generation_router.post(
    "/start",
    summary="启动生成流水线",
    description=(
        "为指定 SKU 异步启动运营视觉生成流水线（Stage1 产品分析 → Stage2 营销策略 → "
        "Stage3 提示词 → 出图）。同一 SKU 同时仅允许一个运行中任务。"
        "通过 `stop_at` 控制首次暂停节点，等待运营人工确认。"
    ),
)
async def start_generation(body: GenerationStartRequest, db: AsyncSession = Depends(get_db)):
    sku = await sku_service.get_sku(db, body.sku_id)
    if not sku:
        return success_response(message="SKU not found", data=None)

    async with generation_service.sku_generation_lock(body.sku_id):
        running = await generation_service.get_running_job_for_sku(db, body.sku_id)
        if running:
            return success_response(
                message="该 SKU 已有进行中的生成任务",
                data={"job_id": running.id, "status": "running"},
            )
        job = await generation_service.create_job(db, body.sku_id, mode=body.mode)
        job.status = "running"
        await db.flush()
        await db.commit()
        job_id = job.id

    # 后台任务使用独立 Session，请求返回后流水线继续执行
    # 后台任务使用独立 Session，请求返回后流水线继续执行
    async def _run():
        try:
            async with AsyncSessionLocal() as session:
                j = await session.get(GenerationJob, job_id)
                s = await sku_service.get_sku(session, body.sku_id)
                if j and s:
                    await generation_service.run_ops_start(session, j, s, stop_at=body.stop_at)
                    await session.commit()
        except Exception as e:
            from app.core.logger_handler import logger
            from app.services.job_progress import set_job_progress
            logger.exception("Generation failed: %s", e)
            set_job_progress(job_id, status="failed", error=str(e))
            try:
                async with AsyncSessionLocal() as session:
                    j = await session.get(GenerationJob, job_id)
                    if j:
                        j.status = "failed"
                        j.error_msg = str(e)
                        await session.commit()
            except Exception:
                pass

    asyncio.create_task(_run())
    return success_response(data={"job_id": job_id, "status": "running"})


@generation_router.post(
    "/resume",
    summary="恢复暂停的生成任务",
    description=(
        "人工确认营销策略或提示词后，调用此接口继续下一阶段。"
        "`action=confirm` 继续执行，`action=regenerate` 重新生成当前阶段。"
    ),
)
async def resume_generation(body: GenerationResumeRequest, db: AsyncSession = Depends(get_db)):
    job = await db.get(GenerationJob, body.job_id)
    if not job:
        return success_response(message="job not found", data=None)

    async with generation_service.sku_generation_lock(job.sku_id):
        job = await db.get(GenerationJob, body.job_id)
        if not job:
            return success_response(message="job not found", data=None)
        if job.status == "running":
            return success_response(
                message="任务已在运行中",
                data={"job_id": job.id, "status": "running"},
            )
        other = await generation_service.get_running_job_for_sku(db, job.sku_id)
        if other and other.id != job.id:
            return success_response(
                message="该 SKU 已有其他进行中的生成任务",
                data={"job_id": other.id, "status": "running"},
            )
        job.status = "running"
        await db.flush()
        await db.commit()
        job_id = job.id
        sku_id = job.sku_id

    # 后台任务使用独立 Session，请求返回后流水线继续执行
    # 后台任务使用独立 Session，请求返回后流水线继续执行
    async def _run():
        try:
            async with AsyncSessionLocal() as session:
                j = await session.get(GenerationJob, job_id)
                s = await sku_service.get_sku(session, sku_id)
                if j and s:
                    await generation_service.run_ops_resume(session, j, s, body.action)
                    await session.commit()
        except Exception as e:
            from app.core.logger_handler import logger
            from app.services.job_progress import set_job_progress

            logger.exception("Generation resume failed: %s", e)
            set_job_progress(job_id, status="failed", error=str(e))
            try:
                async with AsyncSessionLocal() as session:
                    j = await session.get(GenerationJob, job_id)
                    if j:
                        j.status = "failed"
                        j.error_msg = str(e)
                        await session.commit()
            except Exception:
                pass

    asyncio.create_task(_run())
    return success_response(data={"job_id": job_id, "status": "running"})


@generation_router.post(
    "/ensure",
    summary="确保暂停态任务存在",
    description=(
        "运营台进入某 SKU 时调用：若尚无对应暂停任务则创建，"
        "保证前端可拿到 `job_id` 用于轮询或 SSE 订阅进度。"
    ),
)
async def ensure_generation_job(body: GenerationEnsureRequest, db: AsyncSession = Depends(get_db)):
    try:
        job = await generation_service.ensure_paused_job(db, body.sku_id, body.node, body.mode)
        await db.commit()
        return success_response(data={"job_id": job.id, "status": job.status, "current_node": job.current_node})
    except ValueError as e:
        return success_response(message=str(e), data=None)


@generation_router.get(
    "/sku/{sku_id}/latest",
    summary="SKU 最新生成任务",
    description="查询指定 SKU 最近一条生成任务的状态、进度与出图完成情况。",
)
async def get_latest_job(
    sku_id: Annotated[str, Path(description="SKU ID")],
    db: AsyncSession = Depends(get_db),
):
    from app.pipeline.json_utils import read_json
    from app.services.workspace_service import compute_image_progress, get_latest_job as _latest
    from app.utils.path_tool import sku_workspace_dir

    job = await _latest(db, sku_id)
    if not job:
        return success_response(data=None)
    progress = get_job_progress(job.id)
    ws = sku_workspace_dir(sku_id)
    prompts = read_json(ws / "prompts.json") if (ws / "prompts.json").exists() else {}
    image_progress = compute_image_progress(ws, job.mode, prompts if isinstance(prompts, dict) else None)
    progress["image_progress"] = image_progress
    if image_progress.get("total"):
        progress["done"] = image_progress["done"]
        progress["total"] = image_progress["total"]
    return success_response(data={
        "id": job.id,
        "job_id": job.id,
        "sku_id": job.sku_id,
        "status": job.status,
        "current_node": job.current_node,
        "mode": job.mode,
        "progress": progress,
        "progress_json": job.progress_json or {},
        "error_msg": job.error_msg,
        "image_progress": image_progress,
    })


@generation_router.get(
    "/{job_id}",
    summary="查询生成任务详情",
    description="按任务 ID 查询状态、当前节点、进度 JSON 与图片生成进度。",
)
async def get_job(
    job_id: Annotated[str, Path(description="生成任务 ID")],
    db: AsyncSession = Depends(get_db),
):
    from app.pipeline.json_utils import read_json
    from app.services.workspace_service import compute_image_progress
    from app.utils.path_tool import sku_workspace_dir

    job = await db.get(GenerationJob, job_id)
    if not job:
        return success_response(message="not found", data=None)
    progress = get_job_progress(job_id)
    ws = sku_workspace_dir(job.sku_id)
    prompts = read_json(ws / "prompts.json") if (ws / "prompts.json").exists() else {}
    image_progress = compute_image_progress(ws, job.mode, prompts if isinstance(prompts, dict) else None)
    progress["image_progress"] = image_progress
    if image_progress.get("total"):
        progress["done"] = image_progress["done"]
        progress["total"] = image_progress["total"]
    return success_response(data={
        "id": job.id,
        "job_id": job.id,
        "sku_id": job.sku_id,
        "status": job.status,
        "current_node": job.current_node,
        "mode": job.mode,
        "progress": progress,
        "progress_json": job.progress_json or {},
        "error_msg": job.error_msg,
        "image_progress": image_progress,
    })


@generation_router.get(
    "/{job_id}/stream",
    summary="任务进度 SSE 流",
    description=(
        "以 Server-Sent Events 每秒推送任务进度，直到状态为 done / paused / failed。"
        "运营台出图阶段用于实时更新进度条。"
    ),
    responses={200: {"description": "text/event-stream 进度事件流"}},
)
async def stream_job(
    job_id: Annotated[str, Path(description="生成任务 ID")],
):
    async def event_gen():
        for _ in range(120):
            p = get_job_progress(job_id)
            yield f"data: {json.dumps(p, ensure_ascii=False)}\n\n"
            if p.get("status") in ("done", "paused", "failed"):
                break
            await asyncio.sleep(1)
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
