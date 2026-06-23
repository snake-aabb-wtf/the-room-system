"""网络工具：自动探测本机所有局域网 IP，给用户展示可访问地址。"""
from __future__ import annotations
import socket


def local_ips() -> list[str]:
    """返回本机所有非回环的 IPv4 地址（去重保序）。"""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        # getaddrinfo 触发一次向外 UDP，能拿到主出口 IP
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    # 兜底：枚举所有网卡
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    # 再兜底：连一个外部地址看本地绑定
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    return ips
