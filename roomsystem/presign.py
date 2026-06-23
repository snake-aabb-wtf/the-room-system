"""v3.0.0 预签名 URL（HMAC-SHA256）：短时免鉴权下载链接。

设计目标：
  - 单条 `curl URL -o file` 就能下载，无需任何 auth header
  - 签名内嵌过期时间（exp unix ts），过期自动 410
  - 纯无状态：服务端不存任何签名记录，重启不丢
  - secret 启动时随机生成（secrets.token_urlsafe(32)），内存中
"""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time
from typing import Literal


# 启动时生成一次；不可轮换（轮换会让未过期 URL 立即失效）
# 多进程部署时需要共享 secret（写到 data/.presign_secret），但单进程 demo 用内存即可
_SECRET: bytes | None = None


def get_secret() -> bytes:
    """惰性初始化 secret（首次调用生成）。"""
    global _SECRET
    if _SECRET is None:
        _SECRET = secrets.token_urlsafe(32).encode()
    return _SECRET


def set_secret(s: bytes) -> None:
    """从持久化（data/.presign_secret 文件）恢复 secret。多进程部署用。"""
    global _SECRET
    _SECRET = s


# 操作类型
OpType = Literal["get", "upload"]


def sign(room_hash: str, file_id: int, op: OpType = "get",
        ttl_seconds: int = 300) -> tuple[str, float]:
    """生成预签名 URL。

    返回 (signed_url, expires_at)。URL 形如：
        /api/v3/dl_presign/{rh}/{fid}?sig=...&exp=...&op=get
    """
    exp = int(time.time()) + ttl_seconds
    msg = f"{room_hash}|{file_id}|{op}|{exp}".encode()
    sig = hmac.new(get_secret(), msg, hashlib.sha256).hexdigest()
    return sig, float(exp)


def verify(room_hash: str, file_id: int, op: str, exp: float, sig: str) -> tuple[bool, str]:
    """验签。返回 (ok, reason)。"""
    # 1) 过期
    now = time.time()
    if exp < now:
        return False, "expired"
    if exp > now + 7 * 24 * 3600:  # 防时间漂移 + 最长 7 天
        return False, "exp_too_far"
    # 2) 验签
    msg = f"{room_hash}|{file_id}|{op}|{int(exp)}".encode()
    expected = hmac.new(get_secret(), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, "bad_signature"
    return True, "ok"
