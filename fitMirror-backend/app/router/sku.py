"""SKU 管理 API：创建/更新/删除、源图上传、workspace 产物与试穿图访问。"""
"""SKU 管理 API：创建/更新/删除、源图上传、workspace 产物与试穿图访问。"""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limit
from app.core.success_response import success_response
from app.db.db_config import get_db
from app.models.sku import SkuArtifact
from app.services import sku_service

sku_router = APIRouter(prefix="/api/sku", tags=["sku"])


@sku_router.get(
    "",
    summary="SKU 列表",
    description="分页查询全部 SKU，含流水线状态、产物数量与图片 URL。",
)
async def list_skus(
    page: Annotated[int, Query(description="页码，从 1 开始", ge=1)] = 1,
    size: Annotated[int, Query(description="每页条数，最大 500", ge=1, le=500)] = 200,
    db: AsyncSession = Depends(get_db),
):
    size = min(max(1, size), 500)
    items, total = await sku_service.list_skus(db, page, size)
    data = []
    for sku in items:
        arts = (
            await db.execute(select(SkuArtifact).where(SkuArtifact.sku_id == sku.id))
        ).scalars().all()
        data.append(await sku_service.sku_to_dict(sku, list(arts)))
    return success_response(data={"items": data, "total": total})


@sku_router.get(
    "/{sku_id}/workspace",
    summary="SKU 工作区数据",
    description=(
        "返回运营流水线 workspace 聚合数据：product.json、campaign.json、"
        "prompts.json、生成进度、已产出图片列表等。"
    ),
)
async def get_sku_workspace(
    sku_id: Annotated[str, Path(description="SKU ID")],
    db: AsyncSession = Depends(get_db),
):
    from app.services.workspace_service import get_workspace_bundle

    sku = await sku_service.get_sku(db, sku_id)
    if not sku:
        return success_response(message="SKU not found", data=None)
    data = await get_workspace_bundle(db, sku_id)
    return success_response(data=data)


@sku_router.get(
    "/{sku_id}/tryon-image",
    summary="试穿效果图",
    description="返回 SKU 虚拟试穿效果图 PNG。可指定 `code`（如 M1）或自动选取最佳一张。",
    responses={200: {"description": "PNG 图片"}, 404: {"description": "无可用试穿图"}},
)
async def get_sku_tryon_image(
    sku_id: Annotated[str, Path(description="SKU ID")],
    code: Annotated[str | None, Query(description="图片编码，如 M1；留空则自动选最佳")] = None,
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import FileResponse

    from app.services.tryon_image_service import collect_tryon_candidates, get_best_tryon_image
    from app.utils.path_tool import resolve_storage_path

    if code:
        candidates = await collect_tryon_candidates(db, sku_id)
        ref = next((c for c in candidates if c.image_code == code), None)
    else:
        ref = await get_best_tryon_image(db, sku_id)

    if not ref:
        return success_response(message="not found", data=None)

    path = resolve_storage_path(ref.file_path)
    if not path or not path.exists():
        return success_response(message="not found", data=None)
    return FileResponse(path)


@sku_router.get(
    "/{sku_id}/image",
    summary="商品原图",
    description="返回 SKU 上传的原始商品图 PNG/JPG 文件。",
    responses={200: {"description": "图片文件"}, 404: {"description": "SKU 或图片不存在"}},
)
async def get_sku_image(
    sku_id: Annotated[str, Path(description="SKU ID")],
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import FileResponse

    sku = await sku_service.get_sku(db, sku_id)
    if not sku or not sku.source_image_path:
        return success_response(message="not found", data=None)
    from app.utils.path_tool import resolve_storage_path

    path = resolve_storage_path(sku.source_image_path)
    if not path or not path.exists():
        return success_response(message="not found", data=None)
    return FileResponse(path)


@sku_router.get(
    "/{sku_id}",
    summary="SKU 详情",
    description="查询单个 SKU 完整信息，含元数据、流水线产物与状态。",
)
async def get_sku(
    sku_id: Annotated[str, Path(description="SKU ID")],
    db: AsyncSession = Depends(get_db),
):
    sku = await sku_service.get_sku(db, sku_id)
    if not sku:
        return success_response(message="SKU not found", data=None)
    arts = (await db.execute(select(SkuArtifact).where(SkuArtifact.sku_id == sku_id))).scalars().all()
    return success_response(data=await sku_service.sku_to_dict(sku, list(arts)))


@sku_router.post(
    "",
    summary="创建 SKU",
    description="新建商品 SKU，可上传商品原图。限流：10 次/分钟。",
)
async def create_sku(
    sku_code: Annotated[str, Form(description="货号，全局唯一，如 DRESS-001")],
    name: Annotated[str, Form(description="商品名称")] = "",
    category: Annotated[str, Form(description="类目，如 女装/连衣裙")] = "",
    style: Annotated[str, Form(description="风格标签")] = "",
    platform: Annotated[str, Form(description="目标平台")] = "淘宝",
    language: Annotated[str, Form(description="文案语言")] = "中文",
    model_attrs: Annotated[str, Form(description="模特参考信息，如身高体重")] = "",
    model_scene: Annotated[str, Form(description="拍摄场景")] = "居家",
    shooting_style: Annotated[str, Form(description="拍摄风格")] = "棚拍",
    face_visible: Annotated[str, Form(description="是否露脸：show / hide")] = "show",
    additional_requirements: Annotated[str, Form(description="额外生成要求")] = "",
    image: UploadFile | None = File(None, description="商品原图"),
    db: AsyncSession = Depends(get_db),
    _: None = rate_limit(10, 60),
):
    image_bytes = await image.read() if image else None
    sku = await sku_service.create_sku(
        db,
        sku_code=sku_code,
        name=name,
        category=category,
        style=style,
        platform=platform,
        language=language,
        model_attrs=model_attrs,
        model_scene=model_scene,
        shooting_style=shooting_style,
        face_visible=face_visible,
        additional_requirements=additional_requirements,
        image_bytes=image_bytes,
        image_filename=image.filename if image else "original.png",
    )
    return success_response(data={"id": sku.id, "sku_code": sku.sku_code})


@sku_router.put(
    "/{sku_id}",
    summary="更新 SKU",
    description="更新 SKU 字段，可选替换商品原图。限流：10 次/分钟。",
)
async def update_sku(
    sku_id: Annotated[str, Path(description="SKU ID")],
    sku_code: Annotated[str, Form(description="货号")] = "",
    name: Annotated[str, Form(description="商品名称")] = "",
    category: Annotated[str, Form(description="类目")] = "",
    style: Annotated[str, Form(description="风格")] = "",
    platform: Annotated[str, Form(description="平台")] = "",
    language: Annotated[str, Form(description="语言")] = "",
    model_attrs: Annotated[str, Form(description="模特信息")] = "",
    model_scene: Annotated[str, Form(description="场景")] = "",
    shooting_style: Annotated[str, Form(description="拍摄风格")] = "",
    face_visible: Annotated[str, Form(description="露脸设置")] = "",
    additional_requirements: Annotated[str, Form(description="额外要求")] = "",
    image: UploadFile | None = File(None, description="新商品图（可选）"),
    db: AsyncSession = Depends(get_db),
    _: None = rate_limit(10, 60),
):
    image_bytes = await image.read() if image else None
    sku = await sku_service.update_sku(
        db,
        sku_id,
        sku_code=sku_code or None,
        name=name or None,
        category=category or None,
        style=style or None,
        platform=platform or None,
        language=language or None,
        model_attrs=model_attrs or None,
        model_scene=model_scene or None,
        shooting_style=shooting_style or None,
        face_visible=face_visible or None,
        additional_requirements=additional_requirements or None,
        image_bytes=image_bytes,
        image_filename=image.filename if image else "original.png",
    )
    if not sku:
        return success_response(message="SKU not found", data=None)
    return success_response(data={"id": sku.id, "sku_code": sku.sku_code})
