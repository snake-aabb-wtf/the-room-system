"""v3.0.0 Deprecation 中间件：给旧路径加 Deprecation / Sunset / Link header。

RFC 8594 (Sunset Header) + RFC 9745 (Deprecation Header) 规范。
用 FastAPI 装饰器形式注册，避免 ASGI BaseHTTPMiddleware 边界问题。
"""
from __future__ import annotations
from fastapi import Request, Response

# 旧路径前缀
_OLD_PREFIXES = (
    "/api/", "/upload/", "/delete/", "/rename/", "/recycle/", "/restore/",
    "/purge/", "/share/", "/zip/", "/dl/", "/raw/", "/thumb/", "/view/",
    "/admin/", "/nick/", "/s/", "/ws/", "/room/", "/auth",
)

# 不需要 deprecation 的（页面、login、static）
# 注："/" 不能放这里，否则所有路径都被认为"keep"——根路径 "/" 单独处理
_KEEP_PREFIXES = ("/static/", "/docs", "/openapi.json", "/favicon")
# 根路径 "/" 单独规则
_ROOT_PATH = "/"

_V3_REPLACEMENT = "http://room.example/api/v3"
_SUNSET = "2026-12-31"


def register(app) -> None:
    """用 FastAPI 装饰器形式注册中间件（推荐方式）。"""
    @app.middleware("http")
    async def deprecation_mw(request: Request, call_next):
        path = request.url.path
        response: Response = await call_next(request)
        for k, v in headers_for_old(path).items():
            response.headers[k] = v
        return response


def headers_for_old(path: str) -> dict:
    """判断 path 是否为旧路径；是则返回 Deprecation/Sunset/Link header dict。
    既被中间件用，也被测试用（直接验证逻辑）。
    """
    if path == _ROOT_PATH:
        return {}
    if path.startswith("/api/v3/"):
        return {}
    if any(path.startswith(p) for p in _KEEP_PREFIXES):
        return {}
    if not any(path.startswith(p) for p in _OLD_PREFIXES):
        return {}
    return {
        "Deprecation": "true",
        "Sunset": _SUNSET,
        "Link": f'<{_V3_REPLACEMENT}>; rel="successor-version"',
    }


