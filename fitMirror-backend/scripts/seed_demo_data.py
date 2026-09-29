"""
初始化演示数据：SKU 商品图 + 知识库文档
用法:
  cd fitMirror-backend && uv run python scripts/seed_demo_data.py
  cd fitMirror-backend && uv run python scripts/seed_demo_data.py --refresh-images
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal, init_db
from app.models.knowledge_doc import KnowledgeDoc
from app.models.sku import Sku
from app.services.image_similarity import compute_dhash
from app.services.knowledge_service import KnowledgeService
from app.services.sku_service import create_sku
from app.utils.path_tool import ensure_storage_dirs, normalize_stored_path, sku_upload_dir

SEED_DIR = BACKEND_ROOT / "seed"
SEED_IMG_DIR = SEED_DIR / "images"
KNOWLEDGE_MAP = [
    ("knowledge/faq_退换货政策.md", "faq"),
    ("knowledge/faq_尺码指南.md", "faq"),
    ("knowledge/script_客服话术.txt", "script"),
    ("knowledge/policy_发货物流.md", "policy"),
    ("knowledge/product_商品说明.md", "product"),
]

SKU_DEFS = [
    {
        "sku_code": "DRESS-001",
        "name": "法式碎花连衣裙",
        "category": "女装/连衣裙",
        "style": "清新 fresh natural",
        "color": "#F5D0D6",
        "accent": "#E8A0B0",
        "shape": "dress",
        "model_attrs": "亚洲女性, 25岁, 身高165cm, 体重55kg, 标准身材",
    },
    {
        "sku_code": "DRESS-002",
        "name": "简约黑色吊带裙",
        "category": "女装/连衣裙",
        "style": "简约 modern minimal",
        "color": "#1A1A1A",
        "accent": "#3D3D3D",
        "shape": "dress",
        "model_attrs": "亚洲女性, 25岁, 身高165cm, 体重55kg, 标准身材",
    },
    {
        "sku_code": "PANTS-001",
        "name": "高腰直筒牛仔裤",
        "category": "男装/裤装",
        "style": "街头 urban street",
        "color": "#3D5A80",
        "accent": "#5C7A9E",
        "shape": "pants",
        "model_attrs": "亚洲男性, 28岁, 身高175cm, 体重70kg, 标准身材",
    },
    {
        "sku_code": "TOP-001",
        "name": "针织开衫外套",
        "category": "女装/上衣",
        "style": "温馨 cozy warm",
        "color": "#C9A87C",
        "accent": "#E8D4B8",
        "shape": "top",
        "model_attrs": "亚洲女性, 25岁, 身高165cm, 体重55kg, 标准身材",
    },
    {
        "sku_code": "SPORT-001",
        "name": "运动休闲卫衣",
        "category": "运动/健身",
        "style": "运动 athletic",
        "color": "#4A7C59",
        "accent": "#6B9E78",
        "shape": "hoodie",
        "model_attrs": "亚洲女性, 22岁, 身高168cm, 体重58kg, 标准身材",
    },
    {
        "sku_code": "BAG-001",
        "name": "简约托特包",
        "category": "包袋/手袋",
        "style": "简约 modern minimal",
        "color": "#8B7355",
        "accent": "#A89070",
        "shape": "bag",
        "model_attrs": "亚洲女性, 25岁, 身高165cm, 体重55kg, 标准身材",
    },
]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _draw_dress(draw: ImageDraw.ImageDraw, cx: int, cy: int, main: tuple, accent: tuple):
    draw.polygon([(cx, cy - 80), (cx - 60, cy - 40), (cx - 90, cy + 120), (cx + 90, cy + 120), (cx + 60, cy - 40)], fill=main)
    draw.ellipse([cx - 35, cy - 100, cx + 35, cy - 50], fill=accent)
    for i in range(6):
        x = cx - 70 + i * 28
        draw.ellipse([x, cy + 10, x + 18, cy + 28], fill=accent)


def _draw_pants(draw: ImageDraw.ImageDraw, cx: int, cy: int, main: tuple, accent: tuple):
    draw.polygon([(cx - 70, cy - 60), (cx + 70, cy - 60), (cx + 55, cy + 130), (cx + 10, cy + 130), (cx, cy - 20), (cx - 10, cy + 130), (cx - 55, cy + 130)], fill=main)
    draw.rectangle([cx - 72, cy - 65, cx + 72, cy - 48], fill=accent)


def _draw_top(draw: ImageDraw.ImageDraw, cx: int, cy: int, main: tuple, accent: tuple):
    draw.rounded_rectangle([cx - 85, cy - 50, cx + 85, cy + 80], radius=20, fill=main)
    draw.rounded_rectangle([cx - 100, cy - 30, cx - 70, cy + 60], radius=12, fill=accent)
    draw.rounded_rectangle([cx + 70, cy - 30, cx + 100, cy + 60], radius=12, fill=accent)


def _draw_hoodie(draw: ImageDraw.ImageDraw, cx: int, cy: int, main: tuple, accent: tuple):
    draw.rounded_rectangle([cx - 90, cy - 40, cx + 90, cy + 90], radius=25, fill=main)
    draw.polygon([(cx - 40, cy - 40), (cx, cy - 90), (cx + 40, cy - 40)], fill=accent)
    draw.line([(cx - 90, cy + 10), (cx + 90, cy + 10)], fill=accent, width=4)


def _draw_bag(draw: ImageDraw.ImageDraw, cx: int, cy: int, main: tuple, accent: tuple):
    draw.rounded_rectangle([cx - 80, cy - 30, cx + 80, cy + 90], radius=15, fill=main)
    draw.arc([cx - 50, cy - 80, cx + 50, cy - 10], 180, 0, fill=accent, width=8)
    draw.rectangle([cx - 15, cy - 10, cx + 15, cy + 20], fill=accent)


SHAPES = {
    "dress": _draw_dress,
    "pants": _draw_pants,
    "top": _draw_top,
    "hoodie": _draw_hoodie,
    "bag": _draw_bag,
}


def make_product_image(item: dict) -> bytes:
    """生成电商白底商品平铺风格示意图"""
    w, h = 600, 600
    img = Image.new("RGB", (w, h), "#F8F8F8")
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, w - 20, h - 20], outline="#E8E8E8", width=2)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.ellipse([140, 480, 460, 540], fill=(0, 0, 0, 30))
    img = Image.alpha_composite(img.convert("RGBA"), shadow).convert("RGB")

    main = _hex_to_rgb(item["color"])
    accent = _hex_to_rgb(item["accent"])
    draw = ImageDraw.Draw(img)
    shape_fn = SHAPES.get(item["shape"], _draw_dress)
    shape_fn(draw, w // 2, h // 2 - 30, main, accent)

    draw.text((30, 30), item["sku_code"], fill="#999999")
    draw.text((30, h - 50), item["name"][:14], fill="#666666")

    img = img.filter(ImageFilter.SHARPEN)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def save_seed_images():
    SEED_IMG_DIR.mkdir(parents=True, exist_ok=True)
    for item in SKU_DEFS:
        path = SEED_IMG_DIR / f"{item['sku_code']}.png"
        path.write_bytes(make_product_image(item))
        print(f"  saved seed image {path.name}")


async def _apply_image_to_sku(db, sku: Sku, item: dict, img_bytes: bytes):
    upload_dir = sku_upload_dir(sku.id)
    image_path = upload_dir / f"{item['sku_code']}.png"
    image_path.write_bytes(img_bytes)
    sku.source_image_path = normalize_stored_path(image_path)
    sku.model_attrs = item.get("model_attrs", sku.model_attrs)
    meta = dict(sku.metadata_ or {})
    meta["image_hash"] = compute_dhash(image_bytes=img_bytes)
    meta["demo"] = True
    sku.metadata_ = meta
    if sku.status == "draft":
        sku.status = "ready"


async def seed_skus(db, refresh_images: bool = False) -> int:
    count = 0
    save_seed_images()
    for item in SKU_DEFS:
        img_bytes = make_product_image(item)
        existing = await db.execute(select(Sku).where(Sku.sku_code == item["sku_code"]))
        sku = existing.scalar_one_or_none()
        if sku:
            if refresh_images:
                await _apply_image_to_sku(db, sku, item, img_bytes)
                print(f"  ~ refresh image {item['sku_code']}")
                count += 1
            else:
                print(f"  skip SKU {item['sku_code']} (exists)")
            continue
        sku = await create_sku(
            db,
            sku_code=item["sku_code"],
            name=item["name"],
            category=item["category"],
            style=item["style"],
            platform="淘宝",
            language="中文",
            model_attrs=item.get("model_attrs", "亚洲女性, 25岁"),
            image_bytes=img_bytes,
            image_filename=f"{item['sku_code']}.png",
        )
        sku.status = "ready"
        print(f"  + SKU {item['sku_code']} -> {sku.id}")
        count += 1
    return count


async def seed_knowledge(db) -> int:
    svc = KnowledgeService(db)
    count = 0
    for rel_path, doc_type in KNOWLEDGE_MAP:
        path = SEED_DIR / rel_path
        if not path.exists():
            print(f"  skip knowledge {rel_path} (not found)")
            continue
        content = path.read_bytes()
        md5 = __import__("hashlib").md5(content).hexdigest()
        existing = await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.md5 == md5))
        if existing.scalar_one_or_none():
            print(f"  skip knowledge {path.name} (exists)")
            continue
        doc = await svc.upload_file(path.name, content, doc_type)
        print(f"  + knowledge [{doc_type}] {path.name} -> {doc.id} ({len(doc.milvus_ids)} chunks)")
        count += 1
    return count


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-images", action="store_true", help="刷新已有 SKU 商品图")
    args = parser.parse_args()

    print("=== fitMirror 演示数据初始化 ===")
    ensure_storage_dirs()
    await init_db()
    async with AsyncSessionLocal() as db:
        print("\n[1] SKU 商品...")
        sku_n = await seed_skus(db, refresh_images=args.refresh_images)
        print("\n[2] 知识库...")
        kb_n = await seed_knowledge(db)
        await db.commit()

    from app.rag.milvus_store import vector_count

    print(f"\n完成: 处理 SKU {sku_n} 个, 知识库 {kb_n} 个")
    print(f"向量索引条目: {vector_count()}")


if __name__ == "__main__":
    asyncio.run(main())
