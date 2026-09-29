"""
初始化 MySQL 数据库表结构并导入演示数据。
用法: cd fitMirror-backend && uv run python scripts/init_mysql.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from app.db.db_config import AsyncSessionLocal, get_db_info, init_db, check_db_connection
from scripts.seed_demo_data import seed_knowledge, seed_skus


async def main():
    info = get_db_info()
    print(f"=== 初始化数据库 ({info['type']} / {info['database']}) ===")
    ok = await check_db_connection()
    if not ok:
        print("数据库连接失败，请检查 .env 中 MySQL 配置")
        sys.exit(1)
    await init_db()
    async with AsyncSessionLocal() as db:
        print("\n[1] SKU 演示数据...")
        sku_n = await seed_skus(db, refresh_images=True)
        print("\n[2] 知识库...")
        kb_n = await seed_knowledge(db)
        await db.commit()
    print(f"\n完成: SKU {sku_n} 个, 知识库 {kb_n} 个")


if __name__ == "__main__":
    asyncio.run(main())
