"""测试客服新功能：商品目录对齐、商品介绍、试穿、图文合并"""
import io
import sys
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000/api"
BACKEND = Path(__file__).resolve().parents[1]

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    print("=== catalog vs sku list ===")
    catalog = requests.get(f"{BASE}/chat/catalog", timeout=10).json()["data"]
    skus = requests.get(f"{BASE}/sku", timeout=10).json()["data"]
    assert catalog["total"] == skus["total"], f"catalog {catalog['total']} != sku {skus['total']}"
    print(f"OK: {catalog['total']} SKUs aligned")

    print("\n=== session ===")
    sess = requests.post(f"{BASE}/chat/session", json={"user_id": "guest", "title": "测试"}).json()
    sid = sess["data"]["session_id"]
    sku_id = catalog["items"][0]["id"]
    sku_name = catalog["items"][0]["name"]

    print("\n=== product intro ===")
    fd = {"session_id": sid, "user_id": "guest"}
    intro = requests.post(f"{BASE}/chat/product/{sku_id}", data=fd, timeout=30).json()["data"]
    assert intro["metadata"]["type"] == "product_intro"
    assert intro["metadata"]["sku_id"] == sku_id
    assert intro["metadata"]["image_url"] == f"/api/sku/{sku_id}/image"
    assert any(a["label"] == "查看上身效果图" for a in intro["metadata"]["actions"])
    print("intro OK:", sku_name, intro["reply"][:60])

    print("\n=== tryon default body ===")
    fd2 = {"session_id": sid, "user_id": "guest", "sku_id": sku_id}
    tryon = requests.post(f"{BASE}/chat/tryon", data=fd2, timeout=30).json()["data"]
    assert tryon["metadata"]["type"] == "tryon_result"
    assert tryon["metadata"].get("image_url") or tryon["metadata"].get("gallery_urls")
    code = tryon["metadata"].get("image_code", "")
    if code:
        assert code[0] in ("H", "M", "D"), f"unexpected tryon code: {code}"
        if code.startswith("D"):
            assert code in ("D5", "D6"), f"tryon should not use detail code {code}"
    print("tryon OK:", tryon["metadata"].get("image_code"), tryon["metadata"]["body"])

    print("\n=== compose text+image ===")
    img_path = BACKEND / "seed" / "images" / f"{catalog['items'][0]['sku_code']}.png"
    if not img_path.exists():
        img_path = BACKEND / "seed" / "images" / "DRESS-001.png"
    with open(img_path, "rb") as f:
        files = {"image": ("test.png", f, "image/png")}
        data = {"session_id": sid, "user_id": "guest", "content": "这款怎么样？"}
        combo = requests.post(f"{BASE}/chat/message/compose", data=data, files=files, timeout=30).json()["data"]
    assert combo["metadata"]["type"] in ("product_match", "product_intro")
    print("compose OK:", combo["reply"][:80])

    print("\n=== sku image endpoint ===")
    r = requests.get(f"http://127.0.0.1:8000/api/sku/{sku_id}/image", timeout=10)
    assert r.status_code == 200 and "image" in r.headers.get("content-type", "")
    print("image OK:", len(r.content), "bytes")

    print("\nALL CS FEATURE TESTS PASSED")


if __name__ == "__main__":
    main()
