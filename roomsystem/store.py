"""SQLite 持久层。文件本体存磁盘，元数据存这里。
表结构预留了软删除/到期/上传者/统计字段，供 Phase 2-5 使用。"""
from __future__ import annotations
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH, FILES_DIR

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    room_hash    TEXT UNIQUE NOT NULL,        -- sha256(password)[:16]
    name         TEXT,                        -- 预置房间名；临时房间为 NULL
    is_preset    INTEGER DEFAULT 0,
    created_at   REAL NOT NULL,
    last_active  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    room_hash    TEXT NOT NULL,
    name         TEXT NOT NULL,               -- 存盘文件名（已清洗）
    stored_name  TEXT NOT NULL,               -- 磁盘上的实际文件名（防重名）
    size         INTEGER NOT NULL,
    ext          TEXT DEFAULT '',
    deleted      INTEGER DEFAULT 0,           -- 软删除
    uploaded_by  TEXT DEFAULT '',             -- 昵称（Phase 5）
    created_at   REAL NOT NULL,
    expires_at   REAL DEFAULT NULL,           -- 到期时间戳（Phase 5）
    dl_count     INTEGER DEFAULT 0,           -- 下载次数（Phase 4 统计）
    deleted_at   REAL DEFAULT NULL,           -- 软删除时间（v2.2.0 回收站，30 天保留）
    parent_dir   TEXT DEFAULT '',              -- 相对目录（v2.3.0 文件夹）
    thumb_status TEXT DEFAULT 'none'           -- none/ready/failed (v2.3.0 缩略图)
);
CREATE INDEX IF NOT EXISTS idx_files_room ON files(room_hash);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    room_hash    TEXT NOT NULL,
    author       TEXT NOT NULL,               -- 昵称
    body         TEXT NOT NULL,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_room ON messages(room_hash);

CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    room_hash    TEXT,
    client_ip    TEXT,
    action       TEXT NOT NULL,               -- login/upload/download/delete/...
    detail       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);

CREATE TABLE IF NOT EXISTS shares (
    token        TEXT PRIMARY KEY,            -- 分享 token（口令登录后生成）
    room_hash    TEXT NOT NULL,
    created_at   REAL NOT NULL,
    expires_at   REAL,                        -- NULL = 永久
    revoked      INTEGER DEFAULT 0,
    label        TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_shares_room ON shares(room_hash);

CREATE TABLE IF NOT EXISTS api_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token        TEXT UNIQUE NOT NULL,        -- 32 字符随机（URL-safe base64）
    name         TEXT NOT NULL,               -- "CI 脚本"、"我的手机"
    scope        TEXT NOT NULL,               -- 逗号分隔 "admin,user,readonly"
    room_hash    TEXT,                        -- NULL=全局 token；非空=绑定某房间
    created_at   REAL NOT NULL,
    expires_at   REAL,                        -- NULL=永不过期
    revoked      INTEGER DEFAULT 0,
    last_used_at REAL
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_token ON api_tokens(token);

CREATE TABLE IF NOT EXISTS webhooks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT,
    url           TEXT NOT NULL,
    secret        TEXT NOT NULL,              -- 用户给的 secret，签名用
    events        TEXT NOT NULL,              -- 逗号分隔 "file.uploaded,file.deleted,..."
    room_hash     TEXT,                      -- NULL=全局
    active        INTEGER DEFAULT 1,
    created_at    REAL NOT NULL,
    last_fired_at REAL,
    fail_count    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id   INTEGER NOT NULL,
    event        TEXT NOT NULL,
    status_code  INTEGER,
    response_body TEXT,
    ts           REAL NOT NULL
);
"""


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


@contextmanager
def _conn():
    with _lock:
        con = sqlite3.connect(str(DB_PATH), timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        finally:
            con.close()


# ── 房间 ──────────────────────────────────────────
def upsert_room(room_hash: str, name: str | None = None, is_preset: bool = False) -> None:
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO rooms(room_hash, name, is_preset, created_at, last_active)
               VALUES(?,?,?,?,?)
               ON CONFLICT(room_hash) DO UPDATE SET last_active=excluded.last_active,
                  name=COALESCE(excluded.name, rooms.name)""",
            (room_hash, name, int(is_preset), now, now),
        )


def touch_room(room_hash: str) -> None:
    with _conn() as c:
        c.execute("UPDATE rooms SET last_active=? WHERE room_hash=?", (time.time(), room_hash))


def room_exists(room_hash: str) -> bool:
    with _conn() as c:
        r = c.execute("SELECT 1 FROM rooms WHERE room_hash=?", (room_hash,)).fetchone()
        return r is not None


# ── 文件 ──────────────────────────────────────────
def add_file(room_hash: str, name: str, stored_name: str, size: int, ext: str,
             uploaded_by: str = "", expires_at: float | None = None,
             parent_dir: str = "") -> int:
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO files(room_hash,name,stored_name,size,ext,uploaded_by,created_at,expires_at,parent_dir)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (room_hash, name, stored_name, size, ext, uploaded_by, now, expires_at, parent_dir),
        )
        return cur.lastrowid


def list_files(room_hash: str, include_deleted: bool = False) -> list[dict]:
    with _conn() as c:
        q = "SELECT * FROM files WHERE room_hash=?"
        if not include_deleted:
            q += " AND deleted=0"
        q += " ORDER BY created_at DESC, id DESC"
        rows = c.execute(q, (room_hash,)).fetchall()
        return [dict(r) for r in rows]


def list_files_v3(room_hash: str, q: str = "", parent_dir: str | None = None,
                  exts: list[str] | None = None, sort: str = "time",
                  page: int = 1, per_page: int = 50,
                  include_deleted: bool = False) -> tuple[list[dict], int]:
    """v3.0 房间文件查询：q (name/parent_dir 模糊), parent_dir (精确), exts (扩展名列表), sort, page/per_page。
    返回 (rows, total_count)。"""
    where = ["room_hash=?"]
    args: list = [room_hash]
    if not include_deleted:
        where.append("deleted=0")
    if q:
        where.append("(name LIKE ? OR parent_dir LIKE ?)")
        like = f"%{q}%"
        args += [like, like]
    if parent_dir is not None:
        where.append("parent_dir=?")
        args.append(parent_dir)
    if exts:
        placeholders = ",".join("?" for _ in exts)
        where.append(f"ext IN ({placeholders})")
        args += [e.lstrip(".").lower() for e in exts]
    where_sql = " AND ".join(where)
    order_sql = {
        "time": "created_at DESC, id DESC",
        "name": "name COLLATE NOCASE ASC",
        "size_asc": "size ASC",
        "size_desc": "size DESC",
    }.get(sort, "created_at DESC, id DESC")
    offset = max(0, (page - 1) * per_page)

    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM files WHERE {where_sql}", args).fetchone()["n"]
        rows = c.execute(
            f"SELECT * FROM files WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
            args + [per_page, offset],
        ).fetchall()
    return [dict(r) for r in rows], total


def soft_delete_files_batch(file_ids: list[int], room_hash: str) -> tuple[int, list[dict]]:
    """批量软删除：返回 (成功数, 失败 [{id, error}])。"""
    from . import realtime
    import asyncio
    success = 0
    failed = []
    # 一次查所有目标
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, room_hash FROM files WHERE id IN ({}) AND deleted=0".format(
                ",".join("?" * len(file_ids))
            ),
            file_ids,
        ).fetchall()
    valid = [dict(r) for r in rows if r["room_hash"] == room_hash]
    valid_ids = {r["id"] for r in valid}
    for fid in file_ids:
        if fid not in valid_ids:
            failed.append({"id": fid, "error": "not_found_or_wrong_room"})
    if not valid:
        return 0, failed
    now = time.time()
    valid_ids = [r["id"] for r in valid]
    with _conn() as c:
        for fid in valid_ids:
            c.execute("UPDATE files SET deleted=1, deleted_at=? WHERE id=?", (now, fid))
            success += 1
    # 广播（单次）
    for r in valid:
        try:
            asyncio.create_task(realtime.broadcast(room_hash, {"type": "delete", "name": r["name"]}))
        except Exception:
            pass
    return success, failed


def restore_files_batch(file_ids: list[int], room_hash: str) -> tuple[int, list[dict]]:
    """批量恢复：从回收站恢复。"""
    from . import realtime
    import asyncio
    success = 0
    failed = []
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, room_hash FROM files WHERE id IN ({}) AND deleted=1".format(
                ",".join("?" * len(file_ids))
            ),
            file_ids,
        ).fetchall()
    valid = [dict(r) for r in rows if r["room_hash"] == room_hash]
    valid_ids = {r["id"] for r in valid}
    for fid in file_ids:
        if fid not in valid_ids:
            failed.append({"id": fid, "error": "not_in_recycle_or_wrong_room"})
    if not valid:
        return 0, failed
    valid_ids = [r["id"] for r in valid]
    with _conn() as c:
        for fid in valid_ids:
            c.execute("UPDATE files SET deleted=0, deleted_at=NULL WHERE id=?", (fid,))
            success += 1
    for r in valid:
        try:
            asyncio.create_task(realtime.broadcast(room_hash, {"type": "restore", "name": r["name"]}))
        except Exception:
            pass
    return success, failed


def purge_files_batch(file_ids: list[int], room_hash: str) -> tuple[int, list[dict]]:
    """批量物理删除（仅作用于软删文件）。"""
    from .security import ensure_within
    from .config import FILES_DIR
    success = 0
    failed = []
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, stored_name, room_hash FROM files WHERE id IN ({}) AND deleted=1".format(
                ",".join("?" * len(file_ids))
            ),
            file_ids,
        ).fetchall()
    valid = [dict(r) for r in rows if r["room_hash"] == room_hash]
    valid_ids = {r["id"] for r in valid}
    for fid in file_ids:
        if fid not in valid_ids:
            failed.append({"id": fid, "error": "not_in_recycle_or_wrong_room"})
    if not valid:
        return 0, failed
    for r in valid:
        try:
            ensure_within(FILES_DIR / room_hash, stored_path(room_hash, r["stored_name"])).unlink(missing_ok=True)
        except Exception:
            pass
    if valid:
        ids = [r["id"] for r in valid]
        with _conn() as c2:
            qmarks = ",".join("?" * len(ids))
            c2.execute(f"DELETE FROM files WHERE id IN ({qmarks})", ids)
        success = len(valid)
    return success, failed


def empty_recycle(room_hash: str) -> int:
    """清空某房间回收站（30 天前的会被自动清理，但手动清空是一次性物理删）。返回删除数。"""
    from .security import ensure_within
    from .config import FILES_DIR
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, stored_name FROM files WHERE room_hash=? AND deleted=1",
            (room_hash,),
        ).fetchall()
    # 把所有需要删的 id 收集到内存（通常不多，<500），统一在新的连接里删
    ids = [r["id"] for r in rows]
    for r in rows:
        try:
            ensure_within(FILES_DIR / room_hash, stored_path(room_hash, r["stored_name"])).unlink(missing_ok=True)
        except Exception:
            pass
    if ids:
        with _conn() as c2:
            qmarks = ",".join("?" * len(ids))
            c2.execute(f"DELETE FROM files WHERE id IN ({qmarks})", ids)
    return len(ids)


def get_file(room_hash: str, name: str) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM files WHERE room_hash=? AND name=? AND deleted=0",
            (room_hash, name),
        ).fetchone()
        return dict(r) if r else None


def get_file_by_id(file_id: int) -> dict | None:
    """按 id 查文件（用于 /thumb/{rh}/{id} 路由，id 不可枚举查名）。"""
    with _conn() as c:
        r = c.execute("SELECT * FROM files WHERE id=? AND deleted=0", (file_id,)).fetchone()
        return dict(r) if r else None


def set_thumb_status(file_id: int, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE files SET thumb_status=? WHERE id=?", (status, file_id))


def update_file(file_id: int, name: str | None = None,
                parent_dir: str | None = None,
                expires_at: float | None = -1) -> dict | None:
    """v3.0 PATCH /files/{id} 后端：部分更新文件元数据。
    - name 走 clean_name；新名重复时返回 None
    - parent_dir 走安全清洗
    - expires_at=-1 表示不变；None=永久；正数=绝对时间戳
    返回更新后的行（dict）或 None（失败）。
    """
    from .security import clean_name
    sets, args = [], []
    if name is not None:
        new = clean_name(name)
        if not new or new in (".", ".."):
            return None
        sets.append("name=?"); args.append(new)
    if parent_dir is not None:
        # 与 upload 一致的安全清洗
        pdir = (parent_dir or "").replace("\\", "/").strip().strip("/")
        for seg in pdir.split("/") if pdir else []:
            if seg in ("", ".", ".."):
                pdir = ""; break
        pdir = pdir[:100]
        sets.append("parent_dir=?"); args.append(pdir)
    if expires_at != -1:
        sets.append("expires_at=?"); args.append(expires_at)
    if not sets:
        return get_file_by_id(file_id)
    args.append(file_id)
    with _conn() as c:
        try:
            cur = c.execute(f"UPDATE files SET {','.join(sets)} WHERE id=?", args)
            if cur.rowcount == 0 and name is not None:
                # 名字改了但 rowcount 0 ——可能是 UNIQUE 冲突
                return None
        except Exception:
            return None
    return get_file_by_id(file_id)


def get_files_by_ids(file_ids: list[int]) -> list[dict]:
    """批量按 id 取文件，保留传入顺序。zip 路由用。"""
    if not file_ids:
        return []
    with _conn() as c:
        qmarks = ",".join("?" * len(file_ids))
        rows = c.execute(
            f"SELECT * FROM files WHERE id IN ({qmarks}) AND deleted=0", file_ids
        ).fetchall()
    by_id = {r["id"]: dict(r) for r in rows}
    return [by_id[i] for i in file_ids if i in by_id]


def rename_file(room_hash: str, old_name: str, new_name: str, new_stored: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE files SET name=?, stored_name=? WHERE room_hash=? AND name=? AND deleted=0",
            (new_name, new_stored, room_hash, old_name),
        )
        return cur.rowcount > 0


def soft_delete_file(room_hash: str, name: str) -> bool:
    """软删除：标 deleted=1，记 deleted_at=now（v2.2.0 起 30 天内可恢复）。"""
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "UPDATE files SET deleted=1, deleted_at=? "
            "WHERE room_hash=? AND name=? AND deleted=0",
            (now, room_hash, name),
        )
        return cur.rowcount > 0


def list_deleted(room_hash: str) -> list[dict]:
    """列出某房间软删除（回收站）里的文件，按 deleted_at 倒序。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM files WHERE room_hash=? AND deleted=1 ORDER BY deleted_at DESC",
            (room_hash,),
        ).fetchall()
        return [dict(r) for r in rows]


def restore_file(room_hash: str, name: str) -> bool:
    """从回收站恢复：清 deleted / deleted_at。"""
    with _conn() as c:
        cur = c.execute(
            "UPDATE files SET deleted=0, deleted_at=NULL "
            "WHERE room_hash=? AND name=? AND deleted=1",
            (room_hash, name),
        )
        return cur.rowcount > 0


def purge_one(room_hash: str, name: str) -> str | None:
    """从软删文件里物理删除一条；返回磁盘上的 stored_name 以便调用方 unlink。
    找不到或已是活的返回 None。"""
    with _conn() as c:
        r = c.execute(
            "SELECT stored_name FROM files WHERE room_hash=? AND name=? AND deleted=1",
            (room_hash, name),
        ).fetchone()
        if not r:
            return None
        c.execute("DELETE FROM files WHERE room_hash=? AND name=?", (room_hash, name))
        return r["stored_name"]


def recycle_stats(room_hash: str) -> dict:
    """某房间回收站：文件数 + 占用字节。"""
    with _conn() as c:
        r = c.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(size),0) s FROM files "
            "WHERE room_hash=? AND deleted=1",
            (room_hash,),
        ).fetchone()
    return {"count": r["n"], "size": r["s"]}


def inc_download(room_hash: str, name: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE files SET dl_count=dl_count+1 WHERE room_hash=? AND name=?",
            (room_hash, name),
        )


def stored_path(room_hash: str, stored_name: str) -> Path:
    """文件在磁盘上的绝对路径。调用方仍须用 ensure_within 检查。"""
    return FILES_DIR / room_hash / stored_name


# ── 审计 ──────────────────────────────────────────
def audit(room_hash: str | None, client_ip: str, action: str, detail: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO audit(ts,room_hash,client_ip,action,detail) VALUES(?,?,?,?,?)",
            (time.time(), room_hash, client_ip, action, detail),
        )


def recent_audit(limit: int = 300) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def recent_audit_v3(page: int = 1, per_page: int = 50,
                    action: str = "", room_hash: str = "",
                    ip: str = "", since: float = 0, before: float = 0) -> tuple[list[dict], int]:
    """v3.0 审计分页 + 过滤。返回 (rows, total)。"""
    where, args = [], []
    if action:
        where.append("action=?"); args.append(action)
    if room_hash:
        where.append("room_hash=?"); args.append(room_hash)
    if ip:
        where.append("client_ip=?"); args.append(ip)
    if since:
        where.append("ts>=?"); args.append(since)
    if before:
        where.append("ts<=?"); args.append(before)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    offset = max(0, (page - 1) * per_page)
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM audit {where_sql}", args).fetchone()["n"]
        rows = c.execute(
            f"SELECT * FROM audit {where_sql} ORDER BY ts DESC LIMIT ? OFFSET ?",
            args + [per_page, offset],
        ).fetchall()
    return [dict(r) for r in rows], total


# ── Phase 4: 管理统计 ────────────────────────────
def _fmt_size_h(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def stats() -> dict:
    with _conn() as c:
        rooms = c.execute("SELECT COUNT(*) n FROM rooms").fetchone()["n"]
        files = c.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(size),0) s, COALESCE(SUM(dl_count),0) d FROM files WHERE deleted=0"
        ).fetchone()
        msgs = c.execute("SELECT COUNT(*) n FROM messages").fetchone()["n"]
        audits = c.execute("SELECT COUNT(*) n FROM audit").fetchone()["n"]
    return {
        "rooms": rooms,
        "files": files["n"],
        "total_size": files["s"],
        "total_size_h": _fmt_size_h(files["s"]),
        "downloads": files["d"],
        "messages": msgs,
        "audit_events": audits,
    }


def list_rooms() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT r.*, (SELECT COUNT(*) FROM files f WHERE f.room_hash=r.room_hash AND f.deleted=0) fcnt,
                      (SELECT COALESCE(SUM(size),0) FROM files f WHERE f.room_hash=r.room_hash AND f.deleted=0) fsize
               FROM rooms r ORDER BY r.last_active DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


RECYCLE_TTL = 30 * 24 * 3600  # 回收站保留 30 天


def purge_expired(now: float | None = None) -> int:
    """物理删除两类过期：
      1) expires_at <= now 的活文件（到期未删）
      2) 软删除超过 RECYCLE_TTL 的（回收站超过 30 天）
    返回总删除数量。"""
    from .config import FILES_DIR
    from .security import ensure_within
    now = now if now is not None else time.time()
    removed = 0
    with _conn() as c:
        # 1) 到期活文件
        rows = c.execute(
            "SELECT id, room_hash, name, stored_name FROM files "
            "WHERE expires_at IS NOT NULL AND expires_at<=? AND deleted=0",
            (now,),
        ).fetchall()
        for r in rows:
            try:
                p = ensure_within(FILES_DIR / r["room_hash"], stored_path(r["room_hash"], r["stored_name"]))
                p.unlink(missing_ok=True)
            except Exception:
                pass
            c.execute("DELETE FROM files WHERE id=?", (r["id"],))
            removed += 1
        # 2) 回收站 30 天
        cutoff = now - RECYCLE_TTL
        rows = c.execute(
            "SELECT id, room_hash, name, stored_name FROM files "
            "WHERE deleted=1 AND deleted_at IS NOT NULL AND deleted_at<=?",
            (cutoff,),
        ).fetchall()
        for r in rows:
            try:
                p = ensure_within(FILES_DIR / r["room_hash"], stored_path(r["room_hash"], r["stored_name"]))
                p.unlink(missing_ok=True)
            except Exception:
                pass
            c.execute("DELETE FROM files WHERE id=?", (r["id"],))
            removed += 1
    return removed


# ── Phase 5: 分享链接 ────────────────────────────
def create_share(room_hash: str, label: str = "", ttl_hours: float | None = None) -> dict:
    import secrets
    token = secrets.token_urlsafe(12)
    now = time.time()
    exp = now + ttl_hours * 3600 if ttl_hours else None
    with _conn() as c:
        c.execute(
            "INSERT INTO shares(token,room_hash,created_at,expires_at,label) VALUES(?,?,?,?,?)",
            (token, room_hash, now, exp, label),
        )
    return {"token": token, "expires_at": exp, "label": label}


def list_shares(room_hash: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM shares WHERE room_hash=? AND revoked=0 ORDER BY created_at DESC",
            (room_hash,),
        ).fetchall()
        return [dict(r) for r in rows]


def revoke_share(room_hash: str, token: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE shares SET revoked=1 WHERE token=? AND room_hash=?",
            (token, room_hash),
        )


def resolve_share(token: str) -> str | None:
    """返回 token 对应的 room_hash，已吊销/过期则 None。"""
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM shares WHERE token=? AND revoked=0", (token,)
        ).fetchone()
        if not r:
            return None
        if r["expires_at"] and r["expires_at"] < time.time():
            return None
        return r["room_hash"]


# ── Phase v3.0: API Token 系统 ───────────────────
import secrets as _secrets


def _new_token() -> str:
    """生成 32 字符 URL-safe token。"""
    return _secrets.token_urlsafe(24)


def create_api_token(name: str, scope: str, room_hash: str | None = None,
                     expires_at: float | None = None,
                     token: str | None = None) -> dict:
    """创建 API token。返回包含明文 token（仅此一次返回）。"""
    token = token or _new_token()
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO api_tokens(token,name,scope,room_hash,created_at,expires_at)
               VALUES(?,?,?,?,?,?)""",
            (token, name, scope, room_hash, now, expires_at),
        )
        tid = cur.lastrowid
    return {"id": tid, "token": token, "name": name, "scope": scope,
            "room_hash": room_hash, "expires_at": expires_at,
            "created_at": now, "revoked": 0}


def get_api_token(token: str) -> dict | None:
    """查 token 记录（含 revoked / expires_at 字段，调用方负责校验）。"""
    with _conn() as c:
        r = c.execute("SELECT * FROM api_tokens WHERE token=?", (token,)).fetchone()
        return dict(r) if r else None


def list_api_tokens(include_revoked: bool = True) -> list[dict]:
    """列所有 token（不带 token 字段本身）。"""
    with _conn() as c:
        q = "SELECT id,name,scope,room_hash,created_at,expires_at,revoked,last_used_at FROM api_tokens"
        if not include_revoked:
            q += " WHERE revoked=0"
        q += " ORDER BY created_at DESC"
        rows = c.execute(q).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["expires_h"] = (time.strftime("%Y-%m-%d %H:%M", time.localtime(d["expires_at"]))
                              if d["expires_at"] else "永久")
            d["last_used_h"] = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d["last_used_at"]))
                                 if d["last_used_at"] else "-")
            out.append(d)
        return out


def revoke_api_token(token_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE api_tokens SET revoked=1 WHERE id=?", (token_id,))
        return cur.rowcount > 0


def touch_api_token(token_id: int) -> None:
    """更新 last_used_at（异步更新，不阻塞主请求）。"""
    with _conn() as c:
        c.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?", (time.time(), token_id))


def update_api_token(token_id: int, name: str | None = None,
                     expires_at: float | None = -1) -> bool:
    """更新 token 字段。expires_at=-1 表示不变，None 表示永久。"""
    sets, args = [], []
    if name is not None:
        sets.append("name=?"); args.append(name)
    if expires_at != -1:
        sets.append("expires_at=?"); args.append(expires_at)
    if not sets:
        return False
    args.append(token_id)
    with _conn() as c:
        cur = c.execute(f"UPDATE api_tokens SET {','.join(sets)} WHERE id=?", args)
        return cur.rowcount > 0


# ── v3.0.0-rc.4: WebHook 系统 ───────────────────
def create_webhook(name: str, url: str, secret: str, events: str,
                   room_hash: str | None = None) -> dict:
    """创建 webhook。events 逗号分隔如 'file.uploaded,file.deleted'。"""
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO webhooks(name,url,secret,events,room_hash,active,created_at,last_fired_at,fail_count)
               VALUES(?,?,?,?,?,1,?,NULL,0)""",
            (name, url, secret, events, room_hash, now),
        )
        wid = cur.lastrowid
    return {"id": wid, "name": name, "url": url, "events": events,
            "room_hash": room_hash, "active": 1, "created_at": now, "fail_count": 0}


def list_webhooks(room_hash: str | None = None) -> list[dict]:
    with _conn() as c:
        if room_hash:
            rows = c.execute(
                "SELECT * FROM webhooks WHERE room_hash IS NULL OR room_hash=? ORDER BY created_at DESC",
                (room_hash,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM webhooks ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_webhook(wid: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM webhooks WHERE id=?", (wid,)).fetchone()
        return dict(r) if r else None


def update_webhook(wid: int, name: str | None = None, url: str | None = None,
                   secret: str | None = None, events: str | None = None,
                   active: int | None = None) -> bool:
    sets, args = [], []
    for col, val in (("name", name), ("url", url), ("secret", secret),
                      ("events", events), ("active", active)):
        if val is not None:
            sets.append(f"{col}=?"); args.append(val)
    if not sets: return False
    args.append(wid)
    with _conn() as c:
        cur = c.execute(f"UPDATE webhooks SET {','.join(sets)} WHERE id=?", args)
        return cur.rowcount > 0


def delete_webhook(wid: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM webhooks WHERE id=?", (wid,))
        c.execute("DELETE FROM webhook_deliveries WHERE webhook_id=?", (wid,))
        return cur.rowcount > 0


def record_webhook_delivery(webhook_id: int, event: str, status_code: int | None,
                            response_body: str = "") -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO webhook_deliveries(webhook_id,event,status_code,response_body,ts)
               VALUES(?,?,?,?,?)""",
            (webhook_id, event, status_code, response_body[:1000], time.time()),
        )


def touch_webhook_fired(wid: int, ok: bool) -> None:
    """成功调用 ok=True, 失败 ok=False。失败累计 fail_count, 达到阈值自动 disable。"""
    with _conn() as c:
        if ok:
            c.execute("UPDATE webhooks SET last_fired_at=?, fail_count=0 WHERE id=?",
                      (time.time(), wid))
        else:
            c.execute("UPDATE webhooks SET last_fired_at=?, fail_count=fail_count+1 WHERE id=?",
                      (time.time(), wid))
            # 失败 5 次自动 disable
            c.execute("UPDATE webhooks SET active=0 WHERE id=? AND fail_count>=5", (wid,))


def list_webhook_deliveries(webhook_id: int, limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM webhook_deliveries WHERE webhook_id=? ORDER BY ts DESC LIMIT ?",
            (webhook_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

