"""生成任务内存进度存储，供 SSE 实时推送，不持久化到数据库。"""
import json
import threading
from typing import Any

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def set_job_progress(job_id: str, **data: Any) -> None:
    """更新任务进度；data 常见字段：status、stage、done、total、awaiting_confirm、error。"""
    with _lock:
        if job_id not in _jobs:
            # events：该任务每次进度变更的快照列表，SSE 可回放
            _jobs[job_id] = {"events": []}
        _jobs[job_id].update(data)
        _jobs[job_id]["events"].append(data)


def get_job_progress(job_id: str) -> dict[str, Any]:
    with _lock:
        # status：running / paused / done / failed / unknown（任务不存在时）
        return dict(_jobs.get(job_id, {"events": [], "status": "unknown"}))


def clear_job(job_id: str) -> None:
    with _lock:
        _jobs.pop(job_id, None)
