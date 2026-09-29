"""验证 DRESS-002 提示词生成流程"""
import sys
import time

import requests

API = "http://127.0.0.1:8000/api"
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def wait_job(job_id, until, timeout=300):
    for i in range(timeout // 2):
        data = requests.get(f"{API}/generation/{job_id}", timeout=60).json()["data"]
        print(f"  poll {i}: {data['status']} / {data['current_node']} err={data.get('error_msg')}")
        if data["status"] == "failed":
            raise RuntimeError(data.get("error_msg") or "failed")
        if until(data):
            return data
        time.sleep(2)
    raise TimeoutError("timeout")


def main():
    skus = requests.get(f"{API}/sku", timeout=30).json()["data"]["items"]
    sku = next(s for s in skus if s["sku_code"] == "DRESS-002")
    sid = sku["id"]
    print("SKU", sku["sku_code"], sid)
    print("source_image_path", sku.get("source_image_path"))

    ws = requests.get(f"{API}/sku/{sid}/workspace", timeout=30).json()["data"]
    print("has_campaign", ws["has_campaign"], "has_prompts", ws["has_prompts"])

    ensured = requests.post(
        f"{API}/generation/ensure",
        json={"sku_id": sid, "node": "campaign", "mode": "hero"},
        timeout=30,
    ).json()["data"]
    job_id = ensured["job_id"]
    print("ensure", ensured)

    requests.post(f"{API}/generation/resume", json={"job_id": job_id, "action": "confirm"}, timeout=30)
    result = wait_job(job_id, lambda d: d["status"] == "paused" and d["current_node"] == "prompts")
    print("done", result["current_node"])

    ws2 = requests.get(f"{API}/sku/{sid}/workspace", timeout=30).json()["data"]
    print("prompts", len(ws2.get("prompt_list", [])))
    assert ws2["has_prompts"], "prompts should exist"
    print("DRESS-002 PROMPTS OK")


if __name__ == "__main__":
    main()
