"""将数据库中的绝对路径迁移为相对路径（相对 fitMirror-backend 根目录）。"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal
from app.models.knowledge_doc import KnowledgeDoc
from app.models.sku import GeneratedImage, Sku, SkuArtifact
from app.utils.path_tool import normalize_stored_path, path_exists

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _migrate_value(old: str) -> tuple[str, bool]:
    if not old:
        return old, False
    new = normalize_stored_path(old)
    return new, new != old


async def main() -> None:
    changed = 0
    async with AsyncSessionLocal() as db:
        for sku in (await db.execute(select(Sku))).scalars():
            new_path, ok = _migrate_value(sku.source_image_path or "")
            if ok:
                sku.source_image_path = new_path
                changed += 1
                print(f"sku {sku.sku_code} image: {new_path}")

            meta = dict(sku.metadata_ or {})
            if meta.get("workspace"):
                new_ws, ok2 = _migrate_value(str(meta["workspace"]))
                if ok2:
                    meta["workspace"] = new_ws
                    sku.metadata_ = meta
                    changed += 1
                    print(f"sku {sku.sku_code} workspace meta: {new_ws}")

        for art in (await db.execute(select(SkuArtifact))).scalars():
            new_path, ok = _migrate_value(art.file_path or "")
            if ok:
                art.file_path = new_path
                changed += 1
                print(f"artifact sku={art.sku_id} stage={art.stage}: {new_path}")

        for img in (await db.execute(select(GeneratedImage))).scalars():
            new_path, ok = _migrate_value(img.file_path or "")
            if ok:
                img.file_path = new_path
                changed += 1
                print(f"generated_image {img.image_code}: {new_path}")

        for doc in (await db.execute(select(KnowledgeDoc))).scalars():
            new_path, ok = _migrate_value(doc.file_path or "")
            if ok:
                doc.file_path = new_path
                changed += 1
                print(f"knowledge {doc.title}: {new_path}")

        await db.commit()

    print(f"\nMigration done. Updated {changed} records.")

    # 验证
    async with AsyncSessionLocal() as db:
        skus = list((await db.execute(select(Sku))).scalars())
        missing = 0
        for sku in skus:
            if sku.source_image_path and not path_exists(sku.source_image_path):
                missing += 1
                print(f"WARN missing image: {sku.sku_code} -> {sku.source_image_path}")
        print(f"Verify: {len(skus)} skus, {missing} missing source images")


if __name__ == "__main__":
    asyncio.run(main())
