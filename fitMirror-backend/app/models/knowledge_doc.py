"""知识库文档表：上传的 FAQ/政策/话术等文件元数据，与向量索引关联。"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KnowledgeDoc(Base):
    """知识库文档一条记录，对应 storage/knowledge/ 下的一个文件。"""
    __tablename__ = "knowledge_docs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    # 原始文件名，列表展示与预览用
    title: Mapped[str] = mapped_column(String(255))
    # 磁盘相对路径，如 storage/knowledge/{id}_{filename}
    file_path: Mapped[str] = mapped_column(String(512))
    # 文件内容 MD5，上传时去重（相同内容拒绝重复入库）
    md5: Mapped[str] = mapped_column(String(64), index=True)
    # 文档分类：faq（常见问题）/ script（客服话术）/ policy（政策）/ product（商品说明）
    doc_type: Mapped[str] = mapped_column(String(32), default="faq")
    # 分块向量化后写入向量库的 ID 列表；删除文档时用来清理索引
    milvus_ids: Mapped[list | None] = mapped_column(JSON, default=list)
    # 处理状态，当前上传成功即为 ready
    status: Mapped[str] = mapped_column(String(32), default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
