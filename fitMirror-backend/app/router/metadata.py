"""运营工作台静态表单元数据 API（类目、平台、语言等下拉选项）。"""
"""运营工作台静态表单元数据 API（类目、平台、语言等下拉选项）。"""
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter

from app.core.success_response import success_response

metadata_router = APIRouter(prefix="/api/metadata", tags=["metadata"])

META_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "metadata"


@metadata_router.get(
    "",
    summary="运营表单元数据",
    description=(
        "返回运营工作台表单所需的静态选项：类目下拉、平台、语言、人种等。"
        "数据来自 `app/pipeline/metadata/*.json`。"
    ),
)
async def get_metadata():
    data = {}
    for name in ("dropdowns", "platforms", "languages", "ethnicities"):
        p = META_DIR / f"{name}.json"
        if p.exists():
            data[name] = json.loads(p.read_text(encoding="utf-8"))
    return success_response(data=data)
