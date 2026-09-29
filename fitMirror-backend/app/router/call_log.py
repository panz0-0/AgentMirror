"""API 调用链路日志查询接口。"""
import json
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from app.core.success_response import success_response
from app.utils.path_tool import STORAGE_ROOT

call_log_router = APIRouter(prefix="/api/logs", tags=["logs"])

_LOG_DIR = STORAGE_ROOT / "logs"
_LOG_RETENTION_DAYS = 7


def _cleanup_old_logs():
    """删除超过 7 天的日志文件。"""
    if not _LOG_DIR.exists():
        return
    tz = timezone(timedelta(hours=8))
    cutoff = datetime.now(tz) - timedelta(days=_LOG_RETENTION_DAYS)
    for f in _LOG_DIR.glob("call_log_*.jsonl"):
        try:
            date_str = f.stem.replace("call_log_", "")
            file_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=tz)
            if file_date < cutoff:
                f.unlink()
        except Exception:
            continue


@call_log_router.get("/calls", summary="查询 API 调用日志")
async def get_call_logs(
    limit: Annotated[int, Query(description="返回条数，默认 50，最大 200")] = 50,
    status_filter: Annotated[str | None, Query(description="按状态码筛选：all/2xx/4xx/5xx")] = None,
    path_filter: Annotated[str | None, Query(description="按路径关键词筛选")] = None,
):
    """从近 7 天的 JSONL 日志文件中读取调用记录，按时间倒序返回。"""
    # 查询时顺便清理旧日志
    _cleanup_old_logs()

    if not _LOG_DIR.exists():
        return success_response(data={"items": [], "total": 0})

    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz).strftime("%Y%m%d")

    # 收集近 7 天的日志文件（从今天往前找）
    files = []
    for i in range(_LOG_RETENTION_DAYS):
        day = (datetime.now(tz) - timedelta(days=i)).strftime("%Y%m%d")
        f = _LOG_DIR / f"call_log_{day}.jsonl"
        if f.exists():
            files.append(f)

    if not files:
        return success_response(data={"items": [], "total": 0})

    # 从最新的文件开始倒序读取
    records = []
    for log_file in files:
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # 状态码筛选
            if status_filter == "2xx" and not (200 <= entry.get("status", 0) < 300):
                continue
            if status_filter == "4xx" and not (400 <= entry.get("status", 0) < 500):
                continue
            if status_filter == "5xx" and not (500 <= entry.get("status", 0) < 600):
                continue
            # 路径筛选
            if path_filter and path_filter not in entry.get("path", ""):
                continue
            records.append(entry)
            if len(records) >= min(limit, 200):
                break
        if len(records) >= min(limit, 200):
            break

    return success_response(data={"items": records, "total": len(records)})
