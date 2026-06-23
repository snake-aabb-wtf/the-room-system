"""End-to-end integration test for the ``trs`` CLI / SDK.

It spins up an in-process The Room System server (random port, isolated data
dir), then drives the CLI via subprocesses and the SDK via in-process calls
to verify the full user flow:

  bootstrap a token  →  list tokens  →  admin stats / rooms  →
  upload a file  →  list / show / rename / download  →
  batch / recycle  →  webhooks CRUD  →  revoke token.

The CLI is invoked as ``python -m trs.cli ...`` (the entry point and the
module entry point are equivalent).  This avoids depending on a globally
installed ``trs`` console script.
"""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TRS_DIR = BASE / "trs"  # `python -m trs.cli` looks here

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


def wait_up(host: str, port: int, timeout: float = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def run_cli(*args: str, env: dict | None = None) -> tuple[int, str, str]:
    """Run the CLI as ``python -m trs.cli ...`` and capture stdout/stderr.

    We deliberately run from a tmp directory (not the project root) and
    strip the project root from ``PYTHONPATH`` so the ``trs/`` source dir
    under the project root doesn't shadow the installed ``trs`` package
    via ``sys.path[0]``.
    """

    cmd = [sys.executable, "-m", "trs.cli", *args]
    safe_env = dict(env or os.environ)
    # Drop BASE and any reference to it from PYTHONPATH so the project
    # root's ``trs/`` directory (which is a namespace package, not the
    # real package) can't shadow the installed ``trs`` distribution.
    pp = safe_env.get("PYTHONPATH", "")
    parts = [p for p in pp.split(os.pathsep) if p and Path(p).resolve() != BASE.resolve() and p != str(TRS_DIR)]
    safe_env["PYTHONPATH"] = os.pathsep.join(parts) if parts else ""
    proc = subprocess.run(cmd, capture_output=True, env=safe_env, cwd=tempfile.gettempdir())
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


# ─── in-process SDK sanity check (no subprocess needed) ──────────
def sdk_round_trip(host: str, port: int, admin_token: str) -> None:
    """Hit every SDK method that doesn't require cookies.  This catches
    any regression in argument names or URL shape that the CLI would
    otherwise paper over."""
    import httpx

    # The ``trs/`` source dir at the project root is a namespace package
    # (no __init__.py) that would shadow the installed ``trs`` package.
    # Strip it from sys.path so the real package wins.
    sys.path[:] = [p for p in sys.path if p not in ("", str(BASE), str(TRS_DIR))]
    from trs import TrsClient, TrsError  # type: ignore

    base = f"http://{host}:{port}"

    async def go() -> None:
        async with TrsClient(base, token=admin_token) as cli:
            stats = await cli.admin_stats()
            check("SDK admin_stats 200", isinstance(stats, dict) and "rooms" in stats, str(stats)[:120])

            rooms = await cli.admin_rooms()
            check("SDK admin_rooms list", isinstance(rooms, list), str(type(rooms)))

            toks = await cli.list_tokens()
            check("SDK list_tokens", isinstance(toks, list) and any(t.get("scope") == "admin" for t in toks),
                  str(len(toks)))

            wh = await cli.list_webhooks()
            check("SDK list_webhooks", isinstance(wh, list), str(len(wh)))

            # 404 / 4xx surface as TrsError
            try:
                await cli.get_token(99999999)
            except TrsError as e:
                check("SDK 404 raises TrsError", e.status == 404, f"status={e.status}")

    asyncio.run(go())


# ─── CLI workflow ────────────────────────────────────────────────
def cli_workflow(host: str, port: int) -> None:
    base = f"http://{host}:{port}"
    admin_pw = "ci_cli_admin_zz"
    # Use a per-run config so we never clobber a user's real config.
    tmp_cfg = Path(tempfile.gettempdir()) / f"trs_test_{os.getpid()}_{int(time.time())}.toml"
    if tmp_cfg.exists():
        tmp_cfg.unlink()

    cli_env = dict(os.environ)
    cli_env["TRS_CONFIG"] = str(tmp_cfg)
    cli_env["PYTHONPATH"] = str(BASE) + os.pathsep + str(TRS_DIR) + os.pathsep + cli_env.get("PYTHONPATH", "")

    # 1) config path is real & writable
    rc, out, err = run_cli("config", "path", env=cli_env)
    check("CLI config path", rc == 0 and str(tmp_cfg) in out, f"rc={rc} out={out!r} err={err!r}")

    # 2) bootstrap: create first admin token, persists to profile
    rc, out, err = run_cli("auth", "bootstrap", "--password", admin_pw, "--name", "cli-bootstrap",
                           "--scope", "admin", "--base-url", base, env=cli_env)
    check("CLI auth bootstrap", rc == 0, f"rc={rc} stderr={err!r}")
    # The CLI prints a confirmation line + the token record as JSON.  We
    # pull the token from the on-disk config (more reliable than parsing).
    sys.path[:] = [p for p in sys.path if p not in ("", str(BASE), str(TRS_DIR))]
    from trs.config import load_config  # type: ignore
    cfg = load_config(tmp_cfg)
    prof = cfg.get("default")
    check("CLI bootstrap saved token to profile", bool(prof.token) and len(prof.token) >= 20,
          prof.token[:12] if prof.token else "(empty)")
    admin_token = prof.token

    # 3) list tokens
    rc, out, err = run_cli("auth", "list", "--json", env=cli_env)
    check("CLI auth list", rc == 0, f"rc={rc} err={err!r}")
    print(f"  [debug] auth list raw: {out!r}")
    body = json.loads(out)
    print(f"  [debug] body type: {type(body).__name__}, sample: {str(body)[:200]}")
    # body may be {"items": [...]} or a bare list; normalise.
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    check("CLI auth list contains bootstrap token",
          any((t.get("name") if isinstance(t, dict) else None) == "cli-bootstrap"
              and "admin" in ((t.get("scope") or "") if isinstance(t, dict) else "")
              for t in items),
          str([(t.get("name") if isinstance(t, dict) else t, (t.get("scope") or "") if isinstance(t, dict) else "") for t in items]))

    # 4) admin stats (table)
    rc, out, err = run_cli("rooms", "stats", env=cli_env)
    check("CLI rooms stats", rc == 0 and "rooms" in out, f"rc={rc} err={err!r} out={out[:120]}")

    # 5) admin rooms --json
    rc, out, err = run_cli("rooms", "list", "--json", env=cli_env)
    check("CLI rooms list --json", rc == 0, f"rc={rc} err={err!r}")
    rooms = json.loads(out)
    check("CLI rooms list items", isinstance(rooms, dict) and "items" in rooms, str(type(rooms)))

    # 6) upload a file via CLI
    src = Path(tempfile.gettempdir()) / f"trs_upload_{os.getpid()}.txt"
    src.write_text("hello from trs CLI", encoding="utf-8")
    PW = "ci_cli_room_pw"
    R = hashlib.sha256(PW.encode()).hexdigest()[:16]
    # Pre-create the room by logging in via /auth (sets cookie server-side).
    c = http.client.HTTPConnection(host, port, timeout=5)
    c.request("POST", "/auth", body=f"password={PW}",
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    r = c.getresponse()
    r.read()
    cookie = (r.getheader("set-cookie") or "").split(";", 1)[0]
    c.close()
    check("room pre-created via /auth", cookie.startswith("room_session="), cookie)

    # Persist the room cookie into the trs profile so the CLI sends it on
    # cookie-gated endpoints (file upload, messages, share).
    sys.path[:] = [p for p in sys.path if p not in ("", str(BASE), str(TRS_DIR))]
    from trs.config import load_config as _lc, save_config as _sc  # type: ignore
    _cfg = _lc(tmp_cfg)
    _prof = _cfg.get("default")
    _prof.room_cookie = cookie
    _cfg.upsert(_prof)
    _sc(_cfg)

    rc, out, err = run_cli("files", "upload", R, str(src), "--as", "cli-upload.txt", env=cli_env)
    check("CLI files upload", rc == 0, f"rc={rc} stderr={err!r} out={out[:200]}")

    # 7) list files
    rc, out, err = run_cli("files", "list", R, env=cli_env)
    check("CLI files list", rc == 0 and "cli-upload.txt" in out, f"rc={rc} err={err!r} out={out[:200]}")

    # 8) show file
    rc, out, err = run_cli("files", "list", R, "--json", env=cli_env)
    check("CLI files list --json", rc == 0, f"rc={rc} err={err!r}")
    body = json.loads(out)
    fid = next((f["id"] for f in body["items"] if f["name"] == "cli-upload.txt"), None)
    check("CLI files find uploaded id", isinstance(fid, int) and fid > 0, f"fid={fid}")

    rc, out, err = run_cli("files", "show", R, str(fid), env=cli_env)
    check("CLI files show", rc == 0, f"rc={rc} err={err!r}")

    # 9) rename file
    rc, out, err = run_cli("files", "rename", R, str(fid), "cli-renamed.txt", env=cli_env)
    check("CLI files rename", rc == 0, f"rc={rc} err={err!r}")

    # 10) download via presigned URL
    dst = Path(tempfile.gettempdir()) / f"trs_dl_{os.getpid()}.txt"
    if dst.exists():
        dst.unlink()
    rc, out, err = run_cli("files", "download", R, str(fid), str(dst), env=cli_env)
    check("CLI files download (presign)", rc == 0, f"rc={rc} err={err!r}")
    check("CLI files download bytes match", dst.exists() and dst.read_bytes() == b"hello from trs CLI",
          f"size={dst.stat().st_size if dst.exists() else 'missing'}")

    # 11) soft-delete → list recycle → purge
    rc, out, err = run_cli("files", "delete", R, str(fid), env=cli_env)
    check("CLI files delete (soft)", rc == 0, f"rc={rc} err={err!r}")

    rc, out, err = run_cli("files", "recycle", "list", R, env=cli_env)
    check("CLI recycle list", rc == 0 and "cli-renamed.txt" in out, f"rc={rc} err={err!r} out={out[:200]}")

    rc, out, err = run_cli("files", "purge", R, str(fid), env=cli_env)
    check("CLI files purge", rc == 0, f"rc={rc} err={err!r}")

    rc, out, err = run_cli("files", "recycle", "list", R, env=cli_env)
    check("CLI recycle empty after purge", "cli-renamed.txt" not in out, f"out={out[:200]}")

    # 12) batch: upload 2 more, batch-delete both
    for i in range(2):
        p = Path(tempfile.gettempdir()) / f"trs_batch_{i}_{os.getpid()}.txt"
        p.write_text(f"batch {i}", encoding="utf-8")
        run_cli("files", "upload", R, str(p), "--as", f"batch_{i}.txt", env=cli_env)
    rc, out, err = run_cli("files", "list", R, "--json", env=cli_env)
    body = json.loads(out)
    batch_ids = [f["id"] for f in body["items"] if f["name"].startswith("batch_")]
    check("CLI batch: 2 batch files uploaded", len(batch_ids) == 2, str(batch_ids))

    rc, out, err = run_cli("files", "batch", R, "delete", *map(str, batch_ids), env=cli_env)
    check("CLI files batch delete", rc == 0, f"rc={rc} err={err!r}")

    # 13) webhook CRUD
    rc, out, err = run_cli("webhook", "create", "http://127.0.0.1:1/hook",
                           "--secret", "cli-secret-xxxx", "--event", "file.uploaded", env=cli_env)
    check("CLI webhook create", rc == 0, f"rc={rc} err={err!r} out={out[:200]}")
    rec = json.loads(out)
    wid = rec["id"]
    check("CLI webhook returns id", isinstance(wid, int) and wid > 0, str(wid))

    rc, out, err = run_cli("webhook", "list", env=cli_env)
    check("CLI webhook list", rc == 0 and "/hook" in out, f"rc={rc} err={err!r} out={out[:200]}")

    rc, out, err = run_cli("webhook", "update", str(wid), "--enable", env=cli_env)
    check("CLI webhook update enable", rc == 0, f"rc={rc} err={err!r}")

    rc, out, err = run_cli("webhook", "logs", str(wid), env=cli_env)
    check("CLI webhook logs", rc == 0, f"rc={rc} err={err!r}")

    rc, out, err = run_cli("webhook", "delete", str(wid), env=cli_env)
    check("CLI webhook delete", rc == 0, f"rc={rc} err={err!r}")

    # 14) revoke the bootstrap token
    rc, out, err = run_cli("auth", "list", "--json", env=cli_env)
    items = json.loads(out)
    bs = next((t for t in items if t.get("name") == "cli-bootstrap"), None)
    check("CLI bootstrap token present in list", bs is not None, str(items))
    if bs:
        rc, out, err = run_cli("auth", "revoke", str(bs["id"]), env=cli_env)
        check("CLI auth revoke", rc == 0, f"rc={rc} err={err!r}")

    # 15) error path: revoked token should now fail
    rc, out, err = run_cli("rooms", "stats", env=cli_env)
    check("CLI revoked token → 401 surfaces as rc=2", rc == 2, f"rc={rc} stderr={err!r}")

    # 16) config show round-trip
    rc, out, err = run_cli("config", "show", env=cli_env)
    check("CLI config show", rc == 0 and "default" in out, f"rc={rc} err={err!r}")

    # Cleanup
    try:
        tmp_cfg.unlink()
    except OSError:
        pass


def main() -> int:
    sys.path.insert(0, str(BASE))
    tmp = tempfile.mkdtemp(prefix="trs_cli_test_")
    port = free_port()
    print(f"\n>>> 启动 CLI 测试服务: 127.0.0.1:{port}  数据目录: {tmp}")

    os.environ["ROOM_ADMIN_PW"] = "ci_cli_admin_zz"
    env = dict(os.environ)
    env.update({
        "ROOM_HOST": "127.0.0.1",
        "ROOM_PORT": str(port),
        "ROOM_DATA_DIR": str(tmp),
        "ROOM_ADMIN_PW": "ci_cli_admin_zz",
        "PYTHONPATH": str(BASE),
    })
    proc = subprocess.Popen(
        [sys.executable, "-c",
         f"import uvicorn; from roomsystem.app import create_app; "
         f"uvicorn.run(create_app(), host='127.0.0.1', port={port}, log_level='warning')"],
        cwd=str(BASE), env=env,
        stdout=open("_cli_out.txt", "wb"),
        stderr=open("_cli_stderr.txt", "wb"),
    )
    try:
        if not wait_up("127.0.0.1", port, timeout=60):
            err = proc.stderr.read().decode("utf-8", "replace")[:500] if proc.stderr else "(no stderr)"
            print(f"!!! CLI 测试服务启动失败:\n{err}")
            return 1
        print("\n=== SDK 直接调用 ===")
        # Create a bootstrap token via SDK to seed the CLI workflow.
        import httpx
        with httpx.Client(timeout=10) as raw:
            r = raw.post(
                f"http://127.0.0.1:{port}/api/v3/auth/tokens",
                headers={"X-Bootstrap-Password": "ci_cli_admin_zz", "Content-Type": "application/json"},
                content=json.dumps({"name": "sdk-seed", "scope": "admin"}),
            )
        check("SDK-seed token 201", r.status_code == 201, f"status={r.status_code}")
        admin_token = r.json()["token"]

        sdk_round_trip("127.0.0.1", port, admin_token)

        print("\n=== CLI 子命令流程 ===")
        cli_workflow("127.0.0.1", port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n>>> CLI 测试结果: {_passed} 通过, {_failed} 失败")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
