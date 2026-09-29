"""fitMirror 鍚庣鍏ュ彛锛欶astAPI 搴旂敤瑁呴厤銆佽矾鐢辨敞鍐屼笌鍚姩鍒濆鍖栥€?
鍚姩娴佺▼锛氬姞杞?.env 鈫?娉ㄥ唽涓棿浠朵笌寮傚父澶勭悊 鈫?鎸傝浇闈欐€佸瓨鍌ㄧ洰褰?鈫?startup 鏃舵鏌?MySQL銆佸缓琛ㄣ€佸悗鍙伴鐑悜閲忓簱銆?"""
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.background_init import init_manager
from app.core.failed_response_register import register_exception_handlers
from app.core.logger_handler import logger
from app.core.startup_info import log_startup_banner
from app.db.db_config import check_db_connection, get_db_info, init_db
from app.router.chat import chat_router
from app.agentflow_adapter.router import agentflow_router
from app.router.generation import generation_router
from app.router.health import health_router, images_router
from app.router.metadata import metadata_router
from app.router.knowledge import knowledge_router
from app.router.evaluation import evaluation_router
from app.router.call_log import call_log_router
from app.router.openapi_tags import API_DESCRIPTION, API_TAGS
from app.router.sku import sku_router
from app.utils.path_tool import STORAGE_ROOT, ensure_storage_dirs

load_dotenv(Path(__file__).parent / ".env")

app = FastAPI(
    title="fitMirror API",
    version="0.1.0",
    description=API_DESCRIPTION,
    openapi_tags=API_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def call_log_middleware(request: Request, call_next):
    """请求链路日志：记录每个 API 调用的方法、路径、状态码、延迟、错误。"""
    import json, os
    from datetime import datetime, timezone, timedelta

    start = time.time()
    method = request.method
    path = request.url.path

    # 排除日志查询本身，避免自引用
    if path.startswith("/api/logs/"):
        return await call_next(request)
    client_ip = request.client.host if request.client else "-"

    # 提取关键请求参数（不记录 body 原文，避免敏感信息）
    params = dict(request.query_params)
    if not params and request.headers.get("content-type", "").startswith("multipart/form-data"):
        params = {"_note": "multipart upload"}

    status_code = 500
    error_msg = None
    business_error = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Process-Time"] = str(round(time.time() - start, 4))
        # 捕获业务层错误（runtime fallback 设置的 header）
        business_error = response.headers.get("X-Business-Error")
        return response
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        latency_ms = round((time.time() - start) * 1000, 1)
        tz = timezone(timedelta(hours=8))
        log_entry = {
            "ts": datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "method": method,
            "path": path,
            "status": status_code,
            "latency_ms": latency_ms,
            "client": client_ip,
            "params": params if params else None,
            "error": error_msg or business_error,
        }
        # 写入 JSONL 日志文件
        try:
            log_dir = STORAGE_ROOT / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"call_log_{datetime.now(tz).strftime('%Y%m%d')}.jsonl"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # 同时输出到 logger
        status_icon = "OK" if status_code < 400 else "ERR"
        log_tail = ""
        if error_msg or business_error:
            log_tail = f" error={error_msg or business_error}"
        logger.info(f"[{status_icon}] {method} {path} {status_code} {latency_ms}ms {client_ip}{log_tail}")


register_exception_handlers(app)
app.include_router(health_router)
app.include_router(sku_router)
app.include_router(generation_router)
app.include_router(chat_router)
app.include_router(agentflow_router)
app.include_router(knowledge_router)
app.include_router(evaluation_router)
app.include_router(call_log_router)
app.include_router(metadata_router)
app.include_router(images_router)


@app.get("/metrics", summary="Prometheus 指标抓取端点")
async def prometheus_metrics():
    """以 Prometheus text format 暴露 AgentFlow 运行指标。"""
    from app.agentflow_adapter.prometheus_metrics import DEFAULT_PROMETHEUS
    from fastapi.responses import Response

    payload, available = DEFAULT_PROMETHEUS.render()
    if not available:
        return Response(content="# prometheus exporter unavailable\n", media_type="text/plain", status_code=503)
    return Response(content=payload, media_type="text/plain; version=0.0.4")


storage_path = STORAGE_ROOT
if storage_path.exists():
    app.mount("/storage", StaticFiles(directory=str(storage_path)), name="storage")


@app.on_event("startup")
async def startup():
    ensure_storage_dirs()
    if not await check_db_connection():
        info = get_db_info()
        raise RuntimeError(
            f"MySQL 杩炴帴澶辫触锛岃妫€鏌ユ湇鍔℃槸鍚﹀惎鍔ㄥ強 .env 閰嶇疆: "
            f"{info['host']}:{info['port']}/{info['database']}"
        )
    await init_db()
    logger.info("MySQL initialized: %s", get_db_info())
    await init_manager.start()
    log_startup_banner()


@app.get("/", summary="API root", description="fitMirror API root")
async def root():
    return {"message": "fitMirror API", "docs": "/docs"}

