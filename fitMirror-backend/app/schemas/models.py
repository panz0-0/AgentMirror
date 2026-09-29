"""API 请求/响应 Pydantic 模型，Field description 用于 Swagger 文档生成。"""
from pydantic import BaseModel, Field


class SkuCreateResponse(BaseModel):
    id: str = Field(description="SKU 主键 UUID")
    sku_code: str = Field(description="货号，如 DRESS-001")


class GenerationStartRequest(BaseModel):
    sku_id: str = Field(description="要生成视觉资产的 SKU ID")
    mode: str = Field(default="hero", description="出图模式：hero / detail / lookbook / full")
    stop_at: str = Field(
        default="campaign",
        description="流水线暂停节点：stage1 / campaign / prompts / images",
    )


class GenerationResumeRequest(BaseModel):
    job_id: str = Field(description="生成任务 ID")
    action: str = Field(
        default="confirm",
        description="恢复动作：confirm（确认后继续）/ regenerate（重新生成当前阶段）",
    )


class GenerationEnsureRequest(BaseModel):
    sku_id: str = Field(description="SKU ID")
    node: str = Field(default="campaign", description="期望暂停的节点：campaign / prompts")
    mode: str = Field(default="hero", description="出图模式")


class ChatSessionCreate(BaseModel):
    user_id: str = Field(default="guest", description="用户标识，演示环境默认 guest")
    title: str = Field(default="新的对话", description="会话标题，首条消息后会自动更新")


class ChatMessageRequest(BaseModel):
    session_id: str = Field(description="会话 ID")
    user_id: str = Field(default="guest", description="用户标识")
    content: str = Field(description="用户文本消息，支持商品咨询、FAQ、试穿等自然语言")


class UserProfileUpdate(BaseModel):
    user_id: str = Field(default="guest", description="用户标识")
    height_cm: float | None = Field(default=None, description="身高（cm），用于虚拟试穿")
    weight_kg: float | None = Field(default=None, description="体重（kg），用于虚拟试穿")
