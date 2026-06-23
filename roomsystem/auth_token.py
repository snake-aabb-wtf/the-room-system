"""v3.0.0 API Token 鉴权：支持 Authorization: Bearer / X-API-Key header。

与 cookie session 共存：没有 token 时降级到 cookie 鉴权（零迁移成本）。
返回统一结构：{room_hash, scope, token_id, name}，scope 字段是 list[str]。
"""
from __future__ import annotations
from typing import Optional

from fastapi import Request

from . import store


_VALID_SCOPES = {"admin", "user", "readonly"}


def _parse_scopes(scope_str: str) -> list[str]:
    if not scope_str:
        return []
    out = []
    for s in scope_str.split(","):
        s = s.strip()
        if s in _VALID_SCOPES:
            out.append(s)
    return out


def _extract_token(request: Request) -> Optional[str]:
    """从 Authorization: Bearer xxx 或 X-API-Key: xxx 取 token。无则 None。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    xkey = request.headers.get("x-api-key", "").strip()
    if xkey:
        return xkey
    return None


def current_token(request: Request) -> Optional[dict]:
    """当前请求关联的 token 记录。None 表示未用 token 鉴权。"""
    tok = _extract_token(request)
    if not tok:
        return None
    rec = store.get_api_token(tok)
    if not rec:
        return None
    if rec.get("revoked"):
        return None
    if rec.get("expires_at") and rec["expires_at"] < __import__("time").time():
        return None
    return rec


def require_scope(request: Request, need: str, room: str | None = None):
    """校验 token 满足 scope+room。失败 raise HTTPException。

    优先 token 鉴权；token 不在时降级到 cookie 鉴权（看 .auth 模块）。
    need 可选 'admin' / 'user' / 'readonly'。readonly 不允许写操作（在路由层校验方法）。
    """
    from fastapi import HTTPException
    rec = current_token(request)
    if rec:
        scopes = _parse_scopes(rec["scope"])
        if need not in scopes and "admin" not in scopes:
            raise HTTPException(403, f"Token scope '{rec['scope']}' insufficient, need '{need}'")
        if need == "admin" and "admin" not in scopes:
            raise HTTPException(403, f"Need admin scope")
        if room is not None:
            tok_room = rec.get("room_hash")
            if tok_room and tok_room != room and "admin" not in scopes:
                raise HTTPException(403, "Token is bound to a different room")
        return rec
    # 降级到 cookie
    from . import auth as _auth
    sess_room = _auth.current_room(request)
    if sess_room is None:
        raise HTTPException(401, "Authentication required")
    if room is not None and sess_room != room:
        raise HTTPException(403, "Cookie session belongs to a different room")
    if need == "admin" and not _auth.is_admin(request):
        raise HTTPException(403, "Admin scope required")
    return None  # cookie 模式无 token 记录


def auth_layer(request: Request, need: str = "user", room: str | None = None) -> dict:
    """统一鉴权层：返回 {kind: 'token'|'cookie', room_hash, scope?}。"""
    from . import auth as _auth
    rec = current_token(request)
    if rec:
        scopes = _parse_scopes(rec["scope"])
        if need not in scopes and "admin" not in scopes:
            from fastapi import HTTPException
            raise HTTPException(403, f"Token scope insufficient, need '{need}'")
        if need == "admin" and "admin" not in scopes:
            from fastapi import HTTPException
            raise HTTPException(403, "Admin scope required")
        if room is not None:
            tok_room = rec.get("room_hash")
            if tok_room and tok_room != room and "admin" not in scopes:
                from fastapi import HTTPException
                raise HTTPException(403, "Token bound to different room")
        return {"kind": "token", "room_hash": rec.get("room_hash") or room,
                "scope": rec["scope"], "token_id": rec["id"], "name": rec["name"]}
    # 降级 cookie
    sess_room = _auth.current_room(request)
    if sess_room is None:
        from fastapi import HTTPException
        raise HTTPException(401, "Authentication required")
    if room is not None and sess_room != room and not _auth.is_admin(request):
        from fastapi import HTTPException
        raise HTTPException(403, "Cookie session belongs to a different room")
    if need == "admin" and not _auth.is_admin(request):
        from fastapi import HTTPException
        raise HTTPException(403, "Admin scope required")
    return {"kind": "cookie", "room_hash": sess_room, "scope": "cookie"}
