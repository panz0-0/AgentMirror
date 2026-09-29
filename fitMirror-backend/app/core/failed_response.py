"""统一 API 错误响应与业务异常 AppException。"""
from fastapi import HTTPException
from fastapi.responses import JSONResponse


class AppException(HTTPException):
    def __init__(self, message: str, code: int = 400):
        super().__init__(status_code=code, detail=message)
        self.message = message
        self.code = code


def failed_response(message: str, code: int = 400) -> JSONResponse:
    return JSONResponse(content={"code": code, "message": message, "data": None})
