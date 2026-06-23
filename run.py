"""启动入口。直接 python run.py 即可。
端口被占时会自动检测并给出清晰指引，而不是一堆 traceback。"""
import socket
import sys
import uvicorn
from roomsystem.app import create_app
from roomsystem.config import CONFIG
from roomsystem.net import local_ips


def _check_port(host: str, port: int) -> bool:
    """端口是否可绑定。返回 True 表示空闲。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _who_holds(port: int) -> str | None:
    """尽力找出占用端口的进程 PID（Windows）。"""
    try:
        import subprocess
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line.upper():
                parts = line.split()
                return parts[-1] if parts else None
    except Exception:
        return None
    return None


app = create_app()

if __name__ == "__main__":
    banner = "=" * 54
    print(banner)
    print("  The Room System 启动中...")
    print(banner)
    ips = local_ips() or ["127.0.0.1"]
    for ip in ips:
        print(f"  →  http://{ip}:{CONFIG.port}")
    print("-" * 54)
    print(f"  管理后台: http://{ips[0]}:{CONFIG.port}/admin")
    print(banner)

    # 端口冲突提前拦截，给出可操作提示
    try:
        if not _check_port(CONFIG.host, CONFIG.port):
            pid = _who_holds(CONFIG.port)
            print("\n" + "!" * 54)
            print(f"  端口 {CONFIG.port} 已被占用！" + (f"（占用进程 PID={pid}）" if pid else ""))
            print(f"  解决方法：")
            print(f"    1) 终止占用：  taskkill /pid {pid or 'PID'} /f")
            print(f"    2) 或换端口：修改 config.toml [server] port = 某个空闲端口")
            print("!" * 54 + "\n")
            sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        pass  # 检测失败不阻塞，交给 uvicorn 自己报错

    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, log_level="warning")
