"""
一键恢复完整演示环境（推荐新用户使用）

- 创建 MySQL 表结构
- 导入 seed/snapshot/demo_db.json（SKU、知识库、客服会话、生成任务等）
- 使用仓库内已附带的 storage/（商品图、生成图、workspace、向量索引）

用法:
  cd fitMirror-backend
  cp .env.example .env    # 配置 MYSQL_* 与 LLM Key
  uv run python scripts/restore_demo_environment.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from app.db.db_config import AsyncSessionLocal, check_db_connection, get_db_info, init_db
from app.utils.path_tool import ensure_storage_dirs
from scripts.demo_snapshot import SNAPSHOT_PATH, import_snapshot, storage_summary


async def main(force: bool = False):
    info = get_db_info()
    print(f"=== 恢复演示环境 ({info['type']} / {info['database']}) ===")

    if not await check_db_connection():
        print("数据库连接失败，请检查 .env 中 MySQL 配置")
        sys.exit(1)

    if not SNAPSHOT_PATH.exists():
        print(f"缺少快照文件: {SNAPSHOT_PATH}")
        print("维护者可运行: uv run python scripts/export_demo_snapshot.py")
        sys.exit(1)

    store = storage_summary()
    if not store.get("exists") or store.get("files", 0) == 0:
        print("警告: storage/ 目录为空，图片与生成结果可能无法展示。")
    else:
        print(f"storage/: {store['files']} 个文件, {store['size_mb']} MB ({', '.join(store.get('dirs', []))})")

    if not force:
        print("\n将清空并重建当前数据库中的演示表数据，继续请 5 秒内按 Ctrl+C 取消...")
        await asyncio.sleep(5)

    ensure_storage_dirs()
    await init_db()

    async with AsyncSessionLocal() as db:
        counts = await import_snapshot(db)
        await db.commit()

    print("\n恢复完成:")
    for name, n in counts.items():
        print(f"  {name}: {n}")
    print("\n下一步:")
    print("  uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload")
    print("  cd ../frontend && npm install && npm run dev")
    print("  浏览器打开 http://localhost:5173/chat")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="恢复 fitMirror 完整演示环境")
    parser.add_argument("--force", action="store_true", help="跳过 5 秒确认")
    args = parser.parse_args()
    asyncio.run(main(force=args.force))
