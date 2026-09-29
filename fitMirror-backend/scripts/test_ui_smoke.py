"""前端页面 + API 交互冒烟测试（需后端/前端已启动）"""
import sys
import time

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "http://127.0.0.1:8000/api"
WEB = "http://localhost:5173"


def wait(url, timeout=30):
    for _ in range(timeout):
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"timeout waiting {url}")


def main():
    print("=== 等待服务启动 ===")
    health = wait(f"{API}/health").json()
    assert health["data"]["db"] is True
    assert health["data"]["db_info"]["type"] == "mysql"
    assert health["data"]["db_info"]["database"] == "fitmirror"
    print("OK MySQL:", health["data"]["db_info"])

    page = wait(WEB)
    html = page.text
    assert "fitmirror" in html.lower() or "vite" in html.lower() or len(html) > 100
    print("OK 前端页面可访问")

    print("\n=== SKU 列表 ===")
    skus = requests.get(f"{API}/sku").json()["data"]
    assert skus["total"] == 6, f"expected 6 skus, got {skus['total']}"
    sku = skus["items"][0]
    sku_id = sku["id"]
    print(f"OK {skus['total']} SKUs in MySQL")

    print("\n=== SKU 更新回显 ===")
    fd = {
        "sku_code": sku["sku_code"],
        "name": (sku["name"] or "") + "-edited",
        "category": sku.get("category") or "女装/连衣裙",
        "style": sku.get("style") or "",
        "platform": sku.get("platform") or "淘宝",
        "language": sku.get("language") or "中文",
        "model_attrs": sku.get("model_attrs") or "亚洲女性, 身高165cm, 体重55kg",
    }
    upd = requests.put(f"{API}/sku/{sku_id}", data=fd, timeout=30).json()
    assert upd["code"] == 200
    detail = requests.get(f"{API}/sku/{sku_id}").json()["data"]
    assert detail["name"].endswith("-edited")
    # 还原名称
    fd["name"] = sku["name"]
    requests.put(f"{API}/sku/{sku_id}", data=fd, timeout=30)
    print("OK SKU 更新/回显")

    print("\n=== 客服会话 + 商品介绍 + 试穿 ===")
    sess = requests.post(f"{API}/chat/session", json={"user_id": "guest", "title": "UI测试"}).json()
    sid = sess["data"]["session_id"]
    intro = requests.post(
        f"{API}/chat/product/{sku_id}",
        data={"session_id": sid, "user_id": "guest"},
        timeout=30,
    ).json()["data"]
    assert intro["metadata"]["image_url"]
    assert any(a["label"] == "查看上身效果图" for a in intro["metadata"]["actions"])
    tryon = requests.post(
        f"{API}/chat/tryon",
        data={"session_id": sid, "user_id": "guest", "sku_id": sku_id},
        timeout=30,
    ).json()["data"]
    assert tryon["metadata"]["type"] == "tryon_result"
    print("OK 商品介绍 + 试穿")

    print("\n=== 图文合并发送 ===")
    from pathlib import Path
    img = Path(__file__).resolve().parents[1] / "seed" / "images" / "DRESS-001.png"
    with open(img, "rb") as f:
        combo = requests.post(
            f"{API}/chat/message/compose",
            data={"session_id": sid, "user_id": "guest", "content": "这款怎么样"},
            files={"image": ("test.png", f, "image/png")},
            timeout=30,
        ).json()["data"]
    assert combo["metadata"].get("image_url") or combo["metadata"]["type"] in ("product_match", "product_intro")
    hist = requests.get(f"{API}/chat/session/{sid}/history").json()["data"]
    user_img_msgs = [m for m in hist if m["role"] == "user" and m.get("metadata", {}).get("image_url")]
    assert user_img_msgs, "用户图片消息应写入历史"
    print("OK 图文消息 + 历史含图片URL")

    print("\n=== 前端路由页面 ===")
    for path in ["/", "/ops", "/knowledge"]:
        r = requests.get(f"{WEB}{path}", timeout=5)
        assert r.status_code == 200, path
    print("OK 前端路由 / /ops /knowledge")

    print("\nALL INTERACTION SMOKE TESTS PASSED")
    print(f"\n请在浏览器打开: {WEB}")
    print("- AI客服: 粘贴图片预览后发送，点击消息图片可放大")
    print("- 运营台: 点击 SKU 列表行回显表单，修改后点「保存修改」")
    print("- MySQL: fitmirror 库 skus 表应有 6 条数据")


if __name__ == "__main__":
    main()
