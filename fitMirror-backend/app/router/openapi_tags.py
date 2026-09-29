"""OpenAPI / Swagger 文档标签与全局说明。"""

API_TAGS = [
    {
        "name": "health",
        "description": "健康检查：数据库连通性、LLM 配置状态。",
    },
    {
        "name": "chat",
        "description": (
            "AI 客服对话：会话管理、文本/图文消息、商品介绍、虚拟试穿、"
            "商品目录、用户身材档案。基于 LangGraph 意图路由与 RAG。"
        ),
    },
    {
        "name": "sku",
        "description": "SKU 商品管理：CRUD、商品原图、试穿效果图、workspace 流水线数据。",
    },
    {
        "name": "generation",
        "description": (
            "运营视觉生成流水线：启动/恢复 Stage1~3 分析、营销策略、提示词与出图任务，"
            "支持 SSE 进度流式推送。"
        ),
    },
    {
        "name": "knowledge",
        "description": "知识库：上传 FAQ/话术/政策/商品说明，向量索引与预览下载。",
    },
    {
        "name": "metadata",
        "description": "运营表单元数据：类目、平台、语言、人种等下拉选项。",
    },
    {
        "name": "images",
        "description": "生成任务产出图片访问（按 job_id + 图片编码）。",
    },
]

API_DESCRIPTION = """
## fitMirror API

面向电商场景的 AI 全链路服务：**虚拟试穿客服** + **运营视觉生成工作台**。

### 统一响应格式

```json
{"code": 200, "message": "success", "data": {...}}
```

### 模块说明

| 前缀 | 用途 |
|------|------|
| `/api/chat` | AI 客服对话、试穿、商品目录 |
| `/api/sku` | 商品 SKU 管理 |
| `/api/generation` | 运营 AIGC 流水线 |
| `/api/knowledge` | RAG 知识库 |
| `/api/metadata` | 表单元数据 |
| `/api/health` | 健康检查 |

### 认证

当前为本地演示环境，接口无登录鉴权。生产部署请自行增加认证层。
"""
