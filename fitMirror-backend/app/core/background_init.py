"""应用启动后的后台预热任务（向量库连接等），不阻塞主请求。"""
import asyncio

from app.core.logger_handler import logger


class BackgroundInitManager:
    def __init__(self):
        self._ready = False

    async def start(self):
        asyncio.create_task(self._warmup())

    async def _warmup(self):
        try:
            from app.rag.milvus_store import get_vector_store

            get_vector_store()
            self._ready = True
            logger.info("Background init complete")
        except Exception as e:
            logger.warning("Background init partial: %s", e)
            self._ready = True


init_manager = BackgroundInitManager()
