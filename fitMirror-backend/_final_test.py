import requests
import time

uid = "u_final_v2"
base = "http://127.0.0.1:8000"

# Session A
sa = requests.post(f"{base}/api/chat/session", json={"user_id": uid, "title": "A"}).json()
sidA = sa["data"]["session_id"]
t0 = time.time()
r1 = requests.post(f"{base}/api/chat/message", json={"session_id": sidA, "user_id": uid, "content": "你好，我叫小红，身高165，体重50公斤，喜欢甜美风格"}, timeout=60).json()
d1 = r1["data"]
print(f"A1: {time.time()-t0:.1f}s route={d1['executed_route']} err={d1['metadata'].get('agentflow_execution_error','')}")
print(f"A1 reply: {d1['reply'][:80]}")

# 等一下让后台画像提取完成
time.sleep(12)

# Session B - 跨会话记忆
sb = requests.post(f"{base}/api/chat/session", json={"user_id": uid, "title": "B"}).json()
sidB = sb["data"]["session_id"]
t0 = time.time()
r3 = requests.post(f"{base}/api/chat/message", json={"session_id": sidB, "user_id": uid, "content": "你还记得我叫什么吗？身高体重多少？"}, timeout=60).json()
d3 = r3["data"]
print(f"\nB1: {time.time()-t0:.1f}s route={d3['executed_route']}")
print(f"B1 reply: {d3['reply']}")
