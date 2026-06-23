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
from .config import CONFIG, FILES_DIR
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


# ── v3.0.0-rc.2: 文件 CRUD + 批量 + 回收站清空 ──
from pydantic import BaseModel, Field
from typing import Optional as Opt


class FilePatch(BaseModel):
    name: Opt[str] = Field(None, max_length=200)
    parent_dir: Opt[str] = Field(None, max_length=100)
    expires_at: Opt[float] = Field(None, description="None=永久；正数=绝对时间戳；负数=不变")


class IdsBody(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)


def _serialize_file(f: dict) -> dict:
    """统一返回结构（含 size_h 等便利字段）"""
    f["size_h"] = _fmt_size(f["size"])
    f["expire_h"] = ("永久" if not f.get("expires_at")
                     else time.strftime("%Y-%m-%d %H:%M", time.localtime(f["expires_at"])))
    return f


@router.get("/rooms/{rh}/files")
def list_files(rh: str, request: Request,
               q: str = "", parent_dir: Opt[str] = None, ext: str = "",
               sort: str = "time", page: int = 1, per_page: int = 50,
               include_deleted: bool = False):
    """v3 房间文件列表：分页 + 过滤 + 排序。"""
    auth_layer(request, need="user", room=rh)
    if not store.room_exists(rh):
        return not_found("room not found")
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    exts = [e.strip() for e in ext.split(",") if e.strip()] if ext else None
    rows, total = store.list_files_v3(rh, q=q, parent_dir=parent_dir,
                                       exts=exts, sort=sort, page=page,
                                       per_page=per_page,
                                       include_deleted=include_deleted)
    return {
        "items": [_serialize_file(f) for f in rows],
        "pagination": {
            "page": page, "per_page": per_page,
            "total": total, "total_pages": (total + per_page - 1) // per_page,
        },
    }


@router.get("/rooms/{rh}/files/{fid}")
def get_file(rh: str, fid: int, request: Request):
    auth_layer(request, need="user", room=rh)
    f = store.get_file_by_id(fid)
    if not f or f["room_hash"] != rh:
        return not_found("file not found")
    return _serialize_file(f)


@router.patch("/rooms/{rh}/files/{fid}")
async def patch_file(rh: str, fid: int, req: FilePatch, request: Request):
    """v3 文件部分更新：name / parent_dir / expires_at。
    readonly 范围不允许写。
    """
    # scope 校验：必须非 readonly
    rec = None
    from .auth_token import current_token
    rec = current_token(request)
    if rec and "readonly" in (rec.get("scope") or ""):
        from .errors import forbidden as fb
        return fb("readonly token cannot modify files")
    auth_layer(request, need="user", room=rh)
    f = store.get_file_by_id(fid)
    if not f or f["room_hash"] != rh:
        return not_found("file not found")
    # expires_at -1 表示不变；None=永久；正数=绝对时间戳
    exp = -1 if req.expires_at is None else req.expires_at
    new = store.update_file(fid, name=req.name, parent_dir=req.parent_dir, expires_at=exp)
    if new is None:
        return bad_request("invalid update (name collision or security violation)")
    return _serialize_file(new)


@router.delete("/rooms/{rh}/files/{fid}")
async def delete_file_v3(rh: str, fid: int, request: Request):
    auth_layer(request, need="user", room=rh)
    f = store.get_file_by_id(fid)
    if not f or f["room_hash"] != rh:
        return not_found("file not found")
    ok = store.soft_delete_file(rh, f["name"])
    from . import realtime
    await realtime.broadcast(rh, {"type": "delete", "name": f["name"]})
    return {"ok": ok}


@router.post("/rooms/{rh}/files/batch-delete")
async def batch_delete(rh: str, req: IdsBody, request: Request):
    auth_layer(request, need="user", room=rh)
    n, failed = store.soft_delete_files_batch(req.ids, rh)
    return {"ok": True, "deleted": n, "failed": failed}


@router.post("/rooms/{rh}/files/batch-restore")
async def batch_restore(rh: str, req: IdsBody, request: Request):
    auth_layer(request, need="user", room=rh)
    n, failed = store.restore_files_batch(req.ids, rh)
    return {"ok": True, "restored": n, "failed": failed}


@router.post("/rooms/{rh}/files/batch-purge")
async def batch_purge(rh: str, req: IdsBody, request: Request):
    auth_layer(request, need="user", room=rh)
    n, failed = store.purge_files_batch(req.ids, rh)
    return {"ok": True, "purged": n, "failed": failed}


@router.get("/rooms/{rh}/recycle")
def list_recycle(rh: str, request: Request, page: int = 1, per_page: int = 50):
    auth_layer(request, need="user", room=rh)
    per_page = max(1, min(per_page, 200))
    offset = max(0, (page - 1) * per_page)
    with store._conn() as c:
        total = c.execute(
            "SELECT COUNT(*) AS n FROM files WHERE room_hash=? AND deleted=1", (rh,),
        ).fetchone()["n"]
        rows = c.execute(
            "SELECT * FROM files WHERE room_hash=? AND deleted=1 ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
            (rh, per_page, offset),
        ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["size_h"] = _fmt_size(d["size"])
        d["deleted_h"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["deleted_at"]))
        items.append(d)
    return {"items": items,
            "pagination": {"page": page, "per_page": per_page, "total": total,
                           "total_pages": (total + per_page - 1) // per_page}}


@router.post("/rooms/{rh}/recycle/empty")
def empty_recycle_v3(rh: str, request: Request):
    """清空回收站（永久删除全部软删文件）。"""
    auth_layer(request, need="user", room=rh)
    n = store.empty_recycle(rh)
    return {"ok": True, "purged": n}


# ── v3.0.0-rc.2: 管理员分页 + 房间详情 ──
class AdminRoomInfo(BaseModel):
    is_preset: bool
    created_at: float
    last_active: float
    file_count: int
    total_size: int


@router.get("/admin/stats")
def admin_stats_v3(request: Request):
    auth_layer(request, need="admin")
    return store.stats()


@router.get("/admin/rooms")
def admin_rooms_v3(request: Request, q: str = "", page: int = 1, per_page: int = 50):
    """v3 管理员房间列表：支持搜索 + 分页。"""
    auth_layer(request, need="admin")
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    offset = max(0, (page - 1) * per_page)
    with store._conn() as c:
        where = ""
        args = []
        if q:
            where = "WHERE name LIKE ?"
            args = [f"%{q}%"]
        total = c.execute(f"SELECT COUNT(*) AS n FROM rooms {where}", args).fetchone()["n"]
        rows = c.execute(
            f"SELECT r.*, (SELECT COUNT(*) FROM files f WHERE f.room_hash=r.room_hash AND f.deleted=0) AS fcnt, "
            f"(SELECT COALESCE(SUM(size),0) FROM files f WHERE f.room_hash=r.room_hash AND f.deleted=0) AS fsize "
            f"FROM rooms r {where} ORDER BY r.last_active DESC LIMIT ? OFFSET ?",
            args + [per_page, offset],
        ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["last_h"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["last_active"]))
        d["created_h"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["created_at"]))
        d["fsize_h"] = _fmt_size(d["fsize"])
        items.append(d)
    return {"items": items,
            "pagination": {"page": page, "per_page": per_page, "total": total,
                           "total_pages": (total + per_page - 1) // per_page}}


@router.get("/admin/rooms/{rh}")
def admin_room_detail(rh: str, request: Request):
    """v3 单房间详情：文件统计 + 分享 + 令牌 + 审计条数。"""
    auth_layer(request, need="admin")
    if not store.room_exists(rh):
        return not_found("room not found")
    s = store.stats()
    return {
        "room_hash": rh,
        "file_count": s["files"],
        "total_size": s["total_size"],
        "total_size_h": s["total_size_h"],
    }


@router.get("/admin/audit")
def admin_audit_v3(request: Request, page: int = 1, per_page: int = 50,
                   action: str = "", room_hash: str = "",
                   ip: str = "", since: float = 0, before: float = 0):
    auth_layer(request, need="admin")
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    rows, total = store.recent_audit_v3(
        page=page, per_page=per_page, action=action,
        room_hash=room_hash, ip=ip, since=since, before=before,
    )
    items = []
    for r in rows:
        d = r
        d["ts_h"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d["ts"]))
        items.append(d)
    return {"items": items,
            "pagination": {"page": page, "per_page": per_page, "total": total,
                           "total_pages": (total + per_page - 1) // per_page}}


@router.post("/admin/cleanup")
def admin_cleanup_v3(request: Request):
    auth_layer(request, need="admin")
    n = store.purge_expired()
    return {"ok": True, "removed": n}


# ── v3.0.0-rc.3: 预签名 URL（HMAC 短时下载/上传）──
from . import presign as _presign
from .security import ensure_within, clean_name
import mimetypes


@router.get("/rooms/{rh}/presign")
def make_presign(rh: str, request: Request,
                 file_id: int, op: str = "get", ttl: int = 300):
    """v3 鉴权后调用：生成短时预签名 URL。

    返回 {url, sig, exp, ttl}。url 形如
    /api/v3/dl_presign/{rh}/{fid}?sig=...&exp=...&op=get
    任何人拿这个 URL 都能在 ttl 秒内下载该文件（无需 auth header）。
    """
    auth_layer(request, need="user", room=rh)
    if op not in ("get",):
        return bad_request("op must be 'get' (upload presign is not yet supported)")
    if ttl < 1 or ttl > 86400:  # 1s ~ 24h
        return bad_request("ttl must be between 1 and 86400 seconds")
    f = store.get_file_by_id(file_id)
    if not f or f["room_hash"] != rh or f.get("deleted"):
        return not_found("file not found")
    sig, exp = _presign.sign(rh, file_id, op="get", ttl_seconds=ttl)
    url = f"/api/v3/dl_presign/{rh}/{file_id}?sig={sig}&exp={int(exp)}&op={op}"
    return {"url": url, "sig": sig, "exp": exp, "ttl": ttl, "op": op,
            "file_id": file_id, "name": f["name"]}


@router.get("/dl_presign/{rh}/{fid}")
def dl_presign(rh: str, fid: int, request: Request,
               sig: str = "", exp: float = 0, op: str = "get"):
    """免鉴权下载：HMAC 验签通过即流式返回文件。"""
    ok, reason = _presign.verify(rh, fid, op, exp, sig)
    if not ok:
        from .errors import problem
        if reason == "expired":
            return problem(410, "Gone", "presigned URL expired", "expired",
                         {"deprecation": "false"})
        return problem(403, "Forbidden", f"presigned URL invalid: {reason}", "bad-signature")
    f = store.get_file_by_id(fid)
    if not f or f["room_hash"] != rh or f.get("deleted"):
        return not_found("file not found")
    p = ensure_within(FILES_DIR / rh, store.stored_path(rh, f["stored_name"]))
    if not p.exists():
        return not_found("file missing on disk")
    size = p.stat().st_size
    mt, _ = mimetypes.guess_type(str(p))
    headers = {
        "Content-Disposition": f'attachment; filename="{f["name"]}"',
        "Content-Length": str(size),
    }
    from fastapi.responses import StreamingResponse
    from .streaming import iter_chunks
    return StreamingResponse(iter_chunks(p, 0, size - 1),
                             media_type=mt or "application/octet-stream",
                             headers=headers)


# import 一些 Pydantic 在 v3 tokens 段也用到，这里集中 import
def _fmt_size(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024: return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"
