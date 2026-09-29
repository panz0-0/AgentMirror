"""验证 DRESS-002 状态与相对路径"""
import sys

import requests

API = "http://127.0.0.1:8000/api"
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    skus = requests.get(f"{API}/sku", timeout=10).json()["data"]["items"]
    sku = next(s for s in skus if s["sku_code"] == "DRESS-002")
    ws = requests.get(f"{API}/sku/{sku['id']}/workspace", timeout=10).json()["data"]
    job = requests.get(f"{API}/generation/sku/{sku['id']}/latest", timeout=10).json()["data"]

    print("DRESS-002 verification:")
    print("  source_image_path:", sku.get("source_image_path"))
    print("  has_campaign:", ws["has_campaign"])
    print("  has_prompts:", ws["has_prompts"], "count:", len(ws.get("prompt_list", [])))
    print("  job:", job["status"], job["current_node"])

    assert sku["source_image_path"].startswith("storage/")
    assert ws["has_prompts"] and len(ws["prompt_list"]) >= 5
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
