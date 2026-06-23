"""配置加载：读 config.toml，缺省全部有兜底。删了配置文件也能跑。

环境变量覆盖（便于测试 / CI / 容器）：
  ROOM_HOST      覆盖 host
  ROOM_PORT      覆盖 port
  ROOM_DATA_DIR  覆盖数据目录（DB + 文件都放这）
  ROOM_ADMIN_PW  覆盖管理员口令
"""
from __future__ import annotations
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE / "config.toml"

# 数据目录：默认 ./data，可被 ROOM_DATA_DIR 覆盖（CI / 测试用临时目录）
_env_data = os.environ.get("ROOM_DATA_DIR")
DATA_DIR = Path(_env_data).resolve() if _env_data else BASE / "data"
FILES_DIR = DATA_DIR / "files"
DB_PATH = DATA_DIR / "rooms.db"


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 3005
    max_file_size: int = 0  # 0 = 不限制
    preset_rooms: dict[str, str] = field(default_factory=dict)
    # 管理员口令：默认随机生成一次（首次启动时），后台登录用。
    admin_password: str = "admin"  # 仅占位，实际由首启随机覆盖写回

    @property
    def admin_cookie_value(self) -> str:
        return self.admin_password


def load() -> Config:
    cfg = Config()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            raw = tomllib.load(f)
        s = raw.get("server", {})
        cfg.host = s.get("host", cfg.host)
        cfg.port = int(s.get("port", cfg.port))
        st = raw.get("storage", {})
        cfg.max_file_size = int(st.get("max_file_size", cfg.max_file_size))
        cfg.preset_rooms = dict(raw.get("rooms", {}).get("preset", {}))
        # admin 口令可选地写在 config.toml 顶层 [admin] password
        ad = raw.get("admin", {})
        if ad.get("password"):
            cfg.admin_password = ad["password"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    # 环境变量覆盖（优先级最高）
    if os.environ.get("ROOM_HOST"):
        cfg.host = os.environ["ROOM_HOST"]
    if os.environ.get("ROOM_PORT"):
        cfg.port = int(os.environ["ROOM_PORT"])
    if os.environ.get("ROOM_ADMIN_PW"):
        cfg.admin_password = os.environ["ROOM_ADMIN_PW"]
    return cfg


CONFIG = load()
