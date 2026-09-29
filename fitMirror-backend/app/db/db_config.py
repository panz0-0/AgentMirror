"""MySQL 异步数据库配置：引擎、会话工厂与 FastAPI Depends 注入。"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base

# Import all models so metadata is complete
from app.models import chat_history, knowledge_doc, sku  # noqa: F401

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DB_TYPE = os.getenv("DB_TYPE", "mysql").lower()
BACKEND_ROOT = Path(__file__).resolve().parents[2]

if DB_TYPE != "mysql":
    raise RuntimeError(
        f"fitMirror 已统一使用 MySQL，当前 DB_TYPE={DB_TYPE!r}。"
        "请在 fitMirror-backend/.env 中设置 DB_TYPE=mysql"
    )

ASYNC_DATABASE_URL = (
    f"mysql+aiomysql://{os.getenv('MYSQL_USER', 'root')}:{os.getenv('MYSQL_PASSWORD', '')}"
    f"@{os.getenv('MYSQL_HOST', 'localhost')}:{os.getenv('MYSQL_PORT', '3306')}"
    f"/{os.getenv('MYSQL_DATABASE', 'fitmirror')}?charset=utf8mb4"
)

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """FastAPI 依赖：请求结束时自动 commit，异常时 rollback。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_connection() -> bool:
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db_info() -> dict:
    return {
        "type": "mysql",
        "database": os.getenv("MYSQL_DATABASE", "fitmirror"),
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": os.getenv("MYSQL_PORT", "3306"),
    }
