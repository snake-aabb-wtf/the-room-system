"""后台定时任务：清理过期文件。"""
from __future__ import annotations
import asyncio
from . import store


async def expired_cleanup_loop(interval: int = 300) -> None:
    """每 interval 秒扫一次，物理删除到期文件。"""
    while True:
        try:
            n = store.purge_expired()
            if n:
                print(f"[cleanup] 已清理 {n} 个过期文件")
        except Exception as e:
            print(f"[cleanup] error: {e}")
        await asyncio.sleep(interval)
