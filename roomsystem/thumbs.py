"""v2.3.0 缩略图生成。异步、不阻塞上传响应。缺依赖则优雅降级。

支持：
  - 图片（JPG/PNG/GIF/WebP/BMP）：Pillow 生成 256px JPEG
  - 视频（MP4/WebM/MOV/MKV/AVI/M4V）：ffmpeg -ss 00:00:01 -vframes 1
  - PDF：Pillow 读第一页
  - 其他 / 生成失败：thumb_status='failed'，前端用图标占位
"""
from __future__ import annotations
import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("thumbs")
_THUMB_DIR = "thumbs"  # 相对 FILES_DIR/{rh}/
THUMB_SIZE = 256       # 最长边像素

# 类型识别（与 routes._kind 保持一致）
_IMG_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
_VID_EXTS = {"mp4", "webm", "mov", "mkv", "avi", "m4v"}
_PDF_EXTS = {"pdf"}


def _thumb_path(room_hash: str, file_id: int) -> Path:
    from .config import FILES_DIR
    return FILES_DIR / room_hash / _THUMB_DIR / f"{file_id}.jpg"


def _src_path(room_hash: str, stored_name: str) -> Path:
    from .config import FILES_DIR
    return FILES_DIR / room_hash / stored_name


def _can_gen(ext: str) -> str | None:
    """返回 'image' / 'video' / 'pdf' / None。"""
    e = (ext or "").lower().lstrip(".")
    if e in _IMG_EXTS:
        return "image"
    if e in _VID_EXTS:
        return "video"
    if e in _PDF_EXTS:
        return "pdf"
    return None


def _gen_image(src: Path, dst: Path) -> bool:
    from PIL import Image
    try:
        im = Image.open(src)
        # EXIF 旋转（不依赖 piexif，直接用 PIL 的 transpose_if_needed）
        try:
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        im.thumbnail((THUMB_SIZE, THUMB_SIZE))
        # RGBA → RGB
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "JPEG", quality=82, optimize=True)
        return True
    except Exception as e:
        log.warning("image thumb failed %s: %s", src, e)
        return False


def _gen_pdf(src: Path, dst: Path) -> bool:
    from PIL import Image
    try:
        # 第一页：读取并转图
        im = Image.open(src)
        im.thumbnail((THUMB_SIZE, THUMB_SIZE))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "JPEG", quality=82, optimize=True)
        return True
    except Exception as e:
        log.warning("pdf thumb failed %s: %s", src, e)
        return False


def _gen_video(src: Path, dst: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg, "-y", "-ss", "1", "-i", str(src),
               "-vframes", "1", "-vf", f"scale='min({THUMB_SIZE},iw)':-1",
               "-q:v", "3", str(dst)]
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        return r.returncode == 0 and dst.exists() and dst.stat().st_size > 0
    except Exception as e:
        log.warning("video thumb failed %s: %s", src, e)
        return False


def _sync_generate(file_id: int, room_hash: str, stored_name: str, ext: str) -> str:
    """同步执行生成；返回 thumb_status: 'ready' | 'failed'。"""
    from . import store
    kind = _can_gen(ext)
    if not kind:
        store.set_thumb_status(file_id, "none")
        return "none"
    src = _src_path(room_hash, stored_name)
    if not src.exists():
        store.set_thumb_status(file_id, "failed")
        return "failed"
    dst = _thumb_path(room_hash, file_id)
    ok = False
    if kind == "image":
        ok = _gen_image(src, dst)
    elif kind == "video":
        ok = _gen_video(src, dst)
    elif kind == "pdf":
        ok = _gen_pdf(src, dst)
    status = "ready" if ok else "failed"
    store.set_thumb_status(file_id, status)
    return status


async def generate_async(file_id: int, room_hash: str, stored_name: str, ext: str) -> None:
    """包装 _sync_generate 到 asyncio，确保不阻塞事件循环。"""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _sync_generate, file_id, room_hash, stored_name, ext)
    except Exception as e:
        log.warning("thumb async failed for file %s: %s", file_id, e)
        try:
            from . import store
            store.set_thumb_status(file_id, "failed")
        except Exception:
            pass


def thumb_path_or_none(room_hash: str, file_id: int) -> Path | None:
    p = _thumb_path(room_hash, file_id)
    return p if p.exists() else None
