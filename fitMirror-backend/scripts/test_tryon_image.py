"""验证试穿效果图优先返回模特上身图（H3/M 系列），而非商品详情图。"""
import sys

import requests

BASE = "http://127.0.0.1:8000/api"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_CODES = {"H3", "M1", "M2", "M3", "M4", "M5", "D5", "D6"}


def main():
    catalog = requests.get(f"{BASE}/chat/catalog", timeout=10).json()["data"]
    target = None
    for item in catalog["items"]:
        name = item.get("name") or ""
        code = item.get("sku_code") or ""
        if "吊带" in name or "DRESS" in code.upper():
            target = item
            break
    target = target or catalog["items"][0]
    sku_id = target["id"]
    print(f"SKU: {target['name']} ({target['sku_code']})")

    ws = requests.get(f"{BASE}/sku/{sku_id}/workspace", timeout=30).json()["data"]
    ws_codes = [img["code"] for img in (ws or {}).get("images", [])]
    print(f"workspace codes: {ws_codes}")

    sid = requests.post(
        f"{BASE}/chat/session", json={"user_id": "tryon_fix", "title": "tryon"}
    ).json()["data"]["session_id"]
    requests.post(
        f"{BASE}/chat/product/{sku_id}",
        data={"session_id": sid, "user_id": "tryon_fix"},
        timeout=30,
    )
    tryon = requests.post(
        f"{BASE}/chat/tryon",
        data={"session_id": sid, "user_id": "tryon_fix", "sku_id": sku_id},
        timeout=60,
    ).json()["data"]

    meta = tryon["metadata"]
    assert meta["type"] == "tryon_result", meta
    code = meta.get("image_code", "")
    print(f"tryon image_code: {code}")
    print(f"is_model_shot: {meta.get('is_model_shot')}")
    print(f"gallery_urls: {meta.get('gallery_urls')}")

    if ws_codes and any(c in MODEL_CODES for c in ws_codes):
        assert code in MODEL_CODES, f"expected model code, got {code}"
        assert meta.get("is_model_shot") is True
        print("OK: model try-on image selected")
    elif meta.get("pending_generation"):
        assert not meta.get("image_url"), "pending tryon should not show product image"
        print("OK: no generated images, pending state without product fallback")
    else:
        assert meta.get("image_url"), "should have fallback hero image"
        print("OK: fallback hero image")

    print("ALL TRYON IMAGE TESTS PASSED")


if __name__ == "__main__":
    main()
