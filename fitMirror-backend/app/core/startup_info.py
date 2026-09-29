"""启动时打印服务配置摘要（数据库、LLM、向量库、存储路径等）。"""
import os

from app.core.logger_handler import logger
from app.db.db_config import get_db_info
from app.pipeline.config import load_config
from app.utils.factory import (
    get_api_key_masked,
    get_chat_model_name,
    get_llm_base_url,
    has_llm_configured,
)
from app.utils.path_tool import STORAGE_ROOT


def _embed_model_name() -> str:
    embed_type = os.getenv("EMBED_TYPE", os.getenv("API_PROVIDER", "OPENAI")).upper()
    if embed_type == "OLLAMA":
        return os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    if embed_type in ("ALIYUN", "DASHSCOPE"):
        return os.getenv("EMBED_MODEL", "text-embedding-v3")
    return os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")


def _llm_provider() -> str:
    return os.getenv("LLM_TYPE", os.getenv("API_PROVIDER", "OPENAI")).upper()


def _vector_store_label() -> str:
    if os.getenv("USE_MILVUS", "false").lower() == "true":
        host = os.getenv("MILVUS_HOST", "localhost")
        port = os.getenv("MILVUS_PORT", "19530")
        collection = os.getenv("MILVUS_COLLECTION", "fitmirror_kb")
        return f"Milvus ({host}:{port}, collection={collection})"
    return "in-memory (storage/vectors/kb_index.json)"


def _server_base_url() -> str:
    host = os.getenv("HOST", "127.0.0.1")
    port = os.getenv("PORT", "8000")
    return f"http://{host}:{port}"


def collect_startup_info() -> dict[str, str]:
    pipeline = load_config()
    db = get_db_info()
    provider = _llm_provider()
    embed_type = os.getenv("EMBED_TYPE", os.getenv("API_PROVIDER", "OPENAI")).upper()
    base = _server_base_url()

    info = {
        "server": base,
        "swagger": f"{base}/docs",
        "redoc": f"{base}/redoc",
        "openapi": f"{base}/openapi.json",
        "health": f"{base}/api/health",
        "database": f"mysql @ {db['host']}:{db['port']}/{db['database']}",
        "vector_store": _vector_store_label(),
        "storage": str(STORAGE_ROOT.resolve()),
        "llm_provider": provider,
        "embed_provider": embed_type,
        "chat_model": get_chat_model_name(),
        "embed_model": _embed_model_name(),
        "vision_model": pipeline.vision_model or pipeline.model_name,
        "text_model": pipeline.text_model or pipeline.model_name,
        "image_model": pipeline.image_model,
        "image_provider": os.getenv("IMAGE_PROVIDER", pipeline.api_provider),
        "llm_base_url": get_llm_base_url() if provider != "OLLAMA" else os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "api_key": get_api_key_masked() if provider != "OLLAMA" else "(local, no key)",
        "llm_configured": "yes" if has_llm_configured() else "no",
        "rate_limit": "enabled" if os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true" else "disabled",
    }
    return info


def log_startup_banner() -> None:
    info = collect_startup_info()
    lines = [
        "",
        "=" * 62,
        "  fitMirror API started successfully",
        "=" * 62,
        f"  Server          {info['server']}",
        f"  Swagger UI      {info['swagger']}",
        f"  ReDoc           {info['redoc']}",
        f"  OpenAPI JSON    {info['openapi']}",
        f"  Health Check    {info['health']}",
        "-" * 62,
        f"  Database        {info['database']}",
        f"  Vector Store    {info['vector_store']}",
        f"  Storage         {info['storage']}",
        "-" * 62,
        f"  LLM Provider    {info['llm_provider']}",
        f"  LLM Configured  {info['llm_configured']}",
        f"  LLM Base URL    {info['llm_base_url']}",
        f"  Chat Model      {info['chat_model']}",
        f"  Embed Provider  {info['embed_provider']}",
        f"  Embed Model     {info['embed_model']}",
        f"  Vision Model    {info['vision_model']}",
        f"  Text Model      {info['text_model']}",
        f"  Image Provider  {info['image_provider']}",
        f"  Image Model     {info['image_model']}",
        f"  Rate Limit      {info['rate_limit']}",
        "=" * 62,
        "",
    ]
    for line in lines:
        logger.info(line)
