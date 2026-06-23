"""v3.0.0 RFC 7807 Problem Details 错误格式。

为 /api/v3/* 端点提供 application/problem+json 错误响应。
为旧端点（/api/*、/upload/、/delete/ 等）保持原 HTTPException 行为，向后兼容。
"""
from __future__ import annotations
import time
import uuid
from fastapi import Request
from fastapi.responses import JSONResponse


_ERROR_BASE = "https://room.example/errors"


def problem(status: int, title: str, detail: str = "",
            type_suffix: str | None = None,
            headers: dict | None = None) -> JSONResponse:
    """构造一个 RFC 7807 响应。type_suffix 拼到 type URL 末尾。"""
    if type_suffix is None:
        # 常见类型映射
        suffix_map = {400: "bad-request", 401: "unauthorized", 403: "forbidden",
                      404: "not-found", 409: "conflict", 422: "unprocessable",
                      429: "too-many-requests", 500: "internal", 503: "unavailable"}
        type_suffix = suffix_map.get(status, "error")
    body = {
        "type": f"{_ERROR_BASE}/{type_suffix}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": None,         # 由 middleware 填
        "trace_id": uuid.uuid4().hex[:12],  # 方便排查
        "timestamp": int(time.time()),
    }
    return JSONResponse(status_code=status, content=body,
                        media_type="application/problem+json",
                        headers=headers or {})


# 通用问题构造（便捷）
def bad_request(detail: str = "") -> JSONResponse:
    return problem(400, "Bad Request", detail, "bad-request")

def unauthorized(detail: str = "Authentication required") -> JSONResponse:
    return problem(401, "Unauthorized", detail, "unauthorized",
                  {"WWW-Authenticate": 'Bearer realm="theroom", X-API-Key'})

def forbidden(detail: str = "Forbidden") -> JSONResponse:
    return problem(403, "Forbidden", detail, "forbidden")

def not_found(detail: str = "Not found") -> JSONResponse:
    return problem(404, "Not Found", detail, "not-found")

def conflict(detail: str = "") -> JSONResponse:
    return problem(409, "Conflict", detail, "conflict")

def unprocessable(detail: str = "") -> JSONResponse:
    return problem(422, "Unprocessable Entity", detail, "unprocessable")


async def v3_exception_handler(request: Request, exc: Exception):
    """全局 FastAPI 异常处理：仅对 /api/v3/* 路径生效（转 RFC 7807），其他路径保持原样。"""
    from fastapi import HTTPException
    if not request.url.path.startswith("/api/v3/"):
        # 非 v3 路径：走 FastAPI 默认处理（HTML 或 JSON，看 Accept）
        from fastapi.exception_handlers import http_exception_handler
        return await http_exception_handler(request, exc)

    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return problem(exc.status_code, _title_for(exc.status_code),
                      detail, type_suffix=_suffix_for(exc.status_code),
                      headers=getattr(exc, "headers", None))

    # 兜底：500
    return problem(500, "Internal Server Error", str(exc), "internal")


def _title_for(s: int) -> str:
    return {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
            404: "Not Found", 409: "Conflict", 422: "Unprocessable Entity",
            429: "Too Many Requests", 500: "Internal Server Error",
            503: "Service Unavailable"}.get(s, "Error")


def _suffix_for(s: int) -> str:
    return {400: "bad-request", 401: "unauthorized", 403: "forbidden",
            404: "not-found", 409: "conflict", 422: "unprocessable",
            429: "too-many-requests", 500: "internal",
            503: "unavailable"}.get(s, "error")
