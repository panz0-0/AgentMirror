"""SKU 与视觉生成相关的数据库表定义。"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Sku(Base):
    """商品 SKU 主表：运营台录入的商品信息与拍摄参数。"""
    __tablename__ = "skus"

    # 主键 UUID，同时作为 workspace 目录名（storage/workspaces/{id}/）
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    # 货号，全局唯一，如 DRESS-001；客服文本匹配、商品卡片展示用
    sku_code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # 商品展示名称，如「碎花连衣裙」
    name: Mapped[str] = mapped_column(String(255), default="")
    # 类目，可多级「女装/连衣裙」；客服目录按一级类目分组
    category: Mapped[str] = mapped_column(String(255), default="")
    # 风格标签，如「法式」「碎花」；相似款推荐时会参考
    style: Mapped[str] = mapped_column(String(255), default="")
    # 商品价格（元），客服商品介绍与价格查询时展示
    price: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    # 目标电商平台：淘宝 / 京东 / 抖音 等，影响 Stage2 文案语气
    platform: Mapped[str] = mapped_column(String(64), default="淘宝")
    # 出图文案语言：中文 / 英文
    language: Mapped[str] = mapped_column(String(32), default="中文")
    # 参考模特描述，如「身高168cm 体重52kg」；无用户档案时试穿默认身材来源
    model_attrs: Mapped[str] = mapped_column(Text, default="")
    # 运营额外拍摄要求，会拼进流水线提示词
    additional_requirements: Mapped[str] = mapped_column(Text, default="")
    # 模特场景：居家 / 户外 / 街拍 等
    model_scene: Mapped[str] = mapped_column(String(64), default="居家")
    # 拍摄方式：棚拍 / 外景 等
    shooting_style: Mapped[str] = mapped_column(String(64), default="棚拍")
    # 模特是否露脸：show / hide，影响出图提示词
    face_visible: Mapped[str] = mapped_column(String(16), default="show")
    # 商品主图相对路径（storage/uploads/{id}/original.png）；发图识货、dHash 来源
    source_image_path: Mapped[str] = mapped_column(String(512), default="")
    # 流水线整体进度：draft → analyzed → ready → generated
    status: Mapped[str] = mapped_column(String(32), default="draft")
    # JSON 扩展字段（库列名 metadata）；常用 image_hash（dHash）、workspace 路径等
    metadata_: Mapped[dict | None] = mapped_column(JSON, name="metadata", default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 关联：该 SKU 各阶段产物文件记录
    artifacts = relationship("SkuArtifact", back_populates="sku", cascade="all, delete-orphan")
    # 关联：该 SKU 历次生成任务
    jobs = relationship("GenerationJob", back_populates="sku", cascade="all, delete-orphan")


class SkuArtifact(Base):
    """流水线阶段产物索引：记录 product/campaign/prompts JSON 文件路径。"""
    __tablename__ = "sku_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sku_id: Mapped[str] = mapped_column(String(64), ForeignKey("skus.id"), index=True)
    # 阶段编号：1=product.json  2=campaign.json  3=prompts.json
    stage: Mapped[int] = mapped_column()
    # 产物文件相对路径，与 workspace 目录下 JSON 对应
    file_path: Mapped[str] = mapped_column(String(512))
    # 同阶段重复生成时递增，当前业务多为 1
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sku = relationship("Sku", back_populates="artifacts")


class GenerationJob(Base):
    """视觉生成任务：跟踪运营流水线执行到哪一步、是否暂停等待确认。"""
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    sku_id: Mapped[str] = mapped_column(String(64), ForeignKey("skus.id"), index=True)
    # 任务类型，当前固定 ops（运营台流水线）
    job_type: Mapped[str] = mapped_column(String(16), default="ops")
    # 出图模式：hero（主图）/ detail / lookbook / full，决定生成哪些 H/D/M 模块
    mode: Mapped[str] = mapped_column(String(32), default="hero")
    # 任务状态：pending → running → paused（等人确认）→ done / failed
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # LangGraph 会话线程 ID，当前与 sku_id 相同，用于恢复图状态
    graph_thread_id: Mapped[str] = mapped_column(String(64), default="")
    # 当前停在哪一步：stage1 / campaign / prompts / images / done
    current_node: Mapped[str] = mapped_column(String(64), default="")
    # 进度快照 JSON，如 {stage, awaiting_confirm, done, total}；持久化供运营台轮询
    progress_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    # 失败时的错误信息
    error_msg: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 任务完成时间，done 时写入
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    sku = relationship("Sku", back_populates="jobs")
    images = relationship("GeneratedImage", back_populates="job", cascade="all, delete-orphan")


class GeneratedImage(Base):
    """单张 AI 生成图片记录，与 workspace 里 H1.png / M2.png 等文件一一对应。"""
    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("generation_jobs.id"), index=True)
    sku_id: Mapped[str] = mapped_column(String(64), index=True)
    # 图片编号：H1-H5 主图、D1-D9 细节、M1-M5 模特上身、product_ref 参考图
    image_code: Mapped[str] = mapped_column(String(16))
    # PNG 文件相对路径，访问 URL 为 /api/images/{job_id}/{image_code}
    file_path: Mapped[str] = mapped_column(String(512))
    # 出图时使用的提示词快照，便于运营复盘（可选）
    prompt_snapshot: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job = relationship("GenerationJob", back_populates="images")
