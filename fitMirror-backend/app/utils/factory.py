"""LLM / Embedding / OpenAI 客户端工厂，按环境变量切换 Ollama / OpenAI / DashScope。"""
import os

from dotenv import load_dotenv
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings
from openai import OpenAI

from app.core.logger_handler import logger

load_dotenv()


def _api_key() -> str:
    return os.getenv("OPENAI_API_KEY") or os.getenv("ALIYUN_ACCESS_KEY_SECRET") or os.getenv("DASHSCOPE_API_KEY", "")


def _base_url() -> str:
    return os.getenv("BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")


def _chat_model_name() -> str:
    return (
        os.getenv("TEXT_MODEL")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("CHAT_MODEL")
        or os.getenv("MODEL_NAME")
        or "qwen-max"
    )


class DashScopeEmbeddings(Embeddings):
    def __init__(self, model_name: str = "text-embedding-v3", api_key: str | None = None):
        import dashscope

        dashscope.api_key = api_key or _api_key()
        self.dashscope = dashscope
        self.model_name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            resp = self.dashscope.TextEmbedding.call(model=self.model_name, input=text)
            if resp.status_code == 200:
                results.append(resp.output["embeddings"][0]["embedding"])
            else:
                results.append([0.0] * 8)
        return results

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_chat_model(timeout: int = 120) -> BaseChatModel | None:
    """获取对话模型实例，未配置 API Key 时返回 None。

    Args:
        timeout: 请求超时秒数。画像提取/摘要生成等轻量场景应传较小值（如 15），
                 避免 LLM 接口抖动时阻塞主对话响应。
    """
    llm_type = os.getenv("LLM_TYPE", os.getenv("API_PROVIDER", "OPENAI")).upper()
    if llm_type == "OLLAMA":
        return ChatOllama(
            model=os.getenv("OLLAMA_CHAT_MODEL", "qwen3:7b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    key = _api_key()
    if not key:
        return None
    # PrismPix 百炼兼容 OpenAI 协议：用 ChatOpenAI + BASE_URL
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=_chat_model_name(), api_key=key, base_url=_base_url(), timeout=timeout)


def _embed_api_key() -> str:
    """Embedding API Key，优先 EMBED_API_KEY，回退主 OPENAI_API_KEY。"""
    return (os.getenv("EMBED_API_KEY") or _api_key() or "").strip()


def _embed_base_url() -> str:
    """Embedding Base URL，优先 EMBED_BASE_URL，回退主 BASE_URL。"""
    return (os.getenv("EMBED_BASE_URL") or _base_url() or "").strip()


def get_embeddings() -> Embeddings | None:
    """获取 Embedding 模型，RAG 向量检索与 Milvus 依赖此配置。"""
    embed_type = os.getenv("EMBED_TYPE", os.getenv("API_PROVIDER", "OPENAI")).upper()
    if embed_type == "OLLAMA":
        return OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    key = _embed_api_key()
    if not key:
        return None
    if embed_type in ("ALIYUN", "DASHSCOPE"):
        return DashScopeEmbeddings(model_name=os.getenv("EMBED_MODEL", "text-embedding-v3"), api_key=key)
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        api_key=key,
        base_url=_embed_base_url(),
    )


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=_api_key(), base_url=_base_url(), timeout=float(os.getenv("REQUEST_TIMEOUT", "600")))


def get_chat_model_name() -> str:
    return _chat_model_name()


def get_llm_base_url() -> str:
    return _base_url()


def get_api_key_masked() -> str:
    key = _api_key()
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}***{key[-4:]}"


def has_llm_configured() -> bool:
    if os.getenv("LLM_TYPE", "").upper() == "OLLAMA" or os.getenv("API_PROVIDER", "").lower() == "ollama":
        return True
    return bool(_api_key())
