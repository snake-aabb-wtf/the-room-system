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
    deleted_at   REAL DEFAULT NULL            -- 软删除时间（v2.2.0 回收站，30 天保留）
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
             uploaded_by: str = "", expires_at: float | None = None) -> int:
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO files(room_hash,name,stored_name,size,ext,uploaded_by,created_at,expires_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (room_hash, name, stored_name, size, ext, uploaded_by, now, expires_at),
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


def get_file(room_hash: str, name: str) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM files WHERE room_hash=? AND name=? AND deleted=0",
            (room_hash, name),
        ).fetchone()
        return dict(r) if r else None


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


# ── Phase 4: 管理统计 ────────────────────────────
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
