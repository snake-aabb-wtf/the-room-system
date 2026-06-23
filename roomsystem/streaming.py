"""流式上传/下载 + HTTP Range。避免全量入内存，支持视频拖动。"""
from __future__ import annotations
import os
from pathlib import Path

CHUNK = 1024 * 1024  # 1MB


def save_stream(src, dest: Path, max_size: int = 0) -> int:
    """从可读对象 src 分块写入 dest。返回字节数。max_size=0 不限。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as out:
        while True:
            buf = src.read(CHUNK)
            if not buf:
                break
            written += len(buf)
            if max_size and written > max_size:
                out.close()
                tmp.unlink(missing_ok=True)
                raise ValueError(f"file too large (>{max_size} bytes)")
            out.write(buf)
    tmp.replace(dest)
    return written


def parse_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    """解析 'bytes=start-end'，返回 (start, end) 闭区间；非法/无则 None。"""
    if not range_header or file_size == 0:
        return None
    try:
        unit, _, spec = range_header.partition("=")
        if unit.strip().lower() != "bytes":
            return None
        start_s, _, end_s = spec.partition("-")
        start = int(start_s) if start_s.strip() else 0
        end = int(end_s) if end_s.strip() else file_size - 1
        if start < 0:
            start = max(0, file_size + start)
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            return None
        return start, end
    except (ValueError, IndexError):
        return None


def iter_chunks(path: Path, start: int, end: int):
    """按 [start, end] 闭区间分块读文件。"""
    remaining = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            buf = f.read(min(CHUNK, remaining))
            if not buf:
                break
            remaining -= len(buf)
            yield buf
