"""
从当前 MySQL 导出演示快照到 seed/snapshot/demo_db.json
用法: cd fitMirror-backend && uv run python scripts/export_demo_snapshot.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from app.db.db_config import AsyncSessionLocal, check_db_connection, get_db_info
from scripts.demo_snapshot import SNAPSHOT_PATH, export_snapshot, storage_summary


async def main():
    info = get_db_info()
    print(f"=== 导出演示快照 ({info['type']} / {info['database']}) ===")
    if not await check_db_connection():
        print("数据库连接失败")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        counts = await export_snapshot(db)
        await db.commit()

    store = storage_summary()
    print(f"\n已写入: {SNAPSHOT_PATH}")
    for name, n in counts.items():
        print(f"  {name}: {n}")
    print(f"\nstorage/: {store.get('files', 0)} 个文件, {store.get('size_mb', 0)} MB")
    print("请将 storage/ 与 seed/snapshot/demo_db.json 一并提交到仓库。")


if __name__ == "__main__":
    asyncio.run(main())
