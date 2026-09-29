"""验证 TOP-001 图片断点续跑与完成状态"""
import sys
import time

import requests

API = "http://127.0.0.1:8000/api"
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def wait_job(job_id, until, timeout=120):
    for i in range(timeout // 2):
        data = requests.get(f"{API}/generation/{job_id}", timeout=60).json()["data"]
        ip = data.get("image_progress") or data.get("progress", {})
        print(
            f"  poll {i}: status={data['status']} node={data['current_node']} "
            f"done={ip.get('done')}/{ip.get('total')}"
        )
        if data["status"] == "failed":
            raise RuntimeError(data.get("error_msg"))
        if until(data):
            return data
        time.sleep(2)
    raise TimeoutError("timeout")


def main():
    skus = requests.get(f"{API}/sku", timeout=30).json()["data"]["items"]
    sku = next(s for s in skus if s["sku_code"] == "TOP-001")
    sid = sku["id"]
    print("SKU", sku["sku_code"], sid)

    ws = requests.get(f"{API}/sku/{sid}/workspace", timeout=30).json()["data"]
    print("image_progress:", ws.get("image_progress"))
    print("images:", len(ws.get("images", [])))

    ensured = requests.post(
        f"{API}/generation/ensure",
        json={"sku_id": sid, "node": "prompts", "mode": "hero"},
        timeout=30,
    ).json()["data"]
    job_id = ensured["job_id"]
    print("ensure:", ensured)

    requests.post(
        f"{API}/generation/resume",
        json={"job_id": job_id, "action": "confirm"},
        timeout=30,
    )
    result = wait_job(job_id, lambda d: d["status"] in ("done", "paused", "failed"))
    print("final:", result["status"], result["current_node"])

    ws2 = requests.get(f"{API}/sku/{sid}/workspace", timeout=30).json()["data"]
    print("final image_progress:", ws2.get("image_progress"))
    print("final images:", len(ws2.get("images", [])))
    assert ws2["image_progress"]["complete"], "images should be complete"
    print("TOP-001 IMAGE FLOW OK")


if __name__ == "__main__":
    main()
