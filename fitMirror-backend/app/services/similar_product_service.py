"""用户发图找店内相似款：先尽量命中“像这件”的业务意图，再给出可解释的店内推荐。"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Any

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sku import Sku
from app.services.catalog_service import build_catalog
from app.services.image_similarity import compute_dhash, find_top_matches
from app.utils.factory import has_llm_configured
from app.utils.path_tool import resolve_storage_path

SIMILAR_INTENT_KW = (
    "类似", "相似", "同款", "像这件", "像这条", "有像", "差不多的",
    "差不多", "类似的", "同款有", "有没有像", "有没有类似", "有同款",
    "找类似", "类似的款", "相似款", "相近",
)

FLORAL_HINTS = ("碎花", "印花", "法式", "度假", "田园", "floral")
DARK_HINTS = ("黑色", "黑裙", "吊带", "简约黑")
LIGHT_AVG_RGB = 175


def wants_similar_match(text: str) -> bool:
    """判断用户是不是在找“类似款/同款”，而不是精确询问某一件商品。"""
    t = (text or "").strip()
    if not t:
        return False
    return any(k in t for k in SIMILAR_INTENT_KW)


def encode_image_bytes(image_bytes: bytes, mime: str = "image/png") -> str:
    """把本地图片转成可喂给多模态模型的 data URL。"""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _image_lightness(image_bytes: bytes) -> float:
    """计算图片的平均亮度，用来粗略判断偏浅色还是偏深色。"""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((128, 128))
    px = list(img.getdata())
    if not px:
        return 128.0
    return sum(sum(p) / 3 for p in px) / len(px)


def _heuristic_pick(catalog_items: list[dict], image_bytes: bytes, ranked: list[dict]) -> dict | None:
    """无视觉模型时，结合 dHash 排序与商品文案/明暗启发式挑一个最像的款。"""
    if not ranked:
        return None

    lightness = _image_lightness(image_bytes)
    scores: list[tuple[float, dict]] = []

    for item in catalog_items:
        sku_code = item.get("sku_code") or ""
        name = item.get("name") or ""
        category = item.get("category") or ""
        style = item.get("style") or ""
        blob = f"{name} {category} {style}"

        dhash_item = next((r for r in ranked if r.get("sku_code") == sku_code), None)
        dist = dhash_item["distance"] if dhash_item else 64
        score = max(0, 50 - dist)

        if lightness >= LIGHT_AVG_RGB and any(h in blob for h in FLORAL_HINTS):
            score += 28
        if lightness < LIGHT_AVG_RGB and any(h in blob for h in DARK_HINTS):
            score += 22
        if "连衣裙" in blob and lightness >= LIGHT_AVG_RGB:
            score += 8
        if "开衫" in blob or "上衣" in category:
            score -= 6

        scores.append((score, item))

    scores.sort(key=lambda x: -x[0])
    best_score, best = scores[0]
    if best_score < 18:
        return None

    dhash_item = next((r for r in ranked if r.get("id") == best.get("id")), None)
    return {
        "sku_code": best.get("sku_code"),
        "id": best.get("id"),
        "similarity": min(0.82, best_score / 50),
        "reason": _guess_reason(best, lightness),
        "distance": dhash_item.get("distance") if dhash_item else None,
        "method": "heuristic",
    }


def _guess_reason(item: dict, lightness: float) -> str:
    """根据商品风格和图片亮度，生成一条可读的推荐理由。"""
    name = item.get("name") or item.get("sku_code") or "这款"
    category = item.get("category") or ""
    if any(h in f"{name} {category}" for h in FLORAL_HINTS) and lightness >= LIGHT_AVG_RGB:
        return "同为浅色碎花连衣裙风格，版型清新显瘦"
    if "连衣裙" in category:
        return "同为连衣裙品类，整体穿搭场景接近"
    return "款式风格与您的参考图较为接近"


def _vision_match_similar(
    image_bytes: bytes,
    catalog_items: list[dict],
    sku_records: dict[str, Sku],
) -> dict | None:
    """调用视觉模型做“找相似款”决策，适合用户明确发图比款的场景。"""
    from app.pipeline.client import build_vision_client, call_json_model
    from app.pipeline.config import load_config
    from app.pipeline.image_utils import encode_image

    cfg = load_config()
    if not cfg.vision_api_key:
        return None

    client = build_vision_client(cfg)
    user_ref = encode_image_bytes(image_bytes)

    lines = ["店铺在售商品（请从中挑选与用户图片款式最相似的一款）："]
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "用户发来一张衣服参考图（见下图1）。请判断店内哪一款商品在品类、版型、"
                "图案/颜色、风格上最相似。若完全不像任何一款，similarity 请填 0。\n"
                "只输出 JSON："
                '{"sku_code":"货号或空字符串","similarity":0.0,"reason":"一句话说明相似点"}\n\n'
                + "\n".join(lines)
            ),
        },
        {"type": "image_url", "image_url": {"url": user_ref}},
    ]

    idx = 2
    for item in catalog_items[:8]:
        sku = sku_records.get(item["id"])
        if not sku:
            continue
        path = resolve_storage_path(sku.source_image_path)
        if not path or not path.exists():
            continue
        code = item.get("sku_code") or ""
        name = item.get("name") or code
        cat = item.get("category") or ""
        style = item.get("style") or ""
        content.append({
            "type": "text",
            "text": f"图{idx} = {code} {name}（{cat}，风格：{style or '未标注'}）",
        })
        content.append({"type": "image_url", "image_url": {"url": encode_image(str(path))}})
        idx += 1

    messages = [
        {
            "role": "system",
            "content": (
                "你是电商导购视觉专家。根据用户参考图，从店铺商品中找最相似的一款。"
                "关注：连衣裙/上衣/裤装品类、碎花/纯色、收腰/宽松、色系明暗。"
                "不要臆造不存在的货号。"
            ),
        },
        {"role": "user", "content": content},
    ]

    try:
        data = call_json_model(
            client,
            cfg,
            cfg.vision_model,
            messages,
            desc="similar product match",
        )
    except Exception:
        return None

    code = (data.get("sku_code") or "").strip()
    similarity = float(data.get("similarity") or 0)
    reason = (data.get("reason") or "").strip()
    if not code or similarity < 0.45:
        return None

    item = next((i for i in catalog_items if i.get("sku_code") == code), None)
    if not item:
        m = re.search(r"[A-Z]+-\d+", code.upper())
        if m:
            code = m.group(0)
            item = next((i for i in catalog_items if i.get("sku_code") == code), None)
    if not item:
        return None

    return {
        "sku_code": item.get("sku_code"),
        "id": item.get("id"),
        "similarity": similarity,
        "reason": reason or _guess_reason(item, _image_lightness(image_bytes)),
        "method": "vision",
    }


async def find_similar_product(db: AsyncSession, image_bytes: bytes) -> dict | None:
    """为发图咨询返回店内最像的商品，视觉模型失败时自动退回启发式排序。"""
    catalog = await build_catalog(db)
    items = catalog.get("items") or []
    if not items:
        return None

    sku_records: dict[str, Sku] = {}
    for item in items:
        sku = await db.get(Sku, item["id"])
        if sku:
            sku_records[item["id"]] = sku

    if has_llm_configured():
        vision_hit = await asyncio.to_thread(
            _vision_match_similar, image_bytes, items, sku_records
        )
        if vision_hit:
            return vision_hit

    query_hash = compute_dhash(image_bytes=image_bytes)
    ranked = find_top_matches(query_hash, catalog.get("hash_index") or [], top_k=5, max_distance=45)
    return _heuristic_pick(items, image_bytes, ranked)
