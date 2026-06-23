"""认证：口令 → 房间 hash → session cookie。口令永不进 URL。"""
from __future__ import annotations
import hmac
import secrets
from fastapi import Request, Response

from . import store
from .security import room_hash
from .config import CONFIG

_COOKIE = "room_session"
# 内存里的有效 token：{token: room_hash}。进程重启即失效，够用。
_sessions: dict[str, str] = {}


def login(response: Response, password: str) -> str:
    """创建/进入房间。返回 room_hash，并种 cookie。"""
    rh = room_hash(password)
    # 预置房间校验：口令必须精确匹配某个预置房
    name = None
    is_preset = False
    for n, pw in CONFIG.preset_rooms.items():
        if hmac.compare_digest(pw, password):
            name = n
            is_preset = True
            break
    store.upsert_room(rh, name=name, is_preset=is_preset)
    token = secrets.token_urlsafe(24)
    _sessions[token] = rh
    response.set_cookie(_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return rh


def logout(response: Response) -> None:
    token = ""
    if response:
        pass
    _sessions.pop(token, None)
    response.delete_cookie(_COOKIE)


def current_room(request: Request) -> str | None:
    """从 cookie 取当前房间 hash。"""
    token = request.cookies.get(_COOKIE)
    if not token:
        return None
    rh = _sessions.get(token)
    if rh and not store.room_exists(rh):
        # 房间已被清掉，会话作废
        _sessions.pop(token, None)
        return None
    return rh


def is_admin(request: Request) -> bool:
    """管理员 cookie = 配置里的 admin 口令的 sha256 前缀，避免明文比对。"""
    tok = request.cookies.get("room_admin")
    if not tok:
        return False
    import hashlib
    expected = hashlib.sha256(CONFIG.admin_password.encode()).hexdigest()[:24]
    return hmac.compare_digest(tok, expected)


def admin_login(response: Response, password: str) -> bool:
    import hashlib
    if not hmac.compare_digest(password, CONFIG.admin_password):
        return False
    tok = hashlib.sha256(password.encode()).hexdigest()[:24]
    response.set_cookie("room_admin", tok, httponly=True, samesite="lax", max_age=60 * 60 * 24)
    return True


def admin_logout(response: Response) -> None:
    response.delete_cookie("room_admin")
