"""FastAPI 应用工厂。"""
from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import store
from .config import CONFIG, BASE

BASE_DIR = BASE
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app() -> FastAPI:
    store.init_db()
    app = FastAPI(title="The Room System", docs_url=None, redoc_url=None)
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from .routes import router
    app.include_router(router)

    # v3 API（新）
    from .routes_v3 import router as v3_router
    app.include_router(v3_router)

    # RFC 7807 全局异常处理（仅对 /api/v3/* 生效）
    from .errors import v3_exception_handler
    from fastapi import Request
    from starlette.exceptions import HTTPException as StarletteHTTPException
    app.add_exception_handler(StarletteHTTPException, v3_exception_handler)
    app.add_exception_handler(Exception, v3_exception_handler)

    # v3.0.0 Deprecation header 中间件（给旧路径加 Sunset 警告）
    from .deprecation import register as register_deprecation
    register_deprecation(app)

    @app.on_event("startup")
    async def _startup():
        # 首次启动若 admin 口令仍是占位，生成一个随机口令并写回 config.toml
        if CONFIG.admin_password in ("admin", ""):
            import secrets
            CONFIG.admin_password = secrets.token_urlsafe(8)
            _persist_admin(CONFIG.admin_password)
            print("=" * 52)
            print("首次启动：已生成管理员口令（后台登录用）：")
            print(f"    {CONFIG.admin_password}")
            print("已写入 config.toml [admin]，可随时修改。")
            print("=" * 52)
        # v3.0.0: 首启生成 admin API token（不覆盖已有）
        from . import store
        existing = store.list_api_tokens(include_revoked=False)
        if not any(t["name"] == "auto-admin" for t in existing):
            rec = store.create_api_token(name="auto-admin", scope="admin")
            print("=" * 52)
            print("v3.0 API Token（首启自动生成，scope=admin）：")
            print(f"    {rec['token']}")
            print("用此 token 调 /api/v3/* 端点：")
            print(f"    curl -H 'Authorization: Bearer {rec['token']}' http://{CONFIG.host}:{CONFIG.port}/api/v3/auth/tokens")
            print("=" * 52)
        # Phase 4: 启动过期文件清理后台循环
        from .cleanup import expired_cleanup_loop
        import asyncio
        asyncio.create_task(expired_cleanup_loop())

    return app


def _persist_admin(pw: str) -> None:
    cfg = CONFIG.__class__
    # 简单地追加 [admin] 段（已存在则不改），保证幂等不重复
    p = BASE_DIR / "config.toml"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if "[admin]" in text:
        # 替换 password
        import re
        text = re.sub(r"(\[admin\][^\[]*?password\s*=\s*)\"[^\"]*\"", rf'\1"{pw}"', text, flags=re.S)
    else:
        text = text.rstrip() + f"\n\n[admin]\npassword = \"{pw}\"\n"
    p.write_text(text, encoding="utf-8")
