"""【已废弃】早期合并版 ORM 定义，与 sku.py / chat_history.py / knowledge_doc.py 重复。

当前项目未引用本文件，实际建表以 app/models/sku.py 等拆分文件为准。
保留仅供对照，后续可删除。
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# noqa: 以下类定义已迁移至独立模块，请勿在新代码中 import 本文件


class Sku(Base):
    __tablename__ = "skus"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    sku_code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(128), default="")
    style: Mapped[str] = mapped_column(String(255), default="")
    platform: Mapped[str] = mapped_column(String(64), default="淘宝")
    language: Mapped[str] = mapped_column(String(32), default="中文")
    model_attrs: Mapped[str] = mapped_column(Text, default="")
    additional_requirements: Mapped[str] = mapped_column(Text, default="")
    model_scene: Mapped[str] = mapped_column(String(64), default="居家")
    shooting_style: Mapped[str] = mapped_column(String(64), default="棚拍")
    face_visible: Mapped[str] = mapped_column(String(16), default="show")
    source_image_path: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    metadata_: Mapped[dict | None] = mapped_column(JSON, name="metadata", default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    artifacts: Mapped[list["SkuArtifact"]] = relationship(back_populates="sku", cascade="all, delete-orphan")
    jobs: Mapped[list["GenerationJob"]] = relationship(back_populates="sku", cascade="all, delete-orphan")


class SkuArtifact(Base):
    __tablename__ = "sku_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_id: Mapped[str] = mapped_column(String(64), ForeignKey("skus.id"), index=True)
    stage: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(512))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sku: Mapped["Sku"] = relationship(back_populates="artifacts")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    sku_id: Mapped[str] = mapped_column(String(64), ForeignKey("skus.id"), index=True)
    job_type: Mapped[str] = mapped_column(String(32), default="ops")
    mode: Mapped[str] = mapped_column(String(32), default="hero")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    graph_thread_id: Mapped[str] = mapped_column(String(64), default="")
    current_node: Mapped[str] = mapped_column(String(64), default="")
    progress_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    error_msg: Mapped[str | None] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sku: Mapped["Sku"] = relationship(back_populates="jobs")
    images: Mapped[list["GeneratedImage"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("generation_jobs.id"), index=True)
    sku_id: Mapped[str] = mapped_column(String(64), ForeignKey("skus.id"), index=True)
    image_code: Mapped[str] = mapped_column(String(16))
    file_path: Mapped[str] = mapped_column(String(512))
    prompt_snapshot: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped["GenerationJob"] = relationship(back_populates="images")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="guest")
    title: Mapped[str] = mapped_column(String(255), default="新的对话")
    metadata_: Mapped[dict | None] = mapped_column(JSON, name="metadata", default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column(JSON, name="metadata", default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    height_cm: Mapped[float | None] = mapped_column(nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    preferences_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    md5: Mapped[str] = mapped_column(String(64), index=True)
    doc_type: Mapped[str] = mapped_column(String(32), default="faq")
    status: Mapped[str] = mapped_column(String(32), default="active")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
