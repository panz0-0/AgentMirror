"""知识库文档解析 — 支持 txt / md / pdf / docx"""

from __future__ import annotations

from pathlib import Path

# 旧版 PDF 处理方式保留：_extract_pdf 仍作为兼容回退，不删除。
# 新版结构感知解析器位于 app.rag.pdf_structured_parser。


def extract_text(filename: str, content: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md", ".markdown"):
        return content.decode("utf-8", errors="ignore")
    if ext == ".pdf":
        return _extract_pdf(content)
    if ext in (".docx", ".doc"):
        return _extract_docx(content)
    return content.decode("utf-8", errors="ignore")


def _extract_pdf(content: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    parts = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    return "\n\n".join(parts) or "[PDF 无文本内容]"


def _extract_docx(content: bytes) -> str:
    import io

    from docx import Document

    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip()) or "[DOCX 无文本内容]"


def preview_text(filename: str, content: bytes, max_chars: int = 8000) -> str:
    text = extract_text(filename, content)
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n... (内容已截断，完整内容请下载原文件)"
    return text
