"""演示环境快照：导出 / 导入 MySQL 数据（配合仓库内 storage/ 使用）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_history import ChatMessage, ChatSession, UserProfile
from app.models.knowledge_doc import KnowledgeDoc
from app.models.sku import GeneratedImage, GenerationJob, Sku, SkuArtifact

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = BACKEND_ROOT / "seed" / "snapshot" / "demo_db.json"

TABLE_MODELS: list[tuple[str, Any]] = [
    ("skus", Sku),
    ("sku_artifacts", SkuArtifact),
    ("generation_jobs", GenerationJob),
    ("generated_images", GeneratedImage),
    ("knowledge_docs", KnowledgeDoc),
    ("chat_sessions", ChatSession),
    ("chat_messages", ChatMessage),
    ("user_profiles", UserProfile),
]

CLEAR_ORDER = [name for name, _ in reversed(TABLE_MODELS)]


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def model_to_dict(obj: Any) -> dict:
    data: dict[str, Any] = {}
    for attr in inspect(obj).mapper.column_attrs:
        col_name = attr.columns[0].name
        data[col_name] = _serialize(getattr(obj, attr.key))
    return data


def dict_to_model(model: Any, data: dict) -> dict:
    kwargs = {}
    for col in model.__table__.columns:
        if col.name in data:
            kwargs[col.key] = data[col.name]
    return kwargs


async def export_snapshot(db: AsyncSession, path: Path = SNAPSHOT_PATH) -> dict[str, int]:
    payload: dict[str, Any] = {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "tables": {},
    }
    counts: dict[str, int] = {}
    for name, model in TABLE_MODELS:
        result = await db.execute(select(model))
        rows = [model_to_dict(row) for row in result.scalars().all()]
        payload["tables"][name] = rows
        counts[name] = len(rows)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts


async def import_snapshot(db: AsyncSession, path: Path = SNAPSHOT_PATH) -> dict[str, int]:
    if not path.exists():
        raise FileNotFoundError(f"快照不存在: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    tables: dict[str, list] = payload.get("tables") or {}

    await db.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    for name in CLEAR_ORDER:
        model = next(m for n, m in TABLE_MODELS if n == name)
        await db.execute(delete(model))
    await db.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    counts: dict[str, int] = {}
    for name, model in TABLE_MODELS:
        rows = tables.get(name) or []
        for row in rows:
            db.add(model(**dict_to_model(model, row)))
        counts[name] = len(rows)
        await db.flush()

    return counts


def storage_summary() -> dict[str, Any]:
    storage = BACKEND_ROOT / "storage"
    if not storage.exists():
        return {"exists": False, "files": 0, "size_mb": 0}

    files = list(storage.rglob("*"))
    file_list = [p for p in files if p.is_file()]
    total = sum(p.stat().st_size for p in file_list)
    return {
        "exists": True,
        "files": len(file_list),
        "size_mb": round(total / (1024 * 1024), 2),
        "dirs": sorted({p.relative_to(storage).parts[0] for p in file_list if p.relative_to(storage).parts}),
    }
