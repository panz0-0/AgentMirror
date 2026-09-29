"""SKU 数据库记录与 pipeline ProductInput / Config 之间的桥接转换。"""
import os
from pathlib import Path

from dotenv import load_dotenv

from app.pipeline.config import Config, ProductInput, load_config
from app.models.sku import Sku
from app.utils.path_tool import path_exists, resolve_storage_path, sku_workspace_dir

load_dotenv()
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def build_pipeline_config(
    *,
    output_root: str | Path | None = None,
    generation_mode: str = "hero",
    force: bool = False,
    enable_images: bool = True,
) -> Config:
    """使用 PrismPix 同款 .env 变量（load_config）。"""
    cfg = load_config()
    if output_root:
        cfg.output_root = str(output_root)
    else:
        cfg.output_root = os.getenv("OUTPUT_ROOT", str(BACKEND_ROOT / "storage" / "workspaces"))
    cfg.generation_mode = generation_mode
    cfg.force = force
    cfg.enable_generate_images = enable_images
    return cfg


def sku_to_product_input(sku: Sku, workspace: Path | None = None) -> ProductInput:
    """将 Sku ORM 对象转为流水线输入，源图优先用 source_image_path，回退 workspace/original.png。"""
    ws = workspace or sku_workspace_dir(sku.id)
    image_path = resolve_storage_path(sku.source_image_path)
    if not image_path or not image_path.exists():
        alt = ws / "original.png"
        if alt.exists():
            image_path = alt
    return ProductInput(
        sku=sku.id,
        image=str(image_path) if image_path else "",
        category=sku.category,
        style=sku.style,
        model_attrs=sku.model_attrs,
        additional_requirements=sku.additional_requirements,
        platform=sku.platform,
        language=sku.language,
        model_scene=sku.model_scene,
        shooting_style=sku.shooting_style,
        face_visible=sku.face_visible,
    )
