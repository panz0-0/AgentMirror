# -*- coding: utf-8 -*-
"""
配置模块 — Config / ProductInput / load_config()

优先级: CLI 参数 > 环境变量 > .env 文件 > 默认值
"""

from __future__ import annotations

import dataclasses
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Config:
    """全局运行配置。优先级: CLI 参数 > 环境变量 > .env > 默认值。"""

    api_key: str = ""
    api_provider: str = "openai"        # openai | dashscope
    base_url: str = "https://api.openai.com/v1"
    dashscope_image_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    model_name: str = "gpt-4o"          # 统一文本 / vision 模型 (OpenAI compatible)
    vision_model: str = ""              # Stage1 视觉模型; 留空则回退 model_name
    text_model: str = ""                # Stage2/3 文本模型; 留空则回退 model_name
    image_model: str = "gpt-image-1"    # 图像生成模型
    # ── 多提供商支持：视觉 / 出图可独立指定 API Key 与 Base URL ──
    # 留空则回退到主 api_key / base_url (兼容单提供商配置)
    vision_api_key: str = ""
    vision_base_url: str = ""
    image_api_key: str = ""
    image_base_url: str = ""
    output_root: str = "output"
    request_timeout: float = 600.0   # LLM 请求超时 (Stage3 大上下文可能 200s+)
    max_retries: int = 3                # >= 2
    retry_backoff: float = 2.0
    concurrency: int = 6                # 图片并发 (可通过 .env CONCURRENCY 调整)
    enable_generate_images: bool = True
    use_prompt_cache: bool = True
    force: bool = False                 # 忽略已有结果重新生成
    generation_mode: str = "full"       # "full" | "hero" | "detail" | "lookbook"
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        # vision / text 模型默认回退到统一 model_name
        if not self.vision_model:
            self.vision_model = self.model_name
        if not self.text_model:
            self.text_model = self.model_name

    def masked(self) -> dict:
        """返回脱敏后的配置 dict (隐藏 API Key 中间部分)。"""
        d = dataclasses.asdict(self)
        if d.get("api_key"):
            k = d["api_key"]
            d["api_key"] = f"{k[:4]}***{k[-4:]}" if len(k) > 8 else "***"
        return d


@dataclass
class ProductInput:
    """单个 SKU 的输入信息 (CLI / Web / 批处理共用)。"""

    sku: str
    image: str                      # 本地路径 / http(s) url / data url
    category: str = ""              # 类目
    style: str = ""                 # 风格
    model_attrs: str = ""           # 模特属性 (如 "亚洲女性, 25岁, 微笑")
    additional_requirements: str = ""  # 用户额外需求 (多行文本, 全程参与 prompt 生成)
    platform: str = ""              # 投放平台 (如 "淘宝" / "Amazon")
    language: str = ""              # 图片内文字语言 (如 "中文" / "English")
    model_scene: str = ""           # 模特拍摄场景 (如 "居家" / "街头" / "办公")
    shooting_style: str = ""        # 拍摄方式 (如 "棚拍" / "抓拍" / "自拍")
    face_visible: str = "show"      # 是否露脸 "show" | "hide"

    def safe_sku(self) -> str:
        """清洗 SKU 为安全目录名。"""
        name = re.sub(r"[^\w\-.]+", "_", self.sku.strip()) or "SKU"
        return name.strip("_.") or "SKU"


def _project_root() -> Path:
    """fitMirror-backend 根目录 (读取 .env)。"""
    return Path(__file__).resolve().parents[2]


def _load_dotenv(path: str | Path | None = None) -> dict[str, str]:
    """极简 .env 解析 (无第三方依赖)。

    默认从项目根目录读取 .env, 不依赖进程当前工作目录 (兼容 PyCharm 调试)。
    """
    data: dict[str, str] = {}
    p = Path(path) if path is not None else _project_root() / ".env"
    if not p.is_absolute():
        p = _project_root() / p
    if not p.exists():
        return data
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        data[key.strip()] = val
    return data


def load_config() -> Config:
    """从 .env 文件和环境变量加载配置。

    优先级: 环境变量 > .env > 默认值

    Returns:
        合并后的 Config 实例。
    """
    env_file = _load_dotenv()

    def pick(*keys: str, default: Any = None) -> Any:
        # 真实环境变量优先
        for k in keys:
            ek = k.upper()
            if os.environ.get(ek) not in (None, ""):
                return os.environ[ek]
        # .env 文件
        for k in keys:
            ek = k.upper()
            if env_file.get(ek) not in (None, ""):
                return env_file[ek]
        return default

    cfg = Config()
    cfg.api_key = pick(
        "api_key", "openai_api_key", "dashscope_api_key", default=cfg.api_key,
    )
    cfg.api_provider = str(pick("api_provider", default=cfg.api_provider)).lower()
    cfg.base_url = pick("base_url", default=cfg.base_url)
    cfg.dashscope_image_url = pick("dashscope_image_url", default=cfg.dashscope_image_url)
    cfg.model_name = pick("model_name", "model", default=cfg.model_name)
    cfg.vision_model = pick("vision_model", default="") or cfg.model_name
    cfg.text_model = pick("text_model", default="") or cfg.model_name
    cfg.image_model = pick("image_model", default=cfg.image_model)
    # 多提供商：视觉 / 出图独立凭证；留空回退主 api_key / base_url
    cfg.vision_api_key = pick("vision_api_key", default="") or cfg.api_key
    cfg.vision_base_url = pick("vision_base_url", default="") or cfg.base_url
    cfg.image_api_key = pick("image_api_key", default="") or cfg.api_key
    cfg.image_base_url = pick("image_base_url", default="") or cfg.base_url
    cfg.output_root = pick("output_root", "output", default=cfg.output_root)
    cfg.request_timeout = float(pick("request_timeout", default=cfg.request_timeout))
    cfg.max_retries = max(2, int(pick("max_retries", default=cfg.max_retries)))
    cfg.retry_backoff = float(pick("retry_backoff", default=cfg.retry_backoff))
    cfg.concurrency = max(1, int(pick("concurrency", default=cfg.concurrency)))
    cfg.log_level = str(pick("log_level", default=cfg.log_level)).upper()
    cfg.force = pick("force", default="false").lower() in ("true", "1", "yes")
    cfg.use_prompt_cache = pick("use_prompt_cache", "no_cache", default="true").lower() not in ("false", "0", "no")
    cfg.generation_mode = pick("generation_mode", default=cfg.generation_mode)

    return cfg
