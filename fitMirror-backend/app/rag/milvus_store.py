"""知识库向量存储：支持 ChromaDB / Milvus 语义检索与内存关键词检索三种后端。

环境变量控制优先级：
  VECTOR_STORE=chroma  → ChromaDB（HttpClient 连接 Docker 服务）
  USE_MILVUS=true      → Milvus
  默认（都不设）        → InMemoryVectorStore（关键词匹配，持久化到 JSON）
"""
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from app.core.logger_handler import logger

_lock = threading.Lock()
_store: dict[str, dict[str, Any]] = {}
_milvus = None
_chroma = None
_chroma_failed = False  # ChromaDB 连接失败标记，避免每次请求都重试连接

INDEX_PATH = Path(__file__).resolve().parents[2] / "storage" / "vectors" / "kb_index.json"


class InMemoryVectorStore:
    """基于关键词重叠评分的内存向量库，不依赖 embedding 模型，适合开发/演示环境。"""
    def __init__(self):
        self._load()

    def _load(self) -> None:
        global _store
        if INDEX_PATH.exists():
            try:
                _store = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
                logger.info("Loaded %d vectors from %s", len(_store), INDEX_PATH)
            except Exception as e:
                logger.warning("Failed to load vector index: %s", e)
                _store = {}

    def _persist(self) -> None:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(_store, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, texts: list[str], metadatas: list[dict] | None = None) -> list[str]:
        ids = []
        with _lock:
            for i, text in enumerate(texts):
                doc_id = f"mem_{len(_store)}_{i}"
                meta = (metadatas or [{}])[i] if metadatas else {}
                _store[doc_id] = {"text": text, "meta": meta}
                ids.append(doc_id)
            self._persist()
        return ids

    def search(self, query: str, k: int = 3, doc_type: str | None = None) -> list[dict]:
        q = query.lower()
        # 按空白切分得到词级匹配单元
        words = [re.sub(r"[^\w\u4e00-\u9fff]", "", w) for w in q.split() if w]
        # 对中文词（无空格）补充字符 bigram，避免整句匹配失败
        terms = set(words)
        for w in words:
            if re.search(r"[\u4e00-\u9fff]", w) and len(w) >= 2:
                for i in range(len(w) - 1):
                    terms.add(w[i:i + 2])
        terms = [t for t in terms if t]
        scored = []
        with _lock:
            for doc_id, item in _store.items():
                if doc_type and item.get("meta", {}).get("doc_type") != doc_type:
                    continue
                text = item["text"].lower()
                score = sum(1 for t in terms if t in text)
                if score > 0:
                    scored.append((score, doc_id, item))
        scored.sort(key=lambda x: -x[0])
        return [{"id": s[1], "text": s[2]["text"], "meta": s[2]["meta"]} for s in scored[:k]]

    def delete(self, ids: list[str]) -> None:
        with _lock:
            for i in ids:
                _store.pop(i, None)
            self._persist()

    def delete_by_kb_doc_id(self, kb_doc_id: str) -> int:
        to_remove = []
        with _lock:
            for vid, item in _store.items():
                if item.get("meta", {}).get("kb_doc_id") == kb_doc_id:
                    to_remove.append(vid)
            for vid in to_remove:
                _store.pop(vid, None)
            if to_remove:
                self._persist()
        return len(to_remove)

    def count(self) -> int:
        with _lock:
            return len(_store)


_memory_store = InMemoryVectorStore()


def _use_chroma() -> bool:
    return os.getenv("VECTOR_STORE", "").lower() == "chroma"


def _use_milvus() -> bool:
    return os.getenv("USE_MILVUS", "false").lower() == "true"


def get_vector_store():
    """获取向量存储实例：ChromaDB → Milvus → 内存关键词检索，按优先级降级。"""
    global _milvus, _chroma, _chroma_failed

    # 1. ChromaDB
    if _use_chroma() and not _chroma_failed:
        if _chroma is not None:
            return _chroma
        try:
            import chromadb
            from langchain_community.vectorstores import Chroma
            from app.utils.factory import get_embeddings

            emb = get_embeddings()
            if not emb:
                logger.warning("No embeddings configured, fallback to in-memory store")
                return _memory_store

            chroma_client = chromadb.HttpClient(
                host=os.getenv("CHROMA_HOST", "localhost"),
                port=int(os.getenv("CHROMA_PORT", "8000")),
            )
            collection_name = os.getenv("CHROMA_COLLECTION", "fitmirror_kb")
            _chroma = Chroma(
                client=chroma_client,
                collection_name=collection_name,
                embedding_function=emb,
            )
            logger.info("Connected to ChromaDB at %s:%s collection=%s",
                        os.getenv("CHROMA_HOST", "localhost"),
                        os.getenv("CHROMA_PORT", "8000"),
                        collection_name)
            return _chroma
        except Exception as e:
            _chroma_failed = True
            logger.warning("ChromaDB unavailable, falling back to in-memory: %s", e)
            return _memory_store

    # 2. Milvus
    if not _use_milvus():
        return _memory_store
    if _milvus is not None:
        return _milvus
    try:
        from langchain_milvus import Milvus
        from app.utils.factory import get_embeddings

        emb = get_embeddings()
        if not emb:
            logger.warning("No embeddings, fallback to in-memory store")
            return _memory_store
        _milvus = Milvus(
            embedding_function=emb,
            collection_name=os.getenv("MILVUS_COLLECTION", "fitmirror_kb"),
            connection_args={
                "uri": f"http://{os.getenv('MILVUS_HOST', 'localhost')}:{os.getenv('MILVUS_PORT', '19530')}"
            },
            auto_id=True,
        )
        return _milvus
    except Exception as e:
        logger.warning("Milvus unavailable, using in-memory: %s", e)
        return _memory_store


def add_documents(texts: list[str], metadata: dict | None = None) -> list[str]:
    store = get_vector_store()
    meta = metadata or {}
    if isinstance(store, InMemoryVectorStore):
        return store.add(texts, [meta] * len(texts))
    from langchain_core.documents import Document

    docs = [Document(page_content=t, metadata=meta) for t in texts]
    ids = store.add_documents(docs)
    return [str(i) for i in ids]


def delete_by_ids(ids: list[str]) -> None:
    store = get_vector_store()
    if isinstance(store, InMemoryVectorStore):
        store.delete(ids)
        return
    try:
        store.delete(ids=ids)
    except Exception as e:
        logger.warning("Delete from vector store failed: %s", e)


def delete_by_kb_doc_id(kb_doc_id: str) -> int:
    store = get_vector_store()
    if isinstance(store, InMemoryVectorStore):
        return store.delete_by_kb_doc_id(kb_doc_id)
    # ChromaDB 支持按 metadata 过滤删除
    try:
        from langchain_community.vectorstores import Chroma
        if isinstance(store, Chroma):
            store._collection.delete(where={"kb_doc_id": kb_doc_id})
            return store._collection.count()
    except Exception as e:
        logger.warning("Delete by kb_doc_id from ChromaDB failed: %s", e)
    delete_by_ids([])  # Milvus 路径暂不支持按 kb_doc_id 批量删除
    return 0


def search_documents(query: str, k: int = 3, doc_type: str | None = None) -> list[dict]:
    store = get_vector_store()
    if isinstance(store, InMemoryVectorStore):
        return store.search(query, k=k, doc_type=doc_type)
    results = store.similarity_search(query, k=k)
    return [{"text": d.page_content, "meta": d.metadata} for d in results]


def vector_count() -> int:
    store = get_vector_store()
    if isinstance(store, InMemoryVectorStore):
        return store.count()
    try:
        from langchain_community.vectorstores import Chroma
        if isinstance(store, Chroma):
            return store._collection.count()
    except Exception:
        pass
    return 0
