"""测试发图找相似款：用户碎花裙图应推荐 DRESS-001"""
import asyncio
import os
import sys
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = os.getenv("FITMIRROR_PORT", "8000")
BASE = f"http://127.0.0.1:{PORT}/api"
USER_DRESS = Path(
    r"C:\Users\yu\.cursor\projects\d-Project-python-ai-study\assets"
    r"\c__Users_yu_AppData_Roaming_Cursor_User_workspaceStorage_2741e2fd1cfe8e0e658488bb2dced734_images_image-dbbf19c7-e437-4a67-9891-3f4fa73d2928.png"
)
SEED_DRESS = BACKEND / "seed" / "images" / "DRESS-001.png"


async def test_service_layer():
    from app.db.db_config import AsyncSessionLocal
    from app.services.similar_product_service import find_similar_product

    img = USER_DRESS if USER_DRESS.exists() else SEED_DRESS
    assert img.exists(), f"test image missing: {img}"
    data = img.read_bytes()

    async with AsyncSessionLocal() as db:
        hit = await find_similar_product(db, data)
    assert hit, "find_similar_product returned None"
    code = hit.get("sku_code")
    print(f"service match: {code} method={hit.get('method')} similarity={hit.get('similarity')}")
    print(f"reason: {hit.get('reason')}")
    assert code == "DRESS-001", f"expected DRESS-001, got {code}"
    print("service layer OK")


def test_api_compose():
    health = requests.get(f"http://127.0.0.1:{PORT}/api/health", timeout=5)
    assert health.status_code == 200, "backend not running on :8000"

    sess = requests.post(f"{BASE}/chat/session", json={"user_id": "guest", "title": "相似款测试"}, timeout=10).json()
    sid = sess["data"]["session_id"]

    img = USER_DRESS if USER_DRESS.exists() else SEED_DRESS
    with open(img, "rb") as f:
        files = {"image": ("floral_dress.png", f, "image/png")}
        data = {"session_id": sid, "user_id": "guest", "content": "有类似的衣服吗？"}
        resp = requests.post(f"{BASE}/chat/message/compose", data=data, files=files, timeout=120).json()

    assert resp.get("code") in (0, 200, None) or "data" in resp, resp
    result = resp["data"]
    meta = result.get("metadata") or {}
    print(f"api type: {meta.get('type')} sku={meta.get('sku_code')}")
    print(f"reply preview: {result.get('reply', '')[:160]}")
    assert meta.get("type") == "similar_product", f"unexpected type {meta.get('type')}"
    assert meta.get("sku_code") == "DRESS-001", f"expected DRESS-001, got {meta.get('sku_code')}"
    assert "挺像" in result.get("reply", "") or "相似" in result.get("reply", ""), "reply should guide purchase"
    assert any(a.get("label") == "看看上身效果" for a in meta.get("actions", [])), "missing tryon action"
    print("api compose OK")


def main():
    print("=== similar product service ===")
    asyncio.run(test_service_layer())
    print("\n=== similar product API ===")
    test_api_compose()
    print("\nALL SIMILAR PRODUCT TESTS PASSED")


if __name__ == "__main__":
    main()
