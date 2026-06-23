"""v3.0.0 API 路由：/api/v3/* 全部走 Token 鉴权 + RFC 7807 错误。

本阶段只做：/api/v3/auth/tokens CRUD（基础鉴权机制）。
后续阶段补：rooms / files / admin / presign / webhooks 等。
"""
from __future__ import annotations
import time
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from . import store
from .auth_token import auth_layer, _parse_scopes, _VALID_SCOPES
from .errors import problem, bad_request, not_found, forbidden

router = APIRouter(prefix="/api/v3", tags=["v3"])


# ── Pydantic schemas ─────────────────────────────
class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    scope: str = Field(..., description="admin|user|readonly, 逗号分隔可多")
    room_hash: Optional[str] = Field(None, description="NULL=全局；非空=绑定某房间")
    expires_at: Optional[float] = Field(None, description="unix 时间戳；NULL=永不过期")


class TokenPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    expires_at: Optional[float] = Field(None)  # -1 不改 / None=永久


# ── /api/v3/auth/tokens ─────────────────────────
@router.get("/auth/tokens")
def list_tokens(request: Request):
    auth_layer(request, need="admin")
    return {"items": store.list_api_tokens(include_revoked=True)}


@router.post("/auth/tokens", status_code=201)
def create_token(req: TokenCreate, request: Request):
    # bootstrap 模式：没有 token 时用 X-Bootstrap-Password 头（=admin_password）创建第一个 token
    bootstrap = request.headers.get("x-bootstrap-password", "")
    if bootstrap:
        from .config import CONFIG
        import hmac
        if not hmac.compare_digest(bootstrap, CONFIG.admin_password):
            from .errors import unauthorized
            return unauthorized("Invalid bootstrap password")
        # bootstrap 成功，跳过 scope 校验（仅用于冷启动）
    else:
        auth_layer(request, need="admin")
    # 校验 scope
    scopes = _parse_scopes(req.scope)
    if not scopes:
        return bad_request(f"scope must contain at least one of: {sorted(_VALID_SCOPES)}")
    for s in scopes:
        if s not in _VALID_SCOPES:
            return bad_request(f"unknown scope '{s}'; valid: {sorted(_VALID_SCOPES)}")
    # 校验 expires_at
    if req.expires_at is not None and req.expires_at <= time.time():
        return bad_request("expires_at must be in the future (unix timestamp)")
    # 校验 room_hash（若有）
    if req.room_hash and not store.room_exists(req.room_hash):
        return not_found(f"room_hash {req.room_hash} not found")
    scope_str = ",".join(scopes)
    rec = store.create_api_token(name=req.name, scope=scope_str,
                                 room_hash=req.room_hash,
                                 expires_at=req.expires_at)
    return rec  # 含明文 token，仅此一次


@router.get("/auth/tokens/{tid}")
def get_token(tid: int, request: Request):
    auth_layer(request, need="admin")
    items = store.list_api_tokens(include_revoked=True)
    for t in items:
        if t["id"] == tid:
            return t
    return not_found(f"token {tid} not found")


@router.patch("/auth/tokens/{tid}")
def patch_token(tid: int, req: TokenPatch, request: Request):
    auth_layer(request, need="admin")
    name = req.name
    exp = req.expires_at if req.expires_at is not None else -1
    ok = store.update_api_token(tid, name=name, expires_at=exp)
    if not ok:
        return not_found(f"token {tid} not found or no change")
    return {"ok": True}


@router.delete("/auth/tokens/{tid}", status_code=204)
def delete_token(tid: int, request: Request):
    auth_layer(request, need="admin")
    ok = store.revoke_api_token(tid)
    if not ok:
        return not_found(f"token {tid} not found")
    return {"ok": True}
