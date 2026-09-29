"""读取 SKU workspace 产物（product/campaign/prompts/图片），并协调 DB 与文件系统状态。

workspace 目录结构（每个 SKU 独立）：
  product.json   — Stage1 产品分析
  campaign.json  — Stage2 营销策略
  prompts.json   — Stage3 提示词（H1-H5 / D1-D9 / M1-M5）
  *.png          — 出图产物

reconcile_job_status 负责修复后台任务中断后 DB 状态与 workspace 文件不一致的问题。
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sku import GeneratedImage, GenerationJob
from app.pipeline.json_utils import read_json
from app.pipeline.prompt_templates import get_modules_for_mode
from app.services.job_progress import get_job_progress
from app.utils.path_tool import STORAGE_ROOT, path_exists, resolve_storage_path, sku_workspace_dir


CAMPAIGN_LABELS = {
    "core_selling_point": "核心卖点",
    "pain_points": "痛点",
    "benefits": "利益点",
    "usage_scenarios": "使用场景",
    "steps": "使用步骤",
    "comparison_points": "对比点",
    "trust_elements": "信任元素",
}

PROMPT_ORDER = (
    [f"H{i}" for i in range(1, 6)]
    + [f"D{i}" for i in range(1, 10)]
    + [f"M{i}" for i in range(1, 6)]
)


def _safe_read(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def _png_exists(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def sync_workspace_images_to_job(workspace: Path, output_dir: Path, mode: str) -> list[str]:
    """将 workspace 已有 PNG 同步到 job 输出目录 (不触发重新生成)。"""
    import shutil

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for spec in get_modules_for_mode(mode):
        src = workspace / f"{spec.code}.png"
        if _png_exists(src):
            dest = output_dir / src.name
            shutil.copy2(src, dest)
            paths.append(str(dest))
    ref = workspace / "product_ref.png"
    if _png_exists(ref):
        dest = output_dir / ref.name
        shutil.copy2(ref, dest)
        if str(dest) not in paths:
            paths.append(str(dest))
    return paths


def compute_image_progress(ws: Path, mode: str, prompts: dict | None) -> dict:
    """根据 workspace 已有 PNG 计算图片生成进度（含 product_ref）。"""
    prompts = prompts if isinstance(prompts, dict) else {}
    # modules：当前出图模式（hero/detail/lookbook）应生成的图片模块列表
    modules = get_modules_for_mode(mode)
    # hero_codes：prompts.json 里已有提示词的模块编号，如 H1、M2
    hero_codes = [m.code for m in modules if m.code in prompts]

    # codes：本次任务期望产出的全部图片编号（含 product_ref 参考图）
    codes: list[str] = []
    if hero_codes:
        codes.append("product_ref")
    codes.extend(hero_codes)

    # done_codes：workspace 里已经生成好的 PNG 对应编号
    done_codes: list[str] = []
    for code in codes:
        p = ws / ("product_ref.png" if code == "product_ref" else f"{code}.png")
        if _png_exists(p):
            done_codes.append(code)

    total = len(codes)
    done = len(done_codes)
    return {
        "done": done,  # 已生成张数
        "total": total,  # 应生成总张数
        "codes": done_codes,  # 已完成的编号列表，运营台进度条可逐个勾选
        "complete": total > 0 and done >= total,  # 是否全部出完
        "percent": round(done / total * 100) if total else 0,
    }


async def get_workspace_bundle(db: AsyncSession, sku_id: str) -> dict:
    """聚合运营台所需的全部 workspace 数据，含产物 JSON、图片列表与任务状态。"""
    ws = sku_workspace_dir(sku_id)
    product = _safe_read(ws / "product.json")
    campaign = _safe_read(ws / "campaign.json")
    prompts = _safe_read(ws / "prompts.json")

    job_result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.sku_id == sku_id)
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    latest_job = job_result.scalar_one_or_none()
    if latest_job:
        await reconcile_job_status(db, sku_id, latest_job)

    img_result = await db.execute(
        select(GeneratedImage)
        .where(GeneratedImage.sku_id == sku_id)
        .order_by(GeneratedImage.created_at.desc())
    )
    images = _collect_db_images(img_result.scalars().all())
    if not images:
        images = _collect_workspace_images(ws, sku_id, latest_job.id if latest_job else None)

    prompt_list = []
    if isinstance(prompts, dict):
        for code in PROMPT_ORDER:
            if code not in prompts:
                continue
            item = prompts[code]
            if not isinstance(item, dict):
                continue
            text = item.get("prompt") or item.get("prompt_text") or ""
            prompt_list.append({
                "code": code,
                "objective": item.get("objective", ""),
                "size": item.get("size", ""),
                "prompt": text,
            })

    image_progress = compute_image_progress(
        ws,
        latest_job.mode if latest_job else "hero",
        prompts if isinstance(prompts, dict) else None,
    )

    return {
        "workspace": str(ws),  # 磁盘目录绝对路径，调试/运维用
        "product": product,  # Stage1 原始 JSON
        "product_name": (product or {}).get("product_name") if isinstance(product, dict) else None,
        "campaign": campaign,  # Stage2 原始 JSON
        "campaign_sections": _campaign_sections(campaign),  # 转成带中文 label 的列表，前端直接渲染
        "prompts": prompts,  # Stage3 原始 JSON，key 为 H1/D1/M1 等
        "prompt_list": prompt_list,  # prompts 的有序扁平列表，运营台表格展示用
        "images": images,  # 已生成图片 URL 列表，优先 DB，回退扫 workspace
        "image_progress": image_progress,  # 出图进度 {done, total, complete, ...}
        "latest_job": _job_dict(latest_job) if latest_job else None,
        "has_campaign": bool(campaign),  # 是否已完成 Stage2，控制「确认策略」按钮
        "has_prompts": bool(prompt_list),  # 是否已有提示词，控制进入出图阶段
        "has_images": image_progress.get("complete") or bool(images),
    }


def _campaign_sections(campaign: dict | list | None) -> list[dict]:
    if not isinstance(campaign, dict):
        return []
    sections = []
    for key, label in CAMPAIGN_LABELS.items():
        val = campaign.get(key)
        if val is None or val == "" or val == []:
            continue
        sections.append({"key": key, "label": label, "value": val})
    return sections


def _job_dict(job: GenerationJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "current_node": job.current_node,
        "mode": job.mode,
        "progress_json": job.progress_json or {},
    }


async def get_latest_job(db: AsyncSession, sku_id: str) -> GenerationJob | None:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.sku_id == sku_id)
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if not job:
        return None
    await reconcile_job_status(db, sku_id, job)
    return job


def _is_image_generation_stage(job: GenerationJob) -> bool:
    progress_json = job.progress_json or {}
    in_memory = get_job_progress(job.id)
    stages = {progress_json.get("stage"), in_memory.get("stage")}
    return job.current_node == "images" or bool(
        stages & {"images", "image_done", "images_partial"}
    )


async def reconcile_job_status(db: AsyncSession, sku_id: str, job: GenerationJob) -> None:
    """修复后台任务与 workspace 文件不一致的 job 状态。

    常见修复场景：
      - workspace 图片已全部生成但 DB 仍为 running/paused → done
      - DB 标记 done 但图片未齐 → paused + images_partial
      - running 但 campaign/prompts 文件已落盘 → paused 等待确认
    """
    ws = sku_workspace_dir(sku_id)
    has_campaign = (ws / "campaign.json").exists()
    has_prompts = (ws / "prompts.json").exists()
    prompts = _safe_read(ws / "prompts.json")
    image_progress = compute_image_progress(
        ws, job.mode, prompts if isinstance(prompts, dict) else None
    )

    if image_progress["complete"] and image_progress["total"] > 0:
        if job.status != "done" or job.current_node != "done":
            job.status = "done"
            job.current_node = "done"
            job.progress_json = {"stage": "done", **image_progress}
            await db.flush()
        return

    if (
        job.status == "paused"
        and job.current_node in ("campaign", "stage2")
        and has_prompts
        and not image_progress["complete"]
    ):
        job.current_node = "prompts"
        job.progress_json = {"stage": "prompts", "awaiting_confirm": "prompts"}
        await db.flush()
        return

    if job.status == "done" and image_progress["total"] > 0:
        if not image_progress["complete"]:
            job.status = "paused"
            job.current_node = "prompts"
            job.finished_at = None
            job.progress_json = {"stage": "images_partial", **image_progress}
            await db.flush()
        return

    if job.status == "paused" and job.current_node == "done" and image_progress["complete"]:
        job.status = "done"
        await db.flush()
        return

    if job.status != "running":
        return

    if _is_image_generation_stage(job):
        if image_progress["complete"]:
            job.status = "done"
            job.current_node = "done"
            job.progress_json = {"stage": "done", **image_progress}
            await db.flush()
        return

    if job.current_node in ("campaign", "stage2") and has_campaign:
        job.status = "paused"
        job.current_node = "campaign"
        job.progress_json = {"stage": "campaign", "awaiting_confirm": "campaign"}
        await db.flush()
    elif job.current_node in ("prompts", "stage3") and has_prompts:
        job.status = "paused"
        job.current_node = "prompts"
        job.progress_json = {"stage": "prompts", "awaiting_confirm": "prompts"}
        await db.flush()


def _collect_db_images(records) -> list[dict]:
    """从 GeneratedImage 表收集图片，优先使用 DB 记录（含 job 关联）。"""
    images = []
    seen_codes: set[str] = set()
    for img in records:
        if img.image_code in seen_codes:
            continue
        if path_exists(img.file_path):
            seen_codes.add(img.image_code)
            images.append({
                "id": img.id,
                "job_id": img.job_id,
                "code": img.image_code,
                "url": f"/api/images/{img.job_id}/{img.image_code}",
            })
    return images


def _collect_workspace_images(ws: Path, sku_id: str, job_id: str | None) -> list[dict]:
    """DB 无记录时回退扫描 workspace 目录下的 PNG 文件。"""
    images = []
    patterns = ["H*.png", "D*.png", "M*.png", "product_ref.png", "lookbook_ref.png"]
    seen = set()
    for pat in patterns:
        for p in sorted(ws.glob(pat)):
            if p.name in seen or not p.is_file():
                continue
            seen.add(p.name)
            try:
                rel = p.relative_to(STORAGE_ROOT).as_posix()
                url = f"/storage/{rel}"
            except ValueError:
                url = f"/storage/workspaces/{sku_id}/{p.name}"
            images.append({"id": p.stem, "job_id": job_id or "", "code": p.stem, "url": url})
    return images
