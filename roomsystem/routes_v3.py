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
    # 触发 webhooks (取回原名列表)
    for fid in req.ids:
        f = store.get_file_by_id(fid)
        if f and f["room_hash"] == rh:
            try:
                await fire_event("file.restored", rh, {"name": f["name"]})
            except Exception:
                pass
    return {"ok": True, "restored": n, "failed": failed}


@router.post("/rooms/{rh}/files/batch-purge")
async def batch_purge(rh: str, req: IdsBody, request: Request):
    auth_layer(request, need="user", room=rh)
    n, failed = store.purge_files_batch(req.ids, rh)
    for fid in req.ids:
        f = store.get_file_by_id(fid)  # 已被删，返回 None
        # 永久删时 file 已 delete，无 from record
        try:
            await fire_event("file.purged", rh, {"id": fid})
        except Exception:
            pass
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


# ── v3.0.0-rc.4: WebHook 系统 ───────────────────
import hashlib
import hmac as _hmac
import httpx  # uvicorn[standard] 带的 httpx 用于出站调用
from pydantic import BaseModel, Field as _Field


class WebhookCreate(BaseModel):
    name: str = _Field(..., min_length=1, max_length=64)
    url: str = _Field(..., min_length=8, max_length=512)
    secret: str = _Field(..., min_length=4, max_length=128,
                        description="用户自己设的 secret, 签名时用 HMAC-SHA256")
    events: str = _Field("file.uploaded,file.deleted,file.restored,file.purged",
                        description="逗号分隔的事件名")
    room_hash: Opt[str] = None


class WebhookPatch(BaseModel):
    name: Opt[str] = None
    url: Opt[str] = None
    secret: Opt[str] = None
    events: Opt[str] = None
    active: Opt[int] = None


@router.get("/admin/webhooks")
def admin_list_webhooks(request: Request, room_hash: str = ""):
    auth_layer(request, need="admin")
    hooks = store.list_webhooks(room_hash or None)
    # 不返回 secret（安全）
    for h in hooks:
        h.pop("secret", None)
        if h.get("created_at"):
            h["created_h"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["created_at"]))
        if h.get("last_fired_at"):
            h["last_fired_h"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(h["last_fired_at"]))
    return {"items": hooks}


@router.post("/admin/webhooks", status_code=201)
def admin_create_webhook(req: WebhookCreate, request: Request):
    auth_layer(request, need="admin")
    if req.room_hash and not store.room_exists(req.room_hash):
        return not_found("room not found")
    # 简单 URL 校验
    if not (req.url.startswith("http://") or req.url.startswith("https://")):
        return bad_request("url must start with http:// or https://")
    rec = store.create_webhook(
        name=req.name, url=req.url, secret=req.secret,
        events=req.events, room_hash=req.room_hash,
    )
    rec.pop("secret", None)
    return rec


@router.get("/admin/webhooks/{wid}")
def admin_get_webhook(wid: int, request: Request):
    auth_layer(request, need="admin")
    h = store.get_webhook(wid)
    if not h: return not_found("webhook not found")
    h.pop("secret", None)
    if h.get("created_at"):
        h["created_h"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["created_at"]))
    return h


@router.patch("/admin/webhooks/{wid}")
def admin_patch_webhook(wid: int, req: WebhookPatch, request: Request):
    auth_layer(request, need="admin")
    if not store.get_webhook(wid):
        return not_found("webhook not found")
    ok = store.update_webhook(wid, name=req.name, url=req.url,
                              secret=req.secret, events=req.events, active=req.active)
    return {"ok": ok}


@router.delete("/admin/webhooks/{wid}", status_code=204)
def admin_delete_webhook(wid: int, request: Request):
    auth_layer(request, need="admin")
    if not store.delete_webhook(wid):
        return not_found("webhook not found")
    return {"ok": True}


@router.get("/admin/webhooks/{wid}/deliveries")
def admin_list_deliveries(wid: int, request: Request, limit: int = 50):
    auth_layer(request, need="admin")
    return {"items": store.list_webhook_deliveries(wid, limit=limit)}


# ── 事件触发器：被各种写入操作调用 ──
async def fire_event(event: str, room_hash: str, payload: dict) -> None:
    """异步触发：所有活跃且订阅该事件的 webhook 都会收到 POST。
    签名: HMAC-SHA256(secret, timestamp + '.' + body)
    Header: X-Room-Signature-256: t=<ts>,v1=<sig>
    """
    import json as _json
    import asyncio as _asyncio
    # 找订阅
    hooks = store.list_webhooks(room_hash)
    targets = [h for h in hooks
               if h.get("active") and event in (h.get("events") or "").split(",")]
    if not targets:
        return
    body_bytes = _json.dumps({"event": event, "room": room_hash, **payload},
                             ensure_ascii=False).encode("utf-8")
    # 异步投递
    _asyncio.create_task(_deliver_all(targets, event, body_bytes))


async def _deliver_all(hooks, event, body_bytes):
    """对每个 hook 并发 POST 一次。"""
    import asyncio as _asyncio
    import json as _json
    ts = int(time.time())
    async with httpx.AsyncClient(timeout=10) as client:
        for h in hooks:
            wid = h["id"]
            secret = h.get("secret", "").encode()
            msg = f"{ts}.".encode() + body_bytes
            sig = _hmac.new(secret, msg, hashlib.sha256).hexdigest()
            try:
                r = await client.post(
                    h["url"],
                    content=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Room-Signature-256": f"t={ts},v1={sig}",
                        "X-Room-Event": event,
                    },
                )
                store.record_webhook_delivery(wid, event, r.status_code, r.text[:200])
                store.touch_webhook_fired(wid, ok=(200 <= r.status_code < 300))
            except Exception as e:
                store.record_webhook_delivery(wid, event, None, str(e)[:200])
                store.touch_webhook_fired(wid, ok=False)


# ── 在上传/删除/恢复/永久删时触发事件 ──
# 集成点：把原 upload / delete / batch-* 路由的 broadcast 旁加 fire_event
# 为最小侵入，新加 hook 包装。直接修改现有路由工作量大，改在 routes.py 关键点调 fire_event。
# 这里仅暴露 fire_event，调用方集成。
# 实际：已通过 realtime.broadcast 推 WS。fire_event 是另一通道，外部可订阅。


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
