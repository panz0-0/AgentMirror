"""测试运营台完整三步流程：确认提示词 + 可选出图"""
import sys
import time

import requests

API = "http://127.0.0.1:8000/api"
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def wait_job(job_id, until, timeout=600):
    for i in range(timeout // 2):
        try:
            data = requests.get(f"{API}/generation/{job_id}", timeout=120).json()["data"]
        except requests.exceptions.ReadTimeout:
            print(f"  poll {i}: server busy, retry...")
            time.sleep(3)
            continue
        print(f"  job {data['status']} / {data['current_node']} stage={data.get('progress',{}).get('stage')}")
        if data["status"] == "failed":
            raise RuntimeError(data.get("error_msg") or data.get("progress", {}).get("error") or "failed")
        if until(data):
            return data
        time.sleep(2)
    raise TimeoutError("job timeout")


def main():
    skus = requests.get(f"{API}/sku", timeout=30).json()["data"]["items"]
    sku = next(s for s in skus if s["sku_code"] == "TOP-001")
    sid = sku["id"]
    print("SKU:", sku["sku_code"], sid)

    ws = requests.get(f"{API}/sku/{sid}/workspace", timeout=30).json()["data"]
    print("campaign:", ws["has_campaign"], "prompts:", ws["has_prompts"])

    ensured = requests.post(
        f"{API}/generation/ensure",
        json={"sku_id": sid, "node": "campaign", "mode": "hero"},
        timeout=30,
    ).json()["data"]
    job_id = ensured["job_id"]
    print("ensure job:", job_id)

    print("\n=== Step2: generate prompts ===")
    requests.post(f"{API}/generation/resume", json={"job_id": job_id, "action": "confirm"}, timeout=30)
    result = wait_job(job_id, lambda d: d["status"] == "paused" and d["current_node"] == "prompts")
    print("prompts done:", result["current_node"])

    ws2 = requests.get(f"{API}/sku/{sid}/workspace", timeout=30).json()["data"]
    print("prompt count:", len(ws2.get("prompt_list", [])))
    assert ws2["has_prompts"], "prompts.json should exist"
    assert len(ws2["prompt_list"]) >= 5, f"hero mode expects >=5 prompts, got {len(ws2['prompt_list'])}"
    print("first prompt:", ws2["prompt_list"][0]["code"], ws2["prompt_list"][0]["prompt"][:80], "...")

    print("\nALL OPS PROMPT TESTS PASSED")


if __name__ == "__main__":
    main()
