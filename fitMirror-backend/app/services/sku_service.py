"""SKU 运营资料管理：负责建档、更新、落盘上传图，并初始化对应 workspace。"""
import hashlib
import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sku import GeneratedImage, Sku, SkuArtifact
from app.utils.path_tool import (
    normalize_stored_path,
    path_exists,
    resolve_storage_path,
    safe_filename,
    sku_upload_dir,
    sku_workspace_dir,
)


async def list_skus(db: AsyncSession, page: int = 1, size: int = 100) -> tuple[list[Sku], int]:
    """按创建时间倒序返回 SKU 列表，给后台运营页做分页展示。"""
    from sqlalchemy import func, select

    offset = (page - 1) * size
    total = (await db.execute(select(func.count()).select_from(Sku))).scalar_one()
    result = await db.execute(select(Sku).order_by(Sku.created_at.desc()).offset(offset).limit(size))
    items = list(result.scalars().all())
    return items, total


async def update_sku(
    db: AsyncSession,
    sku_id: str,
    *,
    sku_code: str | None = None,
    name: str | None = None,
    category: str | None = None,
    style: str | None = None,
    platform: str | None = None,
    language: str | None = None,
    model_attrs: str | None = None,
    additional_requirements: str | None = None,
    model_scene: str | None = None,
    shooting_style: str | None = None,
    face_visible: str | None = None,
    image_bytes: bytes | None = None,
    image_filename: str = "original.png",
) -> Sku | None:
    """更新 SKU 基础信息；若重新上传主图，会同步刷新文件路径和 image_hash。"""
    sku = await get_sku(db, sku_id)
    if not sku:
        return None
    if sku_code is not None:
        sku.sku_code = sku_code
    if name is not None:
        sku.name = name
    if category is not None:
        sku.category = category
    if style is not None:
        sku.style = style
    if platform is not None:
        sku.platform = platform
    if language is not None:
        sku.language = language
    if model_attrs is not None:
        sku.model_attrs = model_attrs
    if additional_requirements is not None:
        sku.additional_requirements = additional_requirements
    if model_scene is not None:
        sku.model_scene = model_scene
    if shooting_style is not None:
        sku.shooting_style = shooting_style
    if face_visible is not None:
        sku.face_visible = face_visible
    if image_bytes:
        upload_dir = sku_upload_dir(sku.id)
        image_path = upload_dir / safe_filename(image_filename, "original.png")
        image_path.write_bytes(image_bytes)
        sku.source_image_path = normalize_stored_path(image_path)
        try:
            from app.services.image_similarity import compute_dhash

            meta = dict(sku.metadata_ or {})
            meta["image_hash"] = compute_dhash(image_bytes=image_bytes)
            sku.metadata_ = meta
        except Exception:
            pass
    await db.flush()
    return sku


async def get_sku(db: AsyncSession, sku_id: str) -> Sku | None:
    """按主键读取 SKU，供编辑、详情页和后续流水线复用。"""
    return await db.get(Sku, sku_id)


async def create_sku(
    db: AsyncSession,
    *,
    sku_code: str,
    name: str = "",
    category: str = "",
    style: str = "",
    platform: str = "淘宝",
    language: str = "中文",
    model_attrs: str = "",
    additional_requirements: str = "",
    model_scene: str = "居家",
    shooting_style: str = "棚拍",
    face_visible: str = "show",
    image_bytes: bytes | None = None,
    image_filename: str = "original.png",
) -> Sku:
    """创建 SKU 并初始化运营工作区，保证后续分析/出图有独立落盘位置。"""
    sku = Sku(
        sku_code=sku_code,
        name=name or sku_code,
        category=category,
        style=style,
        platform=platform,
        language=language,
        model_attrs=model_attrs,
        additional_requirements=additional_requirements,
        model_scene=model_scene,
        shooting_style=shooting_style,
        face_visible=face_visible,
        status="draft",
    )
    db.add(sku)
    await db.flush()
    ws = sku_workspace_dir(sku.id)

    if image_bytes:
        upload_dir = sku_upload_dir(sku.id)
        image_path = upload_dir / safe_filename(image_filename, "original.png")
        image_path.write_bytes(image_bytes)
        sku.source_image_path = normalize_stored_path(image_path)
        try:
            from app.services.image_similarity import compute_dhash

            meta = {"workspace": normalize_stored_path(ws), "image_hash": compute_dhash(image_bytes=image_bytes)}
        except Exception:
            meta = {"workspace": normalize_stored_path(ws)}
        sku.metadata_ = meta
    else:
        sku.metadata_ = {"workspace": normalize_stored_path(ws)}
    await db.flush()
    return sku


async def save_artifact(db: AsyncSession, sku_id: str, stage: int, file_path: str) -> SkuArtifact:
    """把 Stage 产物登记到数据库，方便运营页回看每一步的中间结果。"""
    art = SkuArtifact(sku_id=sku_id, stage=stage, file_path=normalize_stored_path(file_path))
    db.add(art)
    await db.flush()
    return art


async def sku_to_dict(sku: Sku, artifacts: list[SkuArtifact] | None = None) -> dict:
    """把 ORM SKU 转成前端可直接消费的字典结构。"""
    return {
        "id": sku.id,
        "sku_code": sku.sku_code,
        "name": sku.name,
        "category": sku.category,
        "style": sku.style,
        "platform": sku.platform,
        "language": sku.language,
        "model_attrs": sku.model_attrs,
        "additional_requirements": sku.additional_requirements,
        "model_scene": sku.model_scene,
        "shooting_style": sku.shooting_style,
        "face_visible": sku.face_visible,
        "source_image_path": sku.source_image_path,
        "status": sku.status,
        "artifacts": [
            {"stage": a.stage, "file_path": a.file_path, "version": a.version}
            for a in (artifacts or [])
        ],
        "created_at": sku.created_at.isoformat() if sku.created_at else None,
    }
