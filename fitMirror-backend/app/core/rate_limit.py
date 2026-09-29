"""基于 IP 的内存限流，通过环境变量 RATE_LIMIT_ENABLED=true 开启。"""
import os
import time
from collections import defaultdict
from typing import Callable

from fastapi import Depends, Request

from app.core.failed_response import AppException

_memory_buckets: dict[str, list[float]] = defaultdict(list)


def rate_limit(limit: int = 30, window: int = 60) -> Callable:
    enabled = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"

    async def _check(request: Request):
        if not enabled:
            return
        key = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = _memory_buckets[key]
        _memory_buckets[key] = [t for t in bucket if now - t < window]
        if len(_memory_buckets[key]) >= limit:
            raise AppException("请求过于频繁，请稍后再试", 429)
        _memory_buckets[key].append(now)

    return Depends(_check)
