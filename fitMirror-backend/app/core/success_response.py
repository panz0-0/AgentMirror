"""统一 API 成功响应封装：{code: 200, message, data}。"""
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def success_response(message: str = "success", data=None) -> JSONResponse:
    return JSONResponse(
        content=jsonable_encoder({"code": 200, "message": message, "data": data}),
        media_type="application/json; charset=utf-8",
    )
