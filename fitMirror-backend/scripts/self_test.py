import sys
import time
import requests

BASE = "http://127.0.0.1:8000/api"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    print("=== health ===")
    h = requests.get(f"{BASE}/health", timeout=10).json()
    print(h)
    assert h["data"]["llm_configured"] is True, "LLM not configured - check .env"

    print("\n=== new chat session (DB) ===")
    sess = requests.post(f"{BASE}/chat/session", json={"user_id": "guest", "title": "新的对话"}).json()
    sid = sess["data"]["session_id"]
    print("session_id:", sid)

    history = requests.get(f"{BASE}/chat/session/{sid}/history").json()["data"]
    print("welcome msg:", history[0]["content"][:40], "...")

    print("\n=== real LLM chat: 尺码 ===")
    r1 = requests.post(
        f"{BASE}/chat/message",
        json={"session_id": sid, "user_id": "guest", "content": "身高176 适合什么尺码"},
        timeout=120,
    ).json()
    print("reply:", r1["data"]["reply"][:200])

    print("\n=== real LLM chat: 发货 ===")
    r2 = requests.post(
        f"{BASE}/chat/message",
        json={"session_id": sid, "user_id": "guest", "content": "几天发货？"},
        timeout=120,
    ).json()
    print("reply:", r2["data"]["reply"][:200])

    print("\n=== sessions in DB ===")
    sessions = requests.get(f"{BASE}/chat/sessions", params={"user_id": "guest"}).json()["data"]
    print(f"{len(sessions)} sessions, latest: {sessions[0]['title']}")

    print("\n=== metadata ===")
    meta = requests.get(f"{BASE}/metadata").json()["data"]
    print(f"categories: {len(meta.get('dropdowns', {}).get('categories', []))}")

    print("\nALL REAL-LLM TESTS PASSED")


if __name__ == "__main__":
    main()
