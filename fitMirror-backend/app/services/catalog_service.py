"""商品目录与发图识货：构建分组目录、维护 dHash 索引、图片匹配 SKU。"""
from collections import defaultdict
from app.utils.path_tool import path_exists, resolve_storage_path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sku import Sku
from app.services.image_similarity import compute_dhash


def _image_url(sku_id: str) -> str:
    """生成 SKU 主图的对外访问地址。"""
    return f"/api/sku/{sku_id}/image"


async def ensure_sku_hash(db: AsyncSession, sku: Sku) -> str | None:
    """为 SKU 补齐并缓存 dHash，供后续发图识货时比对。"""
    # sku.metadata_：Sku 表的 JSON 扩展字段（ORM 名 metadata_，库列名 metadata）
    # 用来存不常查、但跟商品绑定的辅助信息；这里主要缓存 image_hash，避免每次建目录都重算
    meta = dict(sku.metadata_ or {})
    # 上传源图时 sku_service 会写入 image_hash；有缓存直接返回，不用再读磁盘算哈希
    if meta.get("image_hash"):
        return meta["image_hash"]

    # sku.source_image_path：运营上传的商品主图，DB 里是相对路径（如 storage/uploads/{sku_id}/original.png）
    # resolve_storage_path：把相对路径转成服务器上的绝对 Path，并兼容历史绝对路径
    path = resolve_storage_path(sku.source_image_path)
    if not path or not path.exists():
        # 没图或文件被删，无法参与识图，build_catalog 会把该 SKU 排除在 hash_index 外
        return None

    try:
        # compute_dhash：对图片做感知哈希（dHash），得到 64 位 01 字符串
        # 两张图内容接近 → 哈希汉明距离小；用户发图识货时用 find_best_match 比这个距离
        h = compute_dhash(path=str(path))
        meta["image_hash"] = h
        sku.metadata_ = meta
        # flush：把 metadata_ 写回 DB，下次 build_catalog 不用再算（上传时可能已写过，这里是懒加载补算）
        await db.flush()
        return h
    except Exception:
        # 图片损坏、格式不支持等：识图失败不影响目录其它字段，返回 None 表示该 SKU 不参与哈希匹配
        return None


async def build_catalog(db: AsyncSession) -> dict:
    """构建客服侧商品目录，顺带整理出可用于识图的 hash_index。"""
    result = await db.execute(select(Sku).order_by(Sku.created_at.desc()))
    skus = list(result.scalars().all())
    # by_category：按一级类目分组，供右侧商品面板按类目折叠展示
    by_category: dict[str, list] = defaultdict(list)
    # all_items：全店 SKU 扁平列表，文本介绍、浏览目录等场景用
    all_items = []
    # hash_candidates：能参与「发图识货」的商品子集（必须有 image_hash）
    # 用户发图时只跟这份列表比 dHash，不必遍历没图的商品
    hash_candidates = []

    for sku in skus:
        img_hash = await ensure_sku_hash(db, sku)
        has_image = path_exists(sku.source_image_path)
        item = {
            "id": sku.id,
            "sku_code": sku.sku_code,
            "name": sku.name or sku.sku_code,
            "category": sku.category or "未分类",
            "style": sku.style,
            "status": sku.status,  # draft/analyzed/ready/generated，反映运营流水线进度
            "image_url": _image_url(sku.id) if has_image else None,
            "image_hash": img_hash,  # dHash 指纹；None 表示该 SKU 不参与识图
        }
        # 类目可能是「女装/连衣裙」，面板只取第一段「女装」做分组
        cat = sku.category.split("/")[0] if sku.category and "/" in sku.category else (sku.category or "未分类")
        by_category[cat].append(item)
        all_items.append(item)
        if img_hash:
            # 与 item 是同一个 dict 引用，后面作为 hash_index 返回
            hash_candidates.append(item)

    categories = [
        {"name": k, "count": len(v), "items": v}
        for k, v in sorted(by_category.items(), key=lambda x: -len(x[1]))
    ]
    return {
        "total": len(all_items),
        "categories": categories,  # 分组目录，客服右侧面板用
        "items": all_items,  # 全量列表，find_sku_by_text 等文本匹配用
        "hash_index": hash_candidates,  # 识图候选池，match_image_to_sku / 相似款用
    }


async def match_image_to_sku(db: AsyncSession, image_bytes: bytes) -> dict:
    """用户发图后，用 dHash 在店内找最接近的同款商品。"""
    from app.services.image_similarity import find_best_match

    catalog = await build_catalog(db)
    # query_hash：用户上传图片的 dHash，与店内 hash_index 逐项比汉明距离
    query_hash = compute_dhash(image_bytes=image_bytes)
    # match：距离最小且低于阈值的商品；含 id、distance 等，distance 越小越像
    match = find_best_match(query_hash, catalog["hash_index"])
    return {
        "query_hash": query_hash,
        "match": match,  # None 表示店内没有足够接近的同款
        "catalog_total": catalog["total"],  # 全店 SKU 数，仅作调试/日志参考
    }
