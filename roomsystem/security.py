"""安全：文件名清洗、路径逃逸检测、房间 hash。Phase 0 止血核心。"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

# 允许的文件名字符：字母数字、中文、点、下划线、短横、空格、括号。其余替换为 _。
_SAFE = re.compile(r"[^\w\u4e00-\u9fff.\- ()\[\]（）【】]")


def room_hash(password: str) -> str:
    """口令 → 房间目录名。单向，不可逆推口令。"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()[:16]


def clean_name(name: str) -> str:
    """清洗文件名：去路径分隔符、控制字符、非法字符；防点开头/过长。"""
    # 只取 basename，斩断任何 ../ 之类
    name = name.replace("\\", "/").split("/")[-1].strip()
    if not name or name in (".", ".."):
        return "unnamed"
    name = _SAFE.sub("_", name)
    # 不允许点开头（隐藏文件/相对穿越）
    name = name.lstrip(".")
    # 长度兜底
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        if dot:
            name = stem[: 200 - len(ext) - 1] + "." + ext
        else:
            name = name[:200]
    return name or "unnamed"


def ensure_within(parent: Path, target: Path) -> Path:
    """断言 target 解析后仍位于 parent 内，否则抛错。防路径遍历。"""
    parent = parent.resolve()
    target = target.resolve()
    if parent != target and parent not in target.parents:
        raise PermissionError(f"path escapes room dir: {target}")
    return target


def unique_path(dir_: Path, name: str) -> Path:
    """返回一个不冲突的路径。同名文件自动追加 (1)(2)。"""
    dir_.mkdir(parents=True, exist_ok=True)
    target = dir_ / name
    if not target.exists():
        return target
    stem = target.stem
    ext = target.suffix
    i = 1
    while True:
        cand = dir_ / f"{stem} ({i}){ext}"
        if not cand.exists():
            return cand
        i += 1
