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
