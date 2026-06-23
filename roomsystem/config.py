"""配置加载：读 config.toml，缺省全部有兜底。删了配置文件也能跑。"""
from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE / "config.toml"
DATA_DIR = BASE / "data"
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
    return cfg


CONFIG = load()
