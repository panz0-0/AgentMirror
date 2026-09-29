import asyncio
from app.db.db_config import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text(
            "SELECT id, content FROM chat_messages "
            "WHERE role='user' ORDER BY created_at DESC LIMIT 5"
        ))
        for row in r.fetchall():
            content = row[1]
            print(f"id={row[0]} content={content!r}")
            # 尝试把乱码转回 UTF-8
            try:
                fixed = content.encode('gbk').decode('utf-8')
                print(f"  -> fixed: {fixed}")
            except Exception as e:
                print(f"  -> cannot fix: {e}")

asyncio.run(main())
