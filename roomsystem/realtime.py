"""WebSocket 房间内实时广播：留言/上传/删除事件推给同房间在线者。"""
from __future__ import annotations
import asyncio
import json
from collections import defaultdict
from fastapi import WebSocket

# 房间 → 在线连接集合
_rooms: dict[str, set[WebSocket]] = defaultdict(set)
_lock = asyncio.Lock()


async def join(room_hash: str, ws: WebSocket) -> None:
    async with _lock:
        _rooms[room_hash].add(ws)


async def leave(room_hash: str, ws: WebSocket) -> None:
    async with _lock:
        _rooms.get(room_hash, set()).discard(ws)
        if not _rooms.get(room_hash):
            _rooms.pop(room_hash, None)


async def broadcast(room_hash: str, event: dict) -> None:
    """向某房间所有在线连接推送一个事件。失败连接自动剔除。"""
    async with _lock:
        conns = list(_rooms.get(room_hash, set()))
    dead = []
    payload = json.dumps(event, ensure_ascii=False)
    for ws in conns:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    if dead:
        async with _lock:
            for ws in dead:
                _rooms.get(room_hash, set()).discard(ws)
