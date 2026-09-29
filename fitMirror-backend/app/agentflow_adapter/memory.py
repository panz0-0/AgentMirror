from __future__ import annotations
import json, os, time
from dataclasses import dataclass
from typing import Any

@dataclass
class MemoryRecord:
    key: str
    text: str
    metadata: dict[str, Any]
    tier: str
    created_at: float

class MemoryManager:
    """三级记忆：Redis 会话工作/摘要 + Milvus 用户画像，外部服务不可用时安全降级。"""
    def __init__(self, redis_client=None, vector_store=None, *, max_working_turns=20):
        self.redis = redis_client
        self.vector_store = vector_store
        self.max_working_turns = max_working_turns
        self._local = {"working": [], "summary": [], "profile": []}

    @classmethod
    def from_environment(cls):
        redis_client = vector_store = None
        if os.getenv("AGENTFLOW_MEMORY_REDIS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
            try:
                import redis.asyncio as redis
                redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
            except Exception:
                pass
        if os.getenv("AGENTFLOW_MEMORY_MILVUS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
            try:
                # Never reuse the shared knowledge-base collection for user memory.
                # A dedicated, access-controlled store is required before enabling.
                vector_store = None
            except Exception:
                pass
        return cls(redis_client, vector_store)

    async def append_turn(self, session_id: str, role: str, content: str, *, user_id="guest", metadata=None):
        rec = {"role": role, "content": content, "user_id": user_id, "metadata": metadata or {}, "ts": time.time()}
        key = f"agentflow:memory:working:{session_id}"
        try:
            if self.redis:
                await self.redis.rpush(key, json.dumps(rec, ensure_ascii=False))
                await self.redis.ltrim(key, -self.max_working_turns, -1)
                return {"tier": "working", "backend": "redis", "degraded": False}
        except Exception:
            pass
        self._local["working"].append(MemoryRecord(session_id, json.dumps(rec, ensure_ascii=False), rec["metadata"], "working", rec["ts"]))
        self._local["working"] = [x for x in self._local["working"] if x.key != session_id or x in self._local["working"][-self.max_working_turns:]]
        # 上式保留其他会话，并只截断当前会话
        current = [x for x in self._local["working"] if x.key == session_id][-self.max_working_turns:]
        others = [x for x in self._local["working"] if x.key != session_id]
        self._local["working"] = others + current
        return {"tier": "working", "backend": "memory", "degraded": True}

    async def get_working(self, session_id: str):
        try:
            if self.redis:
                return [json.loads(x) for x in await self.redis.lrange(f"agentflow:memory:working:{session_id}", 0, -1)]
        except Exception:
            pass
        return [json.loads(x.text) for x in self._local["working"] if x.key == session_id]

    async def save_summary(self, session_id: str, summary: str, *, user_id="guest"):
        key = f"agentflow:memory:summary:{user_id}:{session_id}"
        payload = json.dumps({"session_id": session_id, "user_id": user_id, "summary": summary, "ts": time.time()}, ensure_ascii=False)
        try:
            if self.redis:
                await self.redis.set(key, payload, ex=int(os.getenv("MEMORY_SUMMARY_TTL", "2592000")))
                return {"tier": "summary", "backend": "redis", "degraded": False}
        except Exception:
            pass
        self._local["summary"] = [x for x in self._local["summary"] if x.key != key]
        self._local["summary"].append(MemoryRecord(key, payload, {"user_id": user_id}, "summary", time.time()))
        return {"tier": "summary", "backend": "memory", "degraded": True}

    async def save_profile(self, user_id: str, text: str, metadata=None):
        """存储用户画像：Redis Hash 持久化，未启用时降级为进程内存。"""
        meta = metadata or {}
        meta["user_id"] = user_id
        payload = json.dumps({"text": text, "meta": meta, "ts": time.time()}, ensure_ascii=False)
        key = f"agentflow:memory:profile:{user_id}"
        try:
            if self.redis:
                await self.redis.hset(key, "data", payload)
                await self.redis.expire(key, int(os.getenv("MEMORY_PROFILE_TTL", "7776000")))  # 90天
                return {"tier": "profile", "backend": "redis", "degraded": False}
        except Exception:
            pass
        self._local["profile"] = [x for x in self._local["profile"] if x.key != key]
        self._local["profile"].append(MemoryRecord(key, payload, meta, "profile", time.time()))
        return {"tier": "profile", "backend": "memory", "degraded": True}

    async def get_profile(self, user_id: str):
        """获取用户画像。"""
        try:
            if self.redis:
                value = await self.redis.hget(f"agentflow:memory:profile:{user_id}", "data")
                if value:
                    return json.loads(value)
        except Exception:
            pass
        for x in reversed(self._local["profile"]):
            if x.metadata.get("user_id") == user_id:
                return json.loads(x.text)
        return None

    async def recall(self, user_id: str, session_id: str, query: str = "", *, k=5):
        working = await self.get_working(session_id)
        summaries, profiles = [], []
        try:
            if self.redis:
                key = f"agentflow:memory:summary:{user_id}:{session_id}"
                value = await self.redis.get(key)
                if value:
                    summaries = [json.loads(value)]
        except Exception:
            pass
        if not summaries:
            summaries = [json.loads(x.text) for x in self._local["summary"] if x.metadata.get("user_id") == user_id and x.key.endswith(f":{session_id}")]
        # 用户画像：优先 Redis，降级内存
        profile = await self.get_profile(user_id)
        if profile:
            profiles = [profile]
        return {"working": working, "summaries": summaries, "profiles": profiles, "degraded": not bool(self.redis or self.vector_store)}

