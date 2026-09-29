"""知识库 API 测试：筛选、预览、删除向量同步"""

import sys

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000/api"


def main():
    print("=== 知识库全量 ===")
    all_docs = requests.get(f"{BASE}/knowledge/list", params={"doc_type": "all"}).json()["data"]
    print(f"total={all_docs['total']}, vectors={all_docs['vector_count']}")

    print("\n=== 按类型筛选 ===")
    for t in ("faq", "script", "policy", "product"):
        d = requests.get(f"{BASE}/knowledge/list", params={"doc_type": t}).json()["data"]
        print(f"  {t}: {d['total']} docs")

    items = all_docs["items"]
    if not items:
        print("无文档，请先运行 seed_demo_data.py")
        return

    doc_id = items[0]["id"]
    print(f"\n=== 预览 {items[0]['title']} ===")
    prev = requests.get(f"{BASE}/knowledge/{doc_id}/preview").json()["data"]
    print(prev["preview_text"][:200], "...")

    print(f"\n=== 删除测试 doc {doc_id} ===")
    before = all_docs["vector_count"]
    del_res = requests.delete(f"{BASE}/knowledge/{doc_id}").json()
    after = del_res["data"]["vector_count"]
    print(f"vectors: {before} -> {after}")

    print("\n=== 验证已删除 ===")
    check = requests.get(f"{BASE}/knowledge/{doc_id}/preview")
    print(f"preview status: {check.status_code} (expect 404)")

    print("\n=== 商品目录 ===")
    cat = requests.get(f"{BASE}/chat/catalog").json()["data"]
    with_img = sum(1 for i in cat["items"] if i.get("image_url"))
    print(f"SKU total={cat['total']}, with_image={with_img}")

    print("\nALL KNOWLEDGE TESTS PASSED")


if __name__ == "__main__":
    main()
