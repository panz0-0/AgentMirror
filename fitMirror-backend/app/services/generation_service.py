"""运营视觉生成任务编排：创建/恢复/暂停 Job，驱动 OpsGraphRunner。

任务状态机：pending → running → paused（人工确认）→ done / failed
暂停节点：campaign（营销策略）→ prompts（提示词）→ images（出图）

同一 SKU 通过 sku_generation_lock 保证同时仅有一个运行中任务。
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.ops_graph import ops_runner
from app.graph.state import FitMirrorState
from app.models.sku import GeneratedImage, GenerationJob, Sku
from app.services import sku_service
from app.services.job_progress import set_job_progress
from app.services.workspace_service import compute_image_progress
from app.utils.path_tool import job_output_dir, normalize_stored_path, sku_workspace_dir

_sku_locks: dict[str, asyncio.Lock] = {}
_sku_locks_guard = asyncio.Lock()


@asynccontextmanager
async def sku_generation_lock(sku_id: str):
    """按 SKU 粒度的 asyncio 锁，防止并发 start/resume 导致重复出图。"""
    async with _sku_locks_guard:
        if sku_id not in _sku_locks:
            _sku_locks[sku_id] = asyncio.Lock()
        lock = _sku_locks[sku_id]
    async with lock:
        yield


async def get_running_job_for_sku(db: AsyncSession, sku_id: str) -> GenerationJob | None:
    """取某个 SKU 当前仍在运行中的任务，用于避免重复启动同一条流水线。"""
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.sku_id == sku_id, GenerationJob.status == "running")
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_job(
    db: AsyncSession,
    sku_id: str,
    *,
    job_type: str = "ops",
    mode: str = "hero",
) -> GenerationJob:
    job = GenerationJob(
        sku_id=sku_id,
        job_type=job_type,
        mode=mode,
        status="pending",
        graph_thread_id=sku_id,
        progress_json={},
    )
    db.add(job)
    await db.flush()
    return job


async def run_ops_start(
    db: AsyncSession,
    job: GenerationJob,
    sku: Sku,
    stop_at: str = "campaign",
) -> GenerationJob:
    """首次启动流水线，执行 Stage1+Stage2 后在 stop_at 节点暂停等待确认。"""
    workspace = sku_workspace_dir(sku.id)
    state: FitMirrorState = {
        "thread_id": job.graph_thread_id,
        "sku_id": sku.id,
        "job_id": job.id,
        "generation_mode": job.mode,
        "stop_at_stage": 2,
    }
    job.status = "running"
    job.current_node = "stage1"
    set_job_progress(job.id, status="running", stage="start")

    result = await ops_runner.run_until_pause(state, sku, workspace, stop_at=stop_at)

    if result.get("product_json"):
        await sku_service.save_artifact(db, sku.id, 1, normalize_stored_path(workspace / "product.json"))
    if result.get("campaign_json"):
        await sku_service.save_artifact(db, sku.id, 2, normalize_stored_path(workspace / "campaign.json"))

    job.status = "paused"
    # current_node：运营台当前停在哪一步，决定 resume 时从哪继续
    job.current_node = result.get("awaiting_confirm") or "campaign"
    # progress_json：持久化到 DB 的进度快照；awaiting_confirm 与 current_node 通常一致
    job.progress_json = {"stage": job.current_node, "awaiting_confirm": job.current_node}
    sku.status = "analyzed"
    # awaiting_confirm：内存进度（SSE 用），告知前端正在等人工点「确认」
    set_job_progress(job.id, status="paused", awaiting_confirm=job.current_node)
    return job


async def run_ops_resume(
    db: AsyncSession,
    job: GenerationJob,
    sku: Sku,
    action: str,
) -> GenerationJob:
    """恢复暂停任务：confirm 进入下一阶段，regenerate 重新生成当前阶段。"""
    from app.pipeline.json_utils import read_json

    workspace = sku_workspace_dir(sku.id)
    state: FitMirrorState = {
        "thread_id": job.graph_thread_id,
        "sku_id": sku.id,
        "job_id": job.id,
        "generation_mode": job.mode,
        "product_json": read_json(workspace / "product.json") if (workspace / "product.json").exists() else None,
        "campaign_json": read_json(workspace / "campaign.json") if (workspace / "campaign.json").exists() else None,
        "prompts_json": read_json(workspace / "prompts.json") if (workspace / "prompts.json").exists() else None,
    }
    prompts_data = state.get("prompts_json")
    image_progress = compute_image_progress(workspace, job.mode, prompts_data)

    if action == "confirm" and job.current_node == "done" and image_progress["complete"]:
        job.status = "done"
        job.progress_json = {"stage": "done", **image_progress}
        set_job_progress(
            job.id,
            status="done",
            stage="done",
            done=image_progress["done"],
            total=image_progress["total"],
        )
        return job

    job.status = "running"
    set_job_progress(job.id, status="running")

    if job.current_node == "campaign" and action == "confirm":
        result = await ops_runner.resume_stage3(state, sku, workspace)
        await sku_service.save_artifact(db, sku.id, 3, normalize_stored_path(workspace / "prompts.json"))
        job.status = "paused"
        job.current_node = "prompts"
        job.progress_json = {"stage": "prompts", "prompts": bool(result.get("prompts_json"))}
        set_job_progress(job.id, status="paused", awaiting_confirm="prompts")
    elif job.current_node in ("prompts", "images") and action == "confirm":
        job.current_node = "images"
        job.progress_json = {"stage": "images", **image_progress}
        set_job_progress(
            job.id,
            status="running",
            stage="images",
            done=image_progress["done"],
            total=image_progress["total"],
        )

        output_dir = job_output_dir(job.id)
        from app.services.workspace_service import sync_workspace_images_to_job

        if image_progress["complete"]:
            paths = sync_workspace_images_to_job(workspace, output_dir, job.mode)
            result = {"generated_image_paths": paths}
        else:
            result = await ops_runner.resume_images(state, sku, workspace, output_dir)

        existing_job_result = await db.execute(
            select(GeneratedImage).where(GeneratedImage.job_id == job.id)
        )
        existing_codes = {img.image_code for img in existing_job_result.scalars().all()}

        # 将新生成的 PNG 写入 GeneratedImage，按 image_code 去重（job 级 + sku 级）
        for path in result.get("generated_image_paths") or []:
            p = Path(path)
            if not p.exists():
                continue
            code = p.stem if p.stem else f"IMG{len(existing_codes) + 1}"
            if code in existing_codes:
                continue
            sku_existing = await db.execute(
                select(GeneratedImage).where(
                    GeneratedImage.sku_id == sku.id,
                    GeneratedImage.image_code == code,
                )
            )
            if sku_existing.scalar_one_or_none():
                continue
            db.add(
                GeneratedImage(
                    job_id=job.id,
                    sku_id=sku.id,
                    image_code=code,
                    file_path=normalize_stored_path(p),
                )
            )
            existing_codes.add(code)

        image_progress = compute_image_progress(workspace, job.mode, prompts_data)
        if image_progress["complete"]:
            job.status = "done"
            job.current_node = "done"
            job.finished_at = datetime.utcnow()
            job.progress_json = {"stage": "done", **image_progress}
            sku.status = "generated"
            set_job_progress(
                job.id,
                status="done",
                stage="done",
                done=image_progress["done"],
                total=image_progress["total"],
            )
        else:
            job.status = "paused"
            job.current_node = "prompts"
            job.progress_json = {"stage": "images_partial", **image_progress}
            sku.status = "ready"
            set_job_progress(
                job.id,
                status="paused",
                stage="images_partial",
                done=image_progress["done"],
                total=image_progress["total"],
            )
    else:
        if job.current_node != "done":
            job.status = "paused"

    return job


async def ensure_paused_job(
    db: AsyncSession,
    sku_id: str,
    node: str,
    mode: str = "hero",
) -> GenerationJob:
    """运营台进入 SKU 时确保存在可轮询的暂停态 Job，必要时根据 workspace 文件修复状态。"""
    from app.services.workspace_service import get_latest_job, get_workspace_bundle

    bundle = await get_workspace_bundle(db, sku_id)
    ws = sku_workspace_dir(sku_id)
    prompts = bundle.get("prompts")
    image_progress = compute_image_progress(
        ws, mode, prompts if isinstance(prompts, dict) else None
    )

    job = await get_latest_job(db, sku_id)

    if node == "prompts" and image_progress["complete"] and job:
        job.status = "done"
        job.current_node = "done"
        job.progress_json = {"stage": "done", **image_progress}
        await db.flush()
        return job

    if job and job.status == "failed":
        if node == "campaign" and bundle["has_campaign"]:
            job.status = "paused"
            job.current_node = "campaign"
            job.error_msg = None
            await db.flush()
            return job
        if node == "prompts" and bundle["has_prompts"]:
            job.status = "paused"
            job.current_node = "prompts"
            job.error_msg = None
            await db.flush()
            return job

    if job and job.status == "done" and node == "prompts":
        if image_progress["complete"]:
            return job
        if image_progress["total"] > 0:
            job.status = "paused"
            job.current_node = "prompts"
            job.finished_at = None
            job.progress_json = {"stage": "images_partial", **image_progress}
            await db.flush()
            return job

    if job and image_progress["complete"] and node == "prompts":
        job.status = "done"
        job.current_node = "done"
        job.progress_json = {"stage": "done", **image_progress}
        await db.flush()
        return job

    if job and job.status == "running":
        if node == "prompts" and (
            job.current_node == "images"
            or (job.progress_json or {}).get("stage") in ("images", "image_done", "images_partial")
        ):
            return job

    if job and job.status == "paused" and job.current_node == node:
        return job

    if node == "campaign" and not bundle["has_campaign"]:
        raise ValueError("请先完成产品分析")
    if node == "prompts" and not bundle["has_prompts"]:
        raise ValueError("请先生成提示词")

    job = GenerationJob(
        sku_id=sku_id,
        job_type="ops",
        mode=mode,
        status="paused",
        current_node=node,
        graph_thread_id=sku_id,
        progress_json={"stage": node},
    )
    db.add(job)
    await db.flush()
    return job


def run_ops_background(coro_factory):
    """Fire-and-forget async task on default loop."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro_factory())
    except RuntimeError:
        asyncio.run(coro_factory())
