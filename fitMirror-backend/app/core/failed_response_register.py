"""全局异常处理器注册：将 AppException 与未捕获异常转为统一 JSON 格式。"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.failed_response import AppException
from app.core.logger_handler import logger


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(_: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.code,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(_: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": str(exc), "data": None},
        )
