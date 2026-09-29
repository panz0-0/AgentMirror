# -*- coding: utf-8 -*-
"""完整 lookbook 流程测试：输入商品图 → 视觉分析 → 营销策略 → 5条prompt → 三面参考图 → 5张模特套图。"""
import json
import sys
from pathlib import Path

# 确保项目根目录在 path
sys.path.insert(0, str(Path(__file__).parent))

from app.pipeline.config import load_config, ProductInput
from app.pipeline.runner import run_sku

# ── 配置 ──
cfg = load_config()
cfg.generation_mode = "lookbook"      # 模特套图模式
cfg.enable_generate_images = True       # 开启出图
cfg.force = True                        # 强制重新生成，不用缓存
cfg.concurrency = 2                     # 并发数

# ── 输入：用 SPORT-001.png 演示（可换成你自己的鞋子图片）──
img_path = Path(__file__).parent / "seed" / "images" / "SPORT-001.png"
product_input = ProductInput(
    sku="SHOE-TEST-001",
    image=str(img_path),
    category="运动鞋",
    style="运动休闲",
    model_attrs="East Asian, Female, 20-30, Fair skin, Slim build",
    model_scene="简约白色工作室背景",
    shooting_style="时尚电商棚拍",
    face_visible="show",
)

print("=" * 70)
print("fitMirror Lookbook 全流程测试")
print("=" * 70)
print(f"输入图片: {img_path.name}")
print(f"类目: {product_input.category}")
print(f"模特: {product_input.model_attrs}")
print(f"场景: {product_input.model_scene}")
print(f"出图模式: {cfg.generation_mode}")
print("=" * 70)

# ── 执行全流程 ──
result = run_sku(cfg, product_input)

print("\n" + "=" * 70)
print("执行完成！结果摘要:")
print("=" * 70)
print(json.dumps(result, ensure_ascii=False, indent=2))

# ── 列出生成的文件 ──
ws = Path(result["workspace"])
print("\n生成的文件:")
for f in sorted(ws.iterdir()):
    if f.is_file():
        print(f"  {f.name:30s} {f.stat().st_size:>10,d} bytes")
