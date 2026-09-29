"""感知哈希 (dHash) 图片相似度检索，用于客服发图匹配店铺 SKU。"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image


def compute_dhash(image_bytes: bytes | None = None, path: str | Path | None = None, size: int = 8) -> str:
    """把图片压成 dHash 指纹，用于后续做相似度检索。"""
    if image_bytes:
        img = Image.open(io.BytesIO(image_bytes))
    elif path and Path(path).exists():
        img = Image.open(path)
    else:
        raise ValueError("需要提供 image_bytes 或有效 path")
    img = img.convert("L").resize((size + 1, size))
    px = list(img.getdata())
    bits = []
    for y in range(size):
        for x in range(size):
            bits.append(px[y * (size + 1) + x] > px[y * (size + 1) + x + 1])
    return "".join("1" if b else "0" for b in bits)


def hamming_distance(a: str, b: str) -> int:
    """计算两个等长 dHash 字符串的汉明距离。"""
    if not a or not b or len(a) != len(b):
        return 999
    return sum(c1 != c2 for c1, c2 in zip(a, b))


def find_best_match(
    query_hash: str,
    candidates: list[dict],
    *,
    max_distance: int = 12,
) -> dict | None:
    """在候选商品里找与用户图片最接近的单个 SKU。"""
    ranked = find_top_matches(query_hash, candidates, top_k=1, max_distance=max_distance)
    return ranked[0] if ranked else None


def find_top_matches(
    query_hash: str,
    candidates: list[dict],
    *,
    top_k: int = 3,
    max_distance: int | None = None,
) -> list[dict]:
    """按汉明距离从小到大返回最相似的若干候选。"""
    scored: list[dict] = []
    for c in candidates:
        h = c.get("image_hash") or ""
        if not h:
            continue
        d = hamming_distance(query_hash, h)
        if max_distance is not None and d > max_distance:
            continue
        # distance：两张图 dHash 的汉明距离，0=完全相同，越大差异越大
        scored.append({**c, "distance": d})
    scored.sort(key=lambda x: x["distance"])
    return scored[:top_k]
