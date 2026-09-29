"""RAG retrieval and answer generation with dependency-safe fallbacks."""
import asyncio
import logging

from app.rag.milvus_store import search_documents
from app.utils.factory import get_chat_model, has_llm_configured

logger = logging.getLogger(__name__)

NO_RESULT = "\u6682\u672a\u627e\u5230\u76f8\u5173\u77e5\u8bc6\u5e93\u5185\u5bb9\uff0c\u8bf7\u8054\u7cfb\u4eba\u5de5\u5ba2\u670d\u3002"


class RagService:
    """Retrieve top-k knowledge chunks and optionally ask the configured LLM."""

    def query(self, question: str) -> str:
        try:
            docs = search_documents(question, k=3)
        except Exception:
            logger.exception("RAG vector search failed; returning no-result fallback")
            return NO_RESULT

        if not docs:
            return NO_RESULT

        context = "\n\n".join(str(d.get("text", "")) for d in docs if d.get("text"))
        if not context:
            return NO_RESULT
        fallback = f"\u6839\u636e\u77e5\u8bc6\u5e93\uff1a\n{context[:800]}"

        if not has_llm_configured():
            return fallback
        model = get_chat_model()
        if not model:
            return fallback

        from langchain_core.messages import HumanMessage, SystemMessage
        try:
            resp = model.invoke([
                SystemMessage(content="\u4f60\u662f\u5ba2\u670d\u52a9\u624b\uff0c\u6839\u636e\u77e5\u8bc6\u5e93\u5185\u5bb9\u7b80\u6d01\u56de\u7b54\u3002"),
                HumanMessage(content=f"\u77e5\u8bc6\u5e93\uff1a\n{context}\n\n\u95ee\u9898\uff1a{question}"),
            ])
            return resp.content if isinstance(resp.content, str) else str(resp.content)
        except Exception:
            logger.exception("RAG LLM request failed; returning retrieved context")
            return fallback

    async def aquery(self, question: str) -> str:
        return await asyncio.to_thread(self.query, question)
