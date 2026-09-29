"""AI 客服会话、消息与用户身材档案表定义。"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, Integer, String, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ChatSession(Base):
    """客服对话会话：左侧会话列表一条记录。"""
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    # 用户标识，演示环境默认 guest；删除会话时校验归属
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="guest")
    # 会话标题，首条消息后自动截取用户文本前 20 字
    title: Mapped[str] = mapped_column(String(255), default="新的对话")
    # 会话级扩展 JSON（库列名 metadata），当前业务较少使用
    metadata_: Mapped[dict | None] = mapped_column(JSON, name="metadata", default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    """单条聊天消息：用户提问或 AI 回复，含前端渲染用的 metadata。"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("chat_sessions.id"))
    # 发言方：user / assistant（历史数据可能含 human / ai）
    role: Mapped[str] = mapped_column(String(32))
    # 消息正文，纯文本或 Markdown；图片消息可能是「[图片]」
    content: Mapped[str] = mapped_column(Text)
    # 前端卡片数据（库列名 metadata），ORM 用 metadata_ 避免与 SQLAlchemy 保留名冲突
    # type 常见值：text / faq / catalog / product_intro / product_match /
    #              similar_product / tryon_result / image / action
    # 另可含 sku_id、image_url、actions（按钮）、gallery_urls 等
    metadata_: Mapped[dict | None] = mapped_column(JSON, name="metadata", default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")


class UserProfile(Base):
    """用户身材档案：虚拟试穿与尺码推荐时优先使用。"""
    __tablename__ = "user_profiles"

    # 与 chat_sessions.user_id 对应，作主键（一个用户一条档案）
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 身高（厘米），LangGraph 试穿流程可从对话中自动提取并回写
    height_cm: Mapped[float | None] = mapped_column(default=None)
    # 体重（千克）
    weight_kg: Mapped[float | None] = mapped_column(default=None)
    # 预留偏好 JSON，当前业务未深度使用
    preferences_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
