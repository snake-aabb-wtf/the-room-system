"""核心路由：登录、房间页、上传/下载/删除/重命名、API、WebSocket。"""
from __future__ import annotations
import mimetypes
import re
import time
from pathlib import Path

from fastapi import APIRouter, Request, Response, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse

from . import store, auth, realtime
from .auth import current_room, is_admin, admin_login, admin_logout, login
from .config import CONFIG, FILES_DIR
from .net import local_ips
from .security import clean_name, ensure_within, unique_path, room_hash as _hash
from .streaming import save_stream, parse_range, iter_chunks

router = APIRouter()


def _require_room(request: Request) -> str:
    rh = current_room(request)
    if not rh:
        raise HTTPException(403, "未登录或房间已失效，请回到首页重新进入。")
    return rh


def _fmt_size(n: float) -> str:
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def _ext(name: str) -> str:
    return Path(name).suffix.lstrip(".").lower()


def _access_urls(request: Request) -> list[str]:
    port = CONFIG.port
    ips = local_ips()
    # 用当前请求的 Host 兜底
    host = request.headers.get("host", "").split(":")[0]
    if host and host not in ips and not host.startswith("127.") and host != "localhost":
        ips = [host] + ips
    if not ips:
        ips = ["127.0.0.1"]
    return [f"http://{ip}:{port}" for ip in ips]


def _ttl_to_ts(ttl) -> float | None:
    """表单 ttl（小时数，字符串）→ 到期时间戳。0/空/非法 → None=永久。"""
    try:
        h = float(str(ttl).strip())
        if h > 0:
            return time.time() + h * 3600
    except (TypeError, ValueError):
        pass
    return None


# ── 极简 Markdown 渲染（无外部依赖）──────────────
def _md(text: str) -> str:
    """渲染子集 Markdown 为 HTML，并转义防 XSS。"""
    s = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # 代码块
    s = re.sub(r"```([\s\S]*?)```", lambda m: f'<pre><code>{m.group(1).strip()}</code></pre>', s)
    # 行内代码
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    # 标题
    s = re.sub(r"^###### (.+)$", r"<h6>\1</h6>", s, flags=re.M)
    s = re.sub(r"^##### (.+)$", r"<h5>\1</h5>", s, flags=re.M)
    s = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", s, flags=re.M)
    s = re.sub(r"^### (.+)$", r"<h3>\1</h3>", s, flags=re.M)
    s = re.sub(r"^## (.+)$", r"<h2>\1</h2>", s, flags=re.M)
    s = re.sub(r"^# (.+)$", r"<h1>\1</h1>", s, flags=re.M)
    # 粗体/斜体/删除线
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
    s = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", s)
    # 链接 [text](url) —— url 只允许 http/https
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2" target="_blank">\1</a>', s)
    # 图片 ![alt](http url) —— 仅外链图
    s = re.sub(r"!\[([^\]]*)\]\((https?://[^\s)]+)\)", r'<img src="\2" alt="\1" style="max-width:100%">', s)
    # 引用
    s = re.sub(r"^&gt; (.+)$", r"<blockquote>\1</blockquote>", s, flags=re.M)
    # 水平线
    s = re.sub(r"^---+$", "<hr>", s, flags=re.M)
    # 列表
    s = re.sub(r"^[-*] (.+)$", r"<li>\1</li>", s, flags=re.M)
    s = re.sub(r"(<li>[\s\S]*?</li>)", r"<ul>\1</ul>", s)
    # 段落：连续非空行包 p
    out = []
    for block in re.split(r"\n{2,}", s):
        b = block.strip()
        if not b:
            continue
        if re.match(r"^<(h\d|pre|ul|ol|blockquote|hr|img)", b):
            out.append(b)
        else:
            out.append(f"<p>{b.replace(chr(10), '<br>')}</p>")
    return "\n".join(out)


# ── 页面 ───────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
def page_login(request: Request):
    urls = _access_urls(request)
    return request.app.state.templates.TemplateResponse(
        request, "login.html", {"urls": urls, "err": False}
    )


@router.post("/auth")
def do_auth(request: Request, password: str = File(...)):
    resp = JSONResponse({"ok": True})
    rh = auth.login(resp, password)
    store.audit(rh, request.client.host if request.client else "", "login", rh[:8])
    return resp


@router.get("/room", response_class=HTMLResponse, include_in_schema=False)
@router.get("/room/", response_class=HTMLResponse, include_in_schema=False)
def page_room_redirect(request: Request):
    rh = current_room(request)
    if not rh:
        return RedirectResponse("/", 303)
    return RedirectResponse(f"/room/{rh}", 303)


@router.get("/room/{rh}", response_class=HTMLResponse)
def page_room(request: Request, rh: str):
    if not store.room_exists(rh):
        return RedirectResponse("/", 303)
    # 必须持有该房间的会话
    mine = current_room(request)
    if mine != rh:
        return RedirectResponse("/", 303)
    store.touch_room(rh)
    files = store.list_files(rh)
    for f in files:
        f["size_h"] = _fmt_size(f["size"])
        f["ext"] = f["ext"] or _ext(f["name"])
        f["kind"] = _kind(f["ext"])
        f["when"] = time.strftime("%m-%d %H:%M", time.localtime(f["created_at"]))
        if f.get("expires_at"):
            f["expire_h"] = "永久" if f["expires_at"] == 0 else time.strftime(
                "%m-%d %H:%M", time.localtime(f["expires_at"]))
    return request.app.state.templates.TemplateResponse(
        request, "room.html",
        {
            "rh": rh,
            "files": files,
            "urls": _access_urls(request),
        },
    )


# ── 文件操作 ───────────────────────────────────────
def _kind(ext: str) -> str:
    return (
        "video" if ext in {"mp4", "webm", "mov", "mkv", "avi", "m4v"} else
        "audio" if ext in {"mp3", "wav", "ogg", "flac", "m4a", "aac"} else
        "image" if ext in {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"} else
        "text" if ext in {"txt", "md", "log", "csv", "json", "yaml", "yml", "ini", "conf"} else
        "code" if ext in {"py", "js", "ts", "html", "css", "java", "c", "cpp", "go", "rs", "sh"} else
        "pdf" if ext == "pdf" else
        "file"
    )


@router.get("/api/{rh}/files")
def api_files(rh: str, request: Request):
    if current_room(request) != rh:
        raise HTTPException(403)
    files = store.list_files(rh)
    return [{"name": f["name"], "size": f["size"], "ext": f["ext"], "dl": f["dl_count"]} for f in files]


@router.post("/upload/{rh}")
async def upload(rh: str, request: Request, file: UploadFile = File(...)):
    if current_room(request) != rh:
        raise HTTPException(403)
    # 可选到期时间（小时）；表单字段 ttl，0/空=永久
    form = await request.form()
    ttl = form.get("ttl", "")
    expires_at = _ttl_to_ts(ttl)
    safe = clean_name(file.filename or "unnamed")
    ext = _ext(safe)
    dest_dir = FILES_DIR / rh
    dest = unique_path(dest_dir, safe)
    ensure_within(dest_dir, dest)
    # 流式写盘，先拿到 UploadFile 的文件对象
    size = save_stream(file.file, dest, CONFIG.max_file_size or 0)
    nick = request.cookies.get("nick", "")
    store.add_file(rh, safe, dest.name, size, ext,
                   uploaded_by=nick, expires_at=expires_at)
    store.audit(rh, request.client.host if request.client else "", "upload", f"{safe} ({_fmt_size(size)})")
    await realtime.broadcast(rh, {"type": "upload", "name": safe, "size": size, "by": nick})
    return {"ok": True, "name": safe, "size": size, "size_h": _fmt_size(size)}


@router.post("/upload/{rh}/raw")
async def upload_raw(rh: str, request: Request):
    """curl 直传：body 即文件内容，X-Filename 头给名字。"""
    if current_room(request) != rh:
        raise HTTPException(403)
    fname = request.headers.get("x-filename", "unnamed")
    safe = clean_name(fname)
    ext = _ext(safe)
    dest_dir = FILES_DIR / rh
    dest = unique_path(dest_dir, safe)
    ensure_within(dest_dir, dest)
    size = save_stream(request.stream(), dest, CONFIG.max_file_size or 0)
    store.add_file(rh, safe, dest.name, size, ext, uploaded_by=request.cookies.get("nick", ""))
    store.audit(rh, request.client.host if request.client else "", "upload", f"{safe} ({_fmt_size(size)})")
    return {"ok": True, "name": safe, "size": size}


def _file_meta(rh: str, name: str) -> dict:
    f = store.get_file(rh, name)
    if not f:
        raise HTTPException(404, "文件不存在")
    return f


@router.get("/dl/{rh}/{name:path}")
def download_preview(rh: str, name: str, request: Request):
    """在线预览（inline）。支持 Range，供视频拖动。"""
    if current_room(request) != rh and not is_admin(request):
        raise HTTPException(403)
    f = _file_meta(rh, name)
    p = ensure_within(FILES_DIR / rh, store.stored_path(rh, f["stored_name"]))
    size = p.stat().st_size
    mt, _ = mimetypes.guess_type(str(p))
    ctype = mt or "application/octet-stream"
    rng = parse_range(request.headers.get("range", ""), size)
    headers = {"Cache-Control": "private", "Accept-Ranges": "bytes"}
    if rng:
        s, e = rng
        headers["Content-Range"] = f"bytes {s}-{e}/{size}"
        store.inc_download(rh, name)
        return StreamingResponse(iter_chunks(p, s, e), status_code=206,
                                 media_type=ctype, headers=headers)
    store.inc_download(rh, name)
    return StreamingResponse(iter_chunks(p, 0, size - 1), media_type=ctype, headers=headers)


@router.get("/raw/{rh}/{name:path}")
def download_raw(rh: str, name: str, request: Request):
    """强制下载（attachment）。"""
    if current_room(request) != rh and not is_admin(request):
        raise HTTPException(403)
    f = _file_meta(rh, name)
    p = ensure_within(FILES_DIR / rh, store.stored_path(rh, f["stored_name"]))
    size = p.stat().st_size
    store.inc_download(rh, name)

    def gen():
        yield from iter_chunks(p, 0, size - 1)

    return StreamingResponse(
        gen(), media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{f["name"]}"',
                 "Content-Length": str(size)},
    )


@router.post("/rename/{rh}")
def rename(rh: str, request: Request, name: str = File(...), new_name: str = File(...)):
    if current_room(request) != rh:
        raise HTTPException(403)
    safe = clean_name(new_name)
    f = store.get_file(rh, name)
    if not f:
        raise HTTPException(404)
    old_p = ensure_within(FILES_DIR / rh, store.stored_path(rh, f["stored_name"]))
    dest_dir = FILES_DIR / rh
    new_p = unique_path(dest_dir, safe)
    ensure_within(dest_dir, new_p)
    if new_p != old_p:
        old_p.replace(new_p)
    store.rename_file(rh, name, safe, new_p.name)
    return {"ok": True, "name": safe}


@router.post("/delete/{rh}")
async def delete(rh: str, request: Request, name: str = File(...)):
    if current_room(request) != rh:
        raise HTTPException(403)
    ok = store.soft_delete_file(rh, name)
    store.audit(rh, request.client.host if request.client else "", "delete", name)
    await realtime.broadcast(rh, {"type": "delete", "name": name})
    return {"ok": ok}


# ── 房间内昵称（Phase 5 预备，本身无害，提前开）──
@router.post("/nick/{rh}")
def set_nick(rh: str, request: Request, nick: str = File(...)):
    if current_room(request) != rh:
        raise HTTPException(403)
    nick = (nick or "").strip()[:24] or "匿名"
    resp = JSONResponse({"ok": True, "nick": nick})
    resp.set_cookie("nick", nick, httponly=False, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


# ── 房间留言：HTTP 拉取历史 + WebSocket 实时（Phase 5 提前开一点）──
@router.get("/api/{rh}/messages")
def get_messages(rh: str, request: Request):
    if current_room(request) != rh:
        raise HTTPException(403)
    with store._conn() as c:
        rows = c.execute(
            "SELECT author, body, created_at FROM messages WHERE room_hash=? ORDER BY id DESC LIMIT 200",
            (rh,)).fetchall()
    return [{"author": r["author"], "body": r["body"],
             "when": time.strftime("%H:%M:%S", time.localtime(r["created_at"]))}
            for r in reversed(rows)]


@router.post("/api/{rh}/messages")
async def post_message(rh: str, request: Request, body: str = File(...)):
    if current_room(request) != rh:
        raise HTTPException(403)
    nick = (request.cookies.get("nick") or "匿名").strip()[:24]
    body = (body or "").strip()[:1000]
    if not body:
        raise HTTPException(400, "空内容")
    ts = time.time()
    with store._conn() as c:
        c.execute("INSERT INTO messages(room_hash,author,body,created_at) VALUES(?,?,?,?)",
                  (rh, nick, body, ts))
    when = time.strftime("%H:%M:%S", time.localtime(ts))
    await realtime.broadcast(rh, {"type": "message", "author": nick, "body": body, "when": when})
    return {"ok": True, "author": nick, "body": body, "when": when}


# ── Phase 3: 预览渲染端点（markdown / 文本 / 缩略图）──
@router.get("/view/{rh}/md/{name:path}")
def view_markdown(rh: str, name: str, request: Request):
    """渲染 Markdown 为安全 HTML。"""
    if current_room(request) != rh and not is_admin(request):
        raise HTTPException(403)
    f = _file_meta(rh, name)
    p = ensure_within(FILES_DIR / rh, store.stored_path(rh, f["stored_name"]))
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")[:200000]
    except Exception:
        raw = ""
    html = _md(raw)
    return JSONResponse({"html": html, "name": name})


@router.get("/view/{rh}/text/{name:path}")
def view_text(rh: str, name: str, request: Request):
    """纯文本内容（前端高亮）。"""
    if current_room(request) != rh and not is_admin(request):
        raise HTTPException(403)
    f = _file_meta(rh, name)
    p = ensure_within(FILES_DIR / rh, store.stored_path(rh, f["stored_name"]))
    raw = p.read_text(encoding="utf-8", errors="replace")[:500000]
    return JSONResponse({"text": raw, "name": name, "ext": f["ext"]})


@router.get("/thumb/{rh}/{name:path}")
def thumbnail(rh: str, name: str, request: Request):
    """图片缩略图：直接流式原图（浏览器/CSS 缩放），省去 PIL 依赖。"""
    if current_room(request) != rh and not is_admin(request):
        raise HTTPException(403)
    f = _file_meta(rh, name)
    p = ensure_within(FILES_DIR / rh, store.stored_path(rh, f["stored_name"]))
    size = p.stat().st_size
    mt, _ = mimetypes.guess_type(str(p))
    return StreamingResponse(iter_chunks(p, 0, size - 1),
                             media_type=mt or "image/*",
                             headers={"Cache-Control": "public, max-age=3600"})


# ── Phase 5: 分享链接 ────────────────────────────
@router.post("/share/{rh}")
def create_share(rh: str, request: Request, ttl: str = "", label: str = ""):
    if current_room(request) != rh:
        raise HTTPException(403)
    ttl_h = None
    try:
        ttl_h = float(ttl) if ttl.strip() else None
    except ValueError:
        ttl_h = None
    sh = store.create_share(rh, label=label[:50], ttl_hours=ttl_h)
    store.audit(rh, request.client.host if request.client else "", "share", sh["token"][:8])
    return sh


@router.get("/share/{rh}/list")
def list_shares(rh: str, request: Request):
    if current_room(request) != rh:
        raise HTTPException(403)
    rows = store.list_shares(rh)
    for r in rows:
        r["created_h"] = time.strftime("%m-%d %H:%M", time.localtime(r["created_at"]))
        r["expires_h"] = (time.strftime("%m-%d %H:%M", time.localtime(r["expires_at"]))
                          if r["expires_at"] else "永久")
    return rows


@router.post("/share/{rh}/revoke")
def revoke_share(rh: str, request: Request, token: str = File(...)):
    if current_room(request) != rh:
        raise HTTPException(403)
    store.revoke_share(rh, token)
    return {"ok": True}


@router.get("/s/{token}", response_class=HTMLResponse, include_in_schema=False)
def share_landing(token: str, request: Request):
    """分享链接落地页：验证 token 后引导输入口令进入。"""
    rh = store.resolve_share(token)
    valid = rh is not None
    return request.app.state.templates.TemplateResponse(
        request, "share.html", {"valid": valid, "token": token})


# ── Phase 5: WebSocket 实时 ────────────────────────
@router.websocket("/ws/{rh}")
async def ws_room(ws: WebSocket, rh: str):
    """房间实时通道。通过 cookie 校验会话。"""
    # WebSocket 不能直接读 cookie 校验函数（需要 Request），这里手写校验
    cookie = ws.cookies.get("room_session") if hasattr(ws, "cookies") else None
    from .auth import _sessions
    if not cookie or _sessions.get(cookie) != rh:
        await ws.close(code=4403)
        return
    await ws.accept()
    await realtime.join(rh, ws)
    try:
        while True:
            # 接收客户端心跳/留言（也支持通过 ws 发消息）
            data = await ws.receive_text()
            # 简单协议：{"kind":"message","body":"..."}
            import json
            try:
                msg = json.loads(data)
            except Exception:
                continue
            if msg.get("kind") == "message":
                nick = ws.cookies.get("nick", "匿名") if hasattr(ws, "cookies") else "匿名"
                body = (msg.get("body") or "").strip()[:1000]
                if not body:
                    continue
                ts = time.time()
                with store._conn() as c:
                    c.execute("INSERT INTO messages(room_hash,author,body,created_at) VALUES(?,?,?,?)",
                              (rh, nick, body, ts))
                await realtime.broadcast(rh, {"type": "message", "author": nick, "body": body,
                                              "when": time.strftime("%H:%M:%S", time.localtime(ts))})
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.leave(rh, ws)


# ── 管理员 ─────────────────────────────────────────
@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        request, "admin.html", {"logged": is_admin(request)})


@router.post("/admin/auth")
def admin_auth(request: Request, password: str = File(...)):
    resp = JSONResponse({"ok": True})
    if not admin_login(resp, password):
        resp.delete_cookie("room_admin")
        raise HTTPException(403, "口令错误")
    return resp


def _require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(403)


@router.get("/admin/api/stats")
def admin_stats(request: Request):
    _require_admin(request)
    s = store.stats()
    s["total_size_h"] = _fmt_size(s["total_size"])
    return s


@router.get("/admin/api/rooms")
def admin_rooms(request: Request):
    _require_admin(request)
    rooms = store.list_rooms()
    for r in rooms:
        r["last_h"] = time.strftime("%m-%d %H:%M", time.localtime(r["last_active"]))
        r["created_h"] = time.strftime("%m-%d %H:%M", time.localtime(r["created_at"]))
        r["fsize_h"] = _fmt_size(r["fsize"])
    return rooms


@router.get("/admin/api/audit")
def admin_audit(request: Request, limit: int = 200):
    _require_admin(request)
    rows = store.recent_audit(limit)
    for r in rows:
        r["ts_h"] = time.strftime("%m-%d %H:%M:%S", time.localtime(r["ts"]))
    return rows


@router.post("/admin/api/cleanup")
def admin_cleanup(request: Request):
    _require_admin(request)
    n = store.purge_expired()
    return {"ok": True, "removed": n}


@router.post("/admin/api/room/{rh}/nuke")
def admin_nuke_room(rh: str, request: Request):
    _require_admin(request)
    """物理清空某房间所有文件。"""
    import shutil
    files = store.list_files(rh, include_deleted=True)
    for f in files:
        try:
            ensure_within(FILES_DIR / rh, store.stored_path(rh, f["stored_name"])).unlink(missing_ok=True)
        except Exception:
            pass
    with store._conn() as c:
        c.execute("DELETE FROM files WHERE room_hash=?", (rh,))
    store.audit(rh, request.client.host if request.client else "", "nuke", f"{len(files)} files")
    return {"ok": True, "removed": len(files)}
