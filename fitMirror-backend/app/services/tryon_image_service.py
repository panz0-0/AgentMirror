"""虚拟试穿图片选取：从已生成图中挑出最适合「上身效果」展示的 PNG。

图片编号含义（与运营流水线 prompts.json 一致）：
  H1-H5  商品主图（H3 常为模特上身）
  D1-D9  细节/场景图（D5/D6 偏穿着场景）
  M1-M5  套图模特上身

客服试穿回复优先展示 MODEL_TRYON_CODES 中的图，没有则回退 H 主图。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sku import GeneratedImage
from app.utils.path_tool import normalize_stored_path, path_exists, sku_workspace_dir, storage_url

# 试穿图挑选顺序：越靠前越优先；H3/M 系列最适合展示上身效果
TRYON_IMAGE_PRIORITY: tuple[str, ...] = (
    "H3",
    "M1", "M2", "M3", "M4", "M5",
    "D5", "D6",
    "H1", "H2", "H5",
)

# 视为「真正模特上身/穿着场景」的编号；有则客服文案说「模特上身效果图」
MODEL_TRYON_CODES: frozenset[str] = frozenset({"H3", "M1", "M2", "M3", "M4", "M5", "D5", "D6"})


@dataclass
class TryonImageRef:
    """单张试穿候选图的引用，统一 DB 记录与 workspace 文件两种来源。"""
    sku_id: str
    image_code: str  # 如 H3、M2，对应 {code}.png 文件名
    file_path: str  # 相对存储路径，用于拼 /storage/... URL
    job_id: str | None = None  # 来自 generated_images 表时有值，用于 /api/images/{job_id}/{code}

    @property
    def is_model_shot(self) -> bool:
        """是否为模特上身类图片（非纯商品平铺主图）。"""
        return self.image_code in MODEL_TRYON_CODES

    def to_url(self) -> str | None:
        """转为前端可访问的 URL，按 file_path → job API → SKU API 依次尝试。"""
        url = storage_url(self.file_path)
        if url:
            return url
        if self.job_id:
            return f"/api/images/{self.job_id}/{self.image_code}"
        return f"/api/sku/{self.sku_id}/tryon-image?code={self.image_code}"


def _from_generated(sku_id: str, img: GeneratedImage) -> TryonImageRef:
    """把 generated_images 表一行转成统一的 TryonImageRef。"""
    return TryonImageRef(
        sku_id=sku_id,
        image_code=img.image_code,
        file_path=img.file_path,
        job_id=img.job_id,
    )


async def collect_tryon_candidates(db: AsyncSession, sku_id: str) -> list[TryonImageRef]:
    """收集某 SKU 所有可用的试穿候选图，按 TRYON_IMAGE_PRIORITY 排序返回。"""
    # 先从 DB 读已入库的生成图（出图任务完成后会写入 generated_images）
    result = await db.execute(select(GeneratedImage).where(GeneratedImage.sku_id == sku_id))
    by_code: dict[str, TryonImageRef] = {}
    for img in result.scalars().all():
        if not path_exists(img.file_path):
            continue
        # 同一 image_code 只保留一条（避免重复 job 产生多条记录）
        if img.image_code not in by_code:
            by_code[img.image_code] = _from_generated(sku_id, img)

    # DB 没有时回退扫 workspace 目录（运营台出图落盘但尚未同步 DB 的情况）
    ws = sku_workspace_dir(sku_id)
    for code in TRYON_IMAGE_PRIORITY:
        if code in by_code:
            continue
        p = ws / f"{code}.png"
        if path_exists(p):
            by_code[code] = TryonImageRef(
                sku_id=sku_id,
                image_code=code,
                file_path=normalize_stored_path(p),
                job_id=None,  # workspace 来源无 job_id，URL 走 storage 或 sku API
            )

    # 按优先级重排，保证 H3 排在 H1 前面
    ordered: list[TryonImageRef] = []
    for code in TRYON_IMAGE_PRIORITY:
        if code in by_code:
            ordered.append(by_code[code])
    return ordered


async def get_best_tryon_image(db: AsyncSession, sku_id: str) -> TryonImageRef | None:
    """取单张最适合试穿的图：优先模特上身，否则用排序第一的任意候选。"""
    candidates = await collect_tryon_candidates(db, sku_id)
    if not candidates:
        return None
    model_shots = [c for c in candidates if c.is_model_shot]
    return model_shots[0] if model_shots else candidates[0]


async def get_tryon_gallery(db: AsyncSession, sku_id: str) -> list[TryonImageRef]:
    """取试穿画廊列表：有模特图则全部模特图，否则只返回优先级最高的一张主图。"""
    candidates = await collect_tryon_candidates(db, sku_id)
    model_shots = [c for c in candidates if c.is_model_shot]
    # 画廊不要混入纯商品主图，除非完全没有模特类图片
    return model_shots or candidates[:1]


def build_tryon_metadata(sku_id: str, name: str, body: dict, refs: list[TryonImageRef]) -> dict:
    """组装客服试穿回复的 metadata，供前端渲染画廊与操作按钮。"""
    primary = refs[0]  # 第一张作为封面
    gallery = [u for ref in refs if (u := ref.to_url())]
    return {
        "type": "tryon_result",  # 前端据此渲染试穿结果卡片
        "sku_id": sku_id,
        "sku_name": name,
        "image_url": primary.to_url(),  # 主图 URL
        "image_code": primary.image_code,  # 如 H3，便于调试
        "gallery_urls": gallery,  # 多图轮播
        "is_model_shot": primary.is_model_shot,  # 决定文案是「模特上身」还是「主图参考」
        "body": body,  # {height_cm, weight_kg, is_default} 展示参考身材
        "actions": [
            {"type": "message", "label": "换一件看看", "text": "店里还有什么推荐？"},
        ],
    }
