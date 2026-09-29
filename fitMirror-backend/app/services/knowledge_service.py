"""知识库文档管理：上传解析 → 分块 → 向量化 → 持久化。

支持 doc_type：faq（常见问题）、script（客服话术）、policy（政策）、product（商品说明）。
"""
import hashlib
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_doc import KnowledgeDoc
from app.rag.document_parser import extract_text, preview_text
from app.rag.pdf_structured_parser import parse_pdf_structured
from app.utils.path_tool import KNOWLEDGE_DIR, normalize_stored_path, path_exists, resolve_storage_path

DOC_TYPES = ("faq", "script", "policy", "product")


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _split_text(text: str, chunk_size: int = 500) -> list[str]:
    """按段落边界分块，单块不超过 chunk_size 字符，供向量检索使用。"""
    parts = re.split(r"\n{2,}", text)
    chunks, buf = [], ""
    for p in parts:
        if len(buf) + len(p) < chunk_size:
            buf += p + "\n\n"
        else:
            if buf.strip():
                chunks.append(buf.strip())
            buf = p + "\n\n"
    if buf.strip():
        chunks.append(buf.strip())
    return chunks or [text[:chunk_size]]


class KnowledgeService:
    """知识库 CRUD：文件存储 + 向量索引 + MySQL 元数据。"""
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_docs(self, doc_type: str | None = None) -> list[KnowledgeDoc]:
        q = select(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc())
        if doc_type and doc_type != "all":
            q = q.where(KnowledgeDoc.doc_type == doc_type)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def get_doc(self, doc_id: str) -> KnowledgeDoc | None:
        return await self.db.get(KnowledgeDoc, doc_id)

    async def upload_file(self, filename: str, content: bytes, doc_type: str = "faq") -> KnowledgeDoc:
        if doc_type not in DOC_TYPES:
            doc_type = "faq"
        md5 = _md5(content)
        existing = await self.db.execute(select(KnowledgeDoc).where(KnowledgeDoc.md5 == md5))
        if existing.scalar_one_or_none():
            raise ValueError("文件已存在（内容相同）")

        doc_id = uuid.uuid4().hex
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = f"{doc_id}_{Path(filename).name}"
        path = KNOWLEDGE_DIR / safe_name
        path.write_bytes(content)

        from app.rag.milvus_store import add_documents

        if Path(filename).suffix.lower() == ".pdf":
            # 新版 PDF：先做版面分析，再按章节/段落重组，保留图片占位符和坐标元数据。
            structured_docs = parse_pdf_structured(content, filename)
            if structured_docs:
                ids = []
                for doc in structured_docs:
                    meta = {
                        "title": filename,
                        "doc_type": doc_type,
                        "kb_doc_id": doc_id,
                        "filename": filename,
                        **doc.metadata,
                    }
                    ids.extend(add_documents([doc.page_content], metadata=meta))
            else:
                text = extract_text(filename, content)
                if not text.strip():
                    raise ValueError("无法从文件中提取文本内容")
                ids = add_documents(_split_text(text), metadata={
                    "title": filename,
                    "doc_type": doc_type,
                    "kb_doc_id": doc_id,
                    "filename": filename,
                })
        else:
            text = extract_text(filename, content)
            if not text.strip():
                raise ValueError("无法从文件中提取文本内容")
            chunks = _split_text(text)
            vector_meta = {
                "title": filename,
                "doc_type": doc_type,
                "kb_doc_id": doc_id,
                "filename": filename,
            }
            ids = add_documents(chunks, metadata=vector_meta)

        doc = KnowledgeDoc(
            id=doc_id,
            title=filename,
            file_path=normalize_stored_path(path),
            md5=md5,
            doc_type=doc_type,
            milvus_ids=ids,
            status="ready",
        )
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def delete_doc(self, doc_id: str) -> bool:
        doc = await self.db.get(KnowledgeDoc, doc_id)
        if not doc:
            return False

        from app.rag.milvus_store import delete_by_ids, delete_by_kb_doc_id

        removed = 0
        if doc.milvus_ids:
            delete_by_ids(doc.milvus_ids)
            removed += len(doc.milvus_ids)
        removed += delete_by_kb_doc_id(doc_id)

        resolved = resolve_storage_path(doc.file_path)
        if resolved:
            resolved.unlink(missing_ok=True)
        await self.db.delete(doc)
        await self.db.flush()
        return True

    async def get_preview(self, doc_id: str) -> dict:
        doc = await self.db.get(KnowledgeDoc, doc_id)
        if not doc:
            raise ValueError("文档不存在")
        path = resolve_storage_path(doc.file_path)
        if not path or not path.exists():
            raise ValueError("文件已丢失")
        content = path.read_bytes()
        text = preview_text(doc.title, content)
        ext = Path(doc.title).suffix.lower()
        return {
            "id": doc.id,
            "title": doc.title,
            "doc_type": doc.doc_type,
            "extension": ext,
            "preview_text": text,
            "chunk_count": len(doc.milvus_ids or []),
            "file_size": len(content),
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }

    def doc_to_dict(self, doc: KnowledgeDoc) -> dict:
        path = resolve_storage_path(doc.file_path)
        return {
            "id": doc.id,
            "title": doc.title,
            "doc_type": doc.doc_type,
            "status": doc.status,
            "chunk_count": len(doc.milvus_ids or []),
            "file_size": path.stat().st_size if path and path.exists() else 0,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }
