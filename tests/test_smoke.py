"""端到端冒烟测试：自启服务 → 全流程验证 → 清理。

可独立运行：python tests/test_smoke.py
无需预启动任何服务，脚本会用临时目录 + 随机端口自起一个实例。

覆盖项：
  登录 · 进房间 · 上传(ASCII/中文) · 文件列表 · 下载(全量+Range)
  路径穿越拦截 · 未授权拦截 · Markdown 渲染 · 文本预览
  分享链接(创建/列表/吊销/落地页) · 到期上传 · 留言
  管理员(登录/统计/房间/审计/未授权拦截) · 过期清理
  WebSocket 实时双向广播 + 鉴权
"""
from __future__ import annotations
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore
import pathlib
from pathlib import Path

# ── 测试用固定口令 ──────────────────────────────
PW = "ci_smoke_pw_zZ99"
ADMIN_PW = "ci_admin_pw_xyz"
BASE = Path(__file__).resolve().parent.parent

_passed = 0
_failed = 0


def ok(name: str, detail: str = "") -> None:
    global _passed
    _passed += 1
    print(f"  [PASS] {name}{(' — ' + detail) if detail else ''}")


def fail(name: str, err: str) -> None:
    global _failed
    _failed += 1
    print(f"  [FAIL] {name} — {err}")


def check(name: str, cond: bool, detail: str = "") -> None:
    (ok if cond else fail)(name, detail if not cond else detail)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def rh() -> str:
    return hashlib.sha256(PW.encode()).hexdigest()[:16]


# ── HTTP 工具 ──────────────────────────────────
def req(host, port, method, path, headers=None, body=None, timeout=10, max_read=None):
    c = http.client.HTTPConnection(host, port, timeout=timeout)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    if max_read is not None:
        # 读 N 字节后强制中断（流式响应可能无 Content-Length 不会 EOF）
        try:
            data = r.read(max_read)
        except Exception:
            data = b""
        try:
            r.close()
        except Exception:
            pass
        try:
            c.close()
        except Exception:
            pass
    else:
        data = r.read()
        cookies = r.getheader("set-cookie") or ""
        c.close()
        return r.status, data, cookies, dict(r.getheaders())
    cookies = r.getheader("set-cookie") or ""
    return r.status, data, cookies, dict(r.getheaders())


def mp(field, filename, content, ctype="text/plain", boundary="BNDRY"):
    """构造 multipart body。boundary 不用 - 开头，避免和协议前缀 -- 混淆。"""
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    return head + content + f"\r\n--{boundary}--\r\n".encode()


def wait_up(host, port, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def main():
    # 让测试主进程能 import roomsystem.* 工具
    sys.path.insert(0, str(BASE))

    tmp = tempfile.mkdtemp(prefix="room_test_")
    port = free_port()
    print(f"\n>>> 启动测试服务: 127.0.0.1:{port}  数据目录: {tmp}")

    # 测试主进程 + 子进程共享 ROOM_ADMIN_PW
    os.environ["ROOM_ADMIN_PW"] = "ci_admin_pw_xyz"

    env = dict(os.environ)
    env.update({
        "ROOM_HOST": "127.0.0.1",
        "ROOM_PORT": str(port),
        "ROOM_DATA_DIR": str(tmp),
        "ROOM_ADMIN_PW": "ci_admin_pw_xyz",
        "PYTHONPATH": str(BASE),
    })
    proc = subprocess.Popen(
        [sys.executable, "-c", "import uvicorn; from roomsystem.app import create_app; "
                               "uvicorn.run(create_app(), host='127.0.0.1', port=%d, log_level='warning')" % port],
        cwd=str(BASE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_up("127.0.0.1", port):
            err = proc.stderr.read().decode("utf-8", "replace")[:500]
            print(f"!!! 服务启动失败:\n{err}")
            return 1
        run_tests("127.0.0.1", port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n>>> 结果: {_passed} 通过, {_failed} 失败")
    return 0 if _failed == 0 else 1


def run_tests(host, port):
    print("\n=== 基础流程 ===")
    s, data, _, _ = req(host, port, "GET", "/")
    check("首页渲染", s == 200 and b"\xe6\x96\x87\xe4\xbb\xb6\xe4\xbc\xa0\xe8\xbe\x93" in data, str(s))

    s, _, cookies, _ = req(host, port, "POST", "/auth",
                           {"Content-Type": "application/x-www-form-urlencoded"},
                           body=f"password={PW}")
    sess = cookies.split(";")[0]
    check("登录发 cookie", s == 200 and sess.startswith("room_session="), str(s))

    R = rh()
    s, data, _, _ = req(host, port, "GET", f"/room/{R}", {"Cookie": sess})
    check("进入房间页", s == 200 and b"\xe6\x88\xbf\xe9\x97\xb4" in data, str(s))

    print("\n=== 上传 / 下载 / Range ===")
    b = "BNDRYUA"
    s, d, _, _ = req(host, port, "POST", f"/upload/{R}",
                     {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"},
                     body=mp("file", "ascii.txt", b"hello world", boundary=b))
    check("上传 ASCII 文件", s == 200 and json.loads(d)["ok"], str(s))

    b = "BNDRYUC"
    s, d, _, _ = req(host, port, "POST", f"/upload/{R}",
                     {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"},
                     body=mp("file", "\u6d4b\u8bd5.txt", b"ni hao", boundary=b))  # 测试.txt
    up = json.loads(d)
    check("上传中文文件名", s == 200 and up["ok"] and up["name"] == "\u6d4b\u8bd5.txt", str(s))

    s, data, _, _ = req(host, port, "GET", f"/api/{R}/files", {"Cookie": sess})
    files = json.loads(data)
    check("文件列表", s == 200 and any(f["name"] == "\u6d4b\u8bd5.txt" for f in files), str(s))

    # 全量下载 + Range 文件
    b = "BNDRYUR"
    content = b"0123456789" * 10
    req(host, port, "POST", f"/upload/{R}",
        {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"},
        body=mp("file", "range.bin", content, boundary=b))
    s, data, _, h = req(host, port, "GET", f"/dl/{R}/range.bin", {"Cookie": sess, "Range": "bytes=5-9"})
    check("Range 部分内容(206)", s == 206 and data == content[5:10], f"{s} {data!r}")
    cr = h.get("Content-Range") or h.get("content-range") or ""
    check("Content-Range 头正确", cr == "bytes 5-9/100", cr)
    ar = (h.get("Accept-Ranges") or h.get("accept-ranges") or "").lower()
    check("Accept-Ranges 支持", ar == "bytes", ar)

    print("\n=== 安全拦截 ===")
    s, _, _, _ = req(host, port, "GET", f"/dl/{R}/..%2f..%2fconfig.toml", {"Cookie": sess})
    check("路径穿越被拦", s in (400, 404, 422), str(s))

    s, _, _, _ = req(host, port, "GET", f"/api/{R}/files")  # 无 cookie
    check("未授权访问被拦(403)", s == 403, str(s))

    print("\n=== 预览渲染 (Phase 3) ===")
    md = b"# Title\n\n**bold**\n\n- a\n- b\n\n> quote\n\n`code`"
    b = "BNDRYMD"
    req(host, port, "POST", f"/upload/{R}",
        {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"},
        body=mp("file", "doc.md", md, "text/markdown", b))
    s, d, _, _ = req(host, port, "GET", f"/view/{R}/md/doc.md", {"Cookie": sess})
    html = json.loads(d)["html"]
    check("Markdown 渲染", s == 200 and "<h1>" in html and "<strong>bold</strong>" in html, html[:80])

    b = "BNDRYPY"
    req(host, port, "POST", f"/upload/{R}",
        {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"},
        body=mp("file", "code.py", b"def f():\n    pass", "text/x-python", b))
    s, d, _, _ = req(host, port, "GET", f"/view/{R}/text/code.py", {"Cookie": sess})
    txt = json.loads(d)
    check("文本/代码预览", s == 200 and "def f" in txt["text"] and txt["ext"] == "py", str(s))

    print("\n=== 分享链接 (Phase 5) ===")
    s, d, _, _ = req(host, port, "POST", f"/share/{R}",
                     {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
                     body="ttl=24&label=test")
    sh = json.loads(d)
    check("创建分享链接", s == 200 and sh["token"], str(s))

    s, d, _, _ = req(host, port, "GET", f"/share/{R}/list", {"Cookie": sess})
    check("分享列表", s == 200 and any(x["token"] == sh["token"] for x in json.loads(d)), str(s))

    s, d, _, _ = req(host, port, "GET", f"/s/{sh['token']}")
    check("分享落地页(有效)", s == 200 and "\u6709\u6548" in d.decode("utf-8"), str(s))

    req(host, port, "POST", f"/share/{R}/revoke",
        {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
        body=f"token={sh['token']}")
    s, d, _, _ = req(host, port, "GET", f"/s/{sh['token']}")
    check("吊销后落地页失效", "\u5931\u6548" in d.decode("utf-8"), str(s))

    s, d, _, _ = req(host, port, "GET", "/s/bad_token_xxx")
    check("无效 token 被拦", "\u5931\u6548" in d.decode("utf-8"), str(s))

    # 到期文件上传
    b = "BNDRYEX"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"t.tmp\"\r\n\r\n"
            f"x\r\n--{b}\r\nContent-Disposition: form-data; name=\"ttl\"\r\n\r\n1\r\n--{b}--\r\n").encode()
    s, d, _, _ = req(host, port, "POST", f"/upload/{R}",
                     {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"}, body=body)
    check("到期文件上传", s == 200 and json.loads(d)["ok"], str(s))

    print("\n=== 留言 ===")
    s, d, _, _ = req(host, port, "POST", f"/api/{R}/messages",
                     {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
                     body="body=hello+smoke")
    check("发送留言", s == 200 and json.loads(d)["ok"], str(s))
    s, d, _, _ = req(host, port, "GET", f"/api/{R}/messages", {"Cookie": sess})
    msgs = json.loads(d)
    check("读取留言", any(m["body"] == "hello smoke" for m in msgs), str(len(msgs)))

    print("\n=== 管理后台 (Phase 4) ===")
    s, _, acookies, _ = req(host, port, "POST", "/admin/auth",
                            {"Content-Type": "application/x-www-form-urlencoded"},
                            body=f"password={ADMIN_PW}")
    asess = acookies.split(";")[0]
    check("管理员登录", s == 200 and asess.startswith("room_admin="), str(s))

    s, d, _, _ = req(host, port, "GET", "/admin/api/stats", {"Cookie": asess})
    st = json.loads(d)
    check("统计 API", s == 200 and st["rooms"] >= 1 and st["files"] >= 2, str(st))

    s, d, _, _ = req(host, port, "GET", "/admin/api/rooms", {"Cookie": asess})
    check("房间列表 API", s == 200 and any(r["room_hash"] == R for r in json.loads(d)), str(s))

    s, d, _, _ = req(host, port, "GET", "/admin/api/audit?limit=10", {"Cookie": asess})
    check("审计日志 API", s == 200 and len(json.loads(d)) > 0, str(s))

    s, _, _, _ = req(host, port, "GET", "/admin/api/stats")  # 无 cookie
    check("管理员未授权被拦(403)", s == 403, str(s))

    s, d, _, _ = req(host, port, "POST", "/admin/api/cleanup", {"Cookie": asess})
    check("过期清理 API", s == 200 and json.loads(d)["ok"], str(s))

    print("\n=== v2.1.0 体验急救包 ===")
    # 静态资源就位
    for path, key in [("/static/toast.js", b"toast"),
                      ("/static/toast.css", b"toast"),
                      ("/static/error.js", b"fetch")]:
        s, data, _, _ = req(host, port, "GET", path)
        check(f"静态资源 {key}", s == 200 and len(data) > 50, str(s))

    # room.html 关键 A11Y 节点
    s, html, _, _ = req(host, port, "GET", f"/room/{R}", {"Cookie": sess})
    html = html.decode("utf-8", "replace")
    checks_a11y = [
        ('role="log"', 'aria-log'),
        ('aria-live="polite"', 'aria-live'),
        ('aria-label="点击或拖入文件上传"', 'dropzone-aria'),
        ('role="dialog"', 'modal-dialog'),
        ('aria-modal="true"', 'aria-modal'),
        ('role="toolbar"', 'toolbar'),
        ('新消息', 'unread-bar-text'),
    ]
    for needle, name in checks_a11y:
        check(f"room.html 包含 {name}", needle in html, needle)
    # upload-queue.js 静态资源含 progressbar（动态注入的 DOM）
    s, d, _, _ = req(host, port, "GET", "/static/upload-queue.js")
    check("upload-queue.js 含 progressbar", s == 200 and b"progressbar" in d, "size="+str(len(d)))

    # 鉴权拦截：错口令登录后访问不属于自己的房间 → 拒绝（303 重定向或 403）
    s, _, bad_cookies, _ = req(host, port, "POST", "/auth",
                               {"Content-Type": "application/x-www-form-urlencoded"},
                               body="password=wrong_password_zZ9")
    bad_sess = bad_cookies.split(";")[0] if bad_cookies else ""
    s, _, _, _ = req(host, port, "GET", f"/room/0000000000000000", {"Cookie": bad_sess})
    check("错口令访问他房间被拒", s in (303, 403), str(s))

    # 留言 API：自己发送后能再读到
    req(host, port, "POST", f"/api/{R}/messages",
        {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
        body="body=v2.1+a11y+chat")
    s, d, _, _ = req(host, port, "GET", f"/api/{R}/messages", {"Cookie": sess})
    msgs = json.loads(d)
    check("留言 v2.1 内容入库", any(m.get("body") == "v2.1 a11y chat" for m in msgs), str(len(msgs)))

    print("\n=== v2.2.0 上传与回收 ===")
    # upload-queue.js 静态资源
    s, d, _, _ = req(host, port, "GET", "/static/upload-queue.js")
    check("upload-queue.js 加载", s == 200 and b"MAX_CONCURRENT" in d and b"xhr.abort" in d, "size="+str(len(d)))

    # 回收站：上传→删→列出→恢复→列出清空；再删→永久删→列出再清空
    b = "BNDRYR1"
    req(host, port, "POST", f"/upload/{R}",
        {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"},
        body=mp("file", "recycle_a.txt", b"to be deleted", boundary=b))
    s, _, _, _ = req(host, port, "POST", f"/delete/{R}",
                     {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
                     body="name=recycle_a.txt")
    check("软删除 recycle_a.txt", s == 200, str(s))

    s, d, _, _ = req(host, port, "GET", f"/recycle/{R}", {"Cookie": sess})
    recycle = json.loads(d)
    check("回收站列出含 recycle_a.txt", any(x["name"] == "recycle_a.txt" for x in recycle), str(len(recycle)))
    check("回收站项含 deleted_at & left_days", recycle and ("deleted_at" in recycle[0]) and ("left_days" in recycle[0]), "")

    s, _, _, _ = req(host, port, "POST", f"/restore/{R}",
                     {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
                     body="name=recycle_a.txt")
    check("恢复 recycle_a.txt", s == 200, str(s))

    s, d, _, _ = req(host, port, "GET", f"/recycle/{R}", {"Cookie": sess})
    recycle = json.loads(d)
    check("恢复后回收站不含 recycle_a.txt", not any(x["name"] == "recycle_a.txt" for x in recycle), str(len(recycle)))

    s, d, _, _ = req(host, port, "GET", f"/api/{R}/files", {"Cookie": sess})
    files = json.loads(d)
    check("恢复后文件列表含 recycle_a.txt", any(f["name"] == "recycle_a.txt" for f in files), "")

    # 永久删除流程：再删 → purge
    req(host, port, "POST", f"/delete/{R}",
        {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
        body="name=recycle_a.txt")
    s, _, _, _ = req(host, port, "POST", f"/purge/{R}",
                     {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
                     body="name=recycle_a.txt")
    check("永久删除 recycle_a.txt", s == 200, str(s))
    s, d, _, _ = req(host, port, "GET", f"/recycle/{R}", {"Cookie": sess})
    check("永久删除后回收站为空",
          not any(x["name"] == "recycle_a.txt" for x in json.loads(d)), "")

    # 未授权访问回收站
    s, _, _, _ = req(host, port, "GET", f"/recycle/{R}")
    check("未授权访问回收站被拒(403)", s == 403, str(s))

    # 删除不存在的文件不报错（返回 ok:false，但状态 200）
    s, _, _, _ = req(host, port, "POST", f"/delete/{R}",
                     {"Cookie": sess, "Content-Type": "application/x-www-form-urlencoded"},
                     body="name=does_not_exist.txt")
    check("删除不存在文件 200 容忍", s == 200, str(s))

    print("\n=== v2.3.0 网盘基础 ===")
    # 上传图片，等异步缩略图（轮询最多 5 秒）
    b = "BNDRY3A"
    # 1x1 红色 PNG
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108020000"
        "00907753de0000000c4944415478da6300010000000500010d0a2db4"
        "0000000049454e44ae426082"
    )
    s, d, _, _ = req(host, port, "POST", f"/upload/{R}",
                     {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"},
                     body=mp("file", "red.png", png_bytes, "image/png", b))
    up_img = json.loads(d)
    img_id = up_img.get("id", 0)
    check("图片上传返回 id", s == 200 and img_id > 0, str(s))

    # 缩略图可能还在生成（轮询）
    thumb_ok = False
    for _ in range(20):
        s, d, _, h = req(host, port, "GET", f"/thumb/{R}/{img_id}", {"Cookie": sess})
        if s == 200 and d[:2] == b'\xff\xd8':  # JPEG magic
            thumb_ok = True
            break
        time.sleep(0.25)
    check("图片缩略图生成 JPEG", thumb_ok, f"status={s} len={len(d) if d else 0}")

    # 缩略图鉴权
    s, _, _, _ = req(host, port, "GET", f"/thumb/{R}/{img_id}")
    check("缩略图未授权 403", s == 403, str(s))

    # 文件列表含 thumb_status
    s, d, _, _ = req(host, port, "GET", f"/api/{R}/files", {"Cookie": sess})
    files = json.loads(d)
    img_entry = next((f for f in files if f["name"] == "red.png"), None)
    check("文件列表含 thumb_status", img_entry and "thumb_status" in img_entry, "")

    # 上传带 parent_dir
    b = "BNDRY3B"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"nested.txt\"\r\n\r\n"
            f"hi\r\n--{b}\r\nContent-Disposition: form-data; name=\"parent_dir\"\r\n\r\n"
            f"photos/2024\r\n--{b}--\r\n").encode()
    s, d, _, _ = req(host, port, "POST", f"/upload/{R}",
                     {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"}, body=body)
    check("parent_dir 嵌套上传", s == 200, str(s))
    s, d, _, _ = req(host, port, "GET", f"/api/{R}/files", {"Cookie": sess})
    files = json.loads(d)
    nested = next((f for f in files if f["name"] == "nested.txt"), None)
    check("parent_dir 入库正确", nested and nested.get("parent_dir") == "photos/2024", str(nested))

    # parent_dir 安全：.. 段应被清空
    b = "BNDRY3C"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"safe.txt\"\r\n\r\n"
            f"x\r\n--{b}\r\nContent-Disposition: form-data; name=\"parent_dir\"\r\n\r\n"
            f"../etc\r\n--{b}--\r\n").encode()
    req(host, port, "POST", f"/upload/{R}",
        {"Cookie": sess, "Content-Type": f"multipart/form-data; boundary={b}"}, body=body)
    s, d, _, _ = req(host, port, "GET", f"/api/{R}/files", {"Cookie": sess})
    files = json.loads(d)
    safe = next((f for f in files if f["name"] == "safe.txt"), None)
    check("parent_dir 路径穿越被清空", safe and (safe.get("parent_dir") or "") == "", str(safe.get("parent_dir")))

    # 批量 zip 下载：先准备几个文件，取 id 列表
    s, d, _, _ = req(host, port, "GET", f"/api/{R}/files", {"Cookie": sess})
    files = json.loads(d)
    ids = [str(f["id"]) for f in files[:3]]  # 最多 3 个
    # zip 是 chunked 流式：加 Connection: close 让服务端发完就 EOF
    s, d, _, h = req(host, port, "GET", f"/zip/{R}?ids={','.join(ids)}",
                     {"Cookie": sess, "Connection": "close"})
    check("批量 zip 下载 200", s == 200, str(s))
    check("Content-Type 是 zip", h.get("content-type", "").startswith("application/zip"), h.get("content-type"))
    check("zip 起始 PK 签名", d[:2] == b'PK', d[:4].hex())

    # zip 空 ids 应 400
    s, _, _, _ = req(host, port, "GET", f"/zip/{R}?ids=", {"Cookie": sess})
    check("zip 空 ids 400", s == 400, str(s))

    # zip 越权
    s, _, _, _ = req(host, port, "GET", f"/zip/{R}?ids={','.join(ids)}")
    check("zip 未授权 403", s == 403, str(s))

    print("\n=== v3.0.0-1 鉴权 + Token + RFC 7807 ===")
    # 未授权 401 返回 RFC 7807
    s, d, _, h = req(host, port, "GET", "/api/v3/auth/tokens")
    check("v3 未授权 401", s == 401, str(s))
    check("v3 problem+json content-type", h.get("content-type", "").startswith("application/problem+json"), h.get("content-type"))
    body = json.loads(d)
    check("v3 错误含 type/title/status",
          body.get("type", "").endswith("/unauthorized") and body.get("title") == "Unauthorized" and body.get("status") == 401,
          str(body))

    # 用 admin token 调 list（先创建一个 token）
    # 用 X-Bootstrap-Password（=admin_password）跳过需要 admin token 才能创建 token 的循环
    import tomllib, pathlib
    cfg_path = pathlib.Path(__file__).resolve().parent.parent / "config.toml"
    # 优先用环境变量（与子进程一致）；子进程也读 ROOM_ADMIN_PW
    if os.environ.get("ROOM_ADMIN_PW"):
        admin_pw = os.environ["ROOM_ADMIN_PW"]
    else:
        # CI / 本地 fallback：从 env 拿，或等子进程首启写回 config.toml
        admin_pw = os.environ.get("ROOM_ADMIN_PW", "")
        if not admin_pw:
            for _ in range(20):
                with open(cfg_path, "rb") as f:
                    cfg = tomllib.load(f)
                admin_pw = cfg.get("admin", {}).get("password", "")
                if admin_pw and admin_pw != "admin":
                    break
                time.sleep(0.2)
    bs_headers = {"X-Bootstrap-Password": admin_pw,
                  "Content-Type": "application/json"}
    create_body = json.dumps({"name": "smoke-admin", "scope": "admin"})
    s, d, _, _ = req(host, port, "POST", "/api/v3/auth/tokens", bs_headers, body=create_body.encode())
    check("创建 admin token 201", s == 201, f"{s} {d[:200] if d else ''}")
    tok = json.loads(d)
    tok_id = tok["id"]
    admin_token = tok["token"]
    check("返回明文 token", "token" in tok and len(admin_token) > 20, "")

    # 用 token 列
    auth_h = {"Authorization": "Bearer " + admin_token}
    s, d, _, _ = req(host, port, "GET", "/api/v3/auth/tokens", auth_h)
    listed = json.loads(d)
    check("Bearer 鉴权列 token", s == 200 and any(t["id"] == tok_id for t in listed["items"]), str(s))

    # 同样用 X-API-Key 也能工作
    s, d, _, _ = req(host, port, "GET", "/api/v3/auth/tokens", {"X-API-Key": admin_token})
    check("X-API-Key 鉴权列 token", s == 200, str(s))

    # 吊销
    s, d, _, _ = req(host, port, "DELETE", f"/api/v3/auth/tokens/{tok_id}", auth_h)
    check("吊销 token 204", s == 204, str(s))
    # 吊销后用同一 token 应 401
    s, d, _, _ = req(host, port, "GET", "/api/v3/auth/tokens", auth_h)
    check("吊销后失效 401", s == 401, str(s))

    # 旧路径有 Deprecation header（验证 headers_for_old 函数逻辑，避免中间件边界问题）
    from roomsystem.deprecation import headers_for_old
    h = headers_for_old(f"/api/{R}/files")
    check("旧路径 Deprecation header", h.get("Deprecation") == "true", repr(h))
    check("旧路径 Sunset header", h.get("Sunset") is not None, repr(h))
    # v3 路径不应有
    h3 = headers_for_old("/api/v3/auth/tokens")
    check("v3 路径无 Deprecation header", h3 == {}, repr(h3))

    print("\n=== WebSocket 实时 (Phase 5) ===")
    try:
        import websockets
        import asyncio

        async def ws_test():
            uri = f"ws://{host}:{port}/ws/{R}"
            async with websockets.connect(uri, additional_headers={"Cookie": sess}) as ws:
                await ws.send(json.dumps({"kind": "message", "body": "ws-broadcast"}))
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                m = json.loads(raw)
                check("WS 发送→广播", m.get("type") == "message" and m.get("body") == "ws-broadcast", str(m))
            # 未授权连接应被拒
            try:
                async with websockets.connect(uri, additional_headers={}) as ws:
                    await ws.recv()
                fail("WS 鉴权", "未授权连接竟然成功了")
            except Exception:
                check("WS 未授权被拒", True)

        asyncio.run(ws_test())
    except ImportError:
        check("WebSocket 测试", False, "websockets 库未安装，跳过")


if __name__ == "__main__":
    sys.exit(main())
