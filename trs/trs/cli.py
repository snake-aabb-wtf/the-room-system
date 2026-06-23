"""``trs`` command-line interface for The Room System.

Sub-commands::

    trs auth bootstrap   create the first admin token (uses bootstrap password)
    trs auth list        list API tokens
    trs auth create      create a new API token
    trs auth show        show one token
    trs auth rename      rename a token
    trs auth expire      set token expiry (unix timestamp, 0 = permanent)
    trs auth revoke      revoke a token

    trs rooms list       list rooms (admin)
    trs rooms show       show a single room (admin)
    trs rooms audit      list recent audit events
    trs rooms cleanup    force the cleanup task
    trs rooms stats      show global stats

    trs files list       list files in a room
    trs files show       show a single file
    trs files rename     rename / move a file
    trs files delete     soft-delete a file
    trs files restore    restore from recycle bin
    trs files purge      permanently delete
    trs files batch      batch op (delete|restore|purge)
    trs files recycle    list / empty the recycle bin
    trs files download   download a file via presigned URL
    trs files upload     upload a file (curl-style via /upload/{rh})

    trs msg list         list chat messages
    trs msg post         post a chat message

    trs share create     create a share link
    trs share list       list share links
    trs share revoke     revoke a share link

    trs webhook list     list webhooks
    trs webhook create   create a webhook
    trs webhook show     show one webhook
    trs webhook update   update a webhook
    trs webhook delete   delete a webhook
    trs webhook logs     show delivery history

    trs config show      print the resolved config
    trs config set       set base_url / token / api_key
    trs config path      print config file path
    trs config profiles  list profile names
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .client import TrsClient, TrsError
from .config import (
    Config,
    Profile,
    active_profile_name,
    load_config,
    save_config,
)


# ─── small helpers ────────────────────────────────────────────────
def _print_json(data: Any, *, fp=sys.stdout) -> None:
    json.dump(data, fp, ensure_ascii=False, indent=2, default=str)
    fp.write("\n")


def _print_table(rows: list[dict], columns: list[tuple[str, str]], *, fp=sys.stdout) -> None:
    """Render a list of dicts as an aligned text table.

    ``columns`` is a list of ``(header, key)`` pairs.  Missing keys render
    as an empty cell.
    """
    if not rows:
        print("(no rows)", file=fp)
        return
    str_rows: list[list[str]] = []
    for r in rows:
        str_rows.append([str(r.get(c[1], "")) for c in columns])
    widths = [max(len(c[0]), max((len(row[i]) for row in str_rows), default=0))
              for i, c in enumerate(columns)]
    sep = "  "
    print(sep.join(c[0].ljust(widths[i]) for i, c in enumerate(columns)), file=fp)
    print(sep.join("-" * w for w in widths), file=fp)
    for row in str_rows:
        print(sep.join(row[i].ljust(widths[i]) for i, _ in enumerate(columns)), file=fp)


def _human_size(n: Any) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    units = ["B", "KB", "MB", "GB", "TB"]
    for u in units:
        if n < 1024:
            return f"{n:.1f}{u}" if u != "B" else f"{int(n)}{u}"
        n /= 1024
    return f"{n:.1f}PB"


def _err(msg: str) -> None:
    print(f"trs: {msg}", file=sys.stderr)


def _resolve(args: argparse.Namespace) -> tuple[TrsClient, Config]:
    """Build a TrsClient and a Config from CLI args / env / file."""

    cfg = load_config(getattr(args, "config", None))
    name = getattr(args, "profile", None) or active_profile_name()
    if name not in cfg.profiles and not args.base_url and not args.token and not args.api_key:
        # No profile, no overrides: still allow it (point at localhost).
        profile = Profile(name=name)
    else:
        profile = cfg.get(name)
    base_url = args.base_url or os.environ.get("TRS_BASE_URL") or profile.base_url
    token = args.token or os.environ.get("TRS_TOKEN") or profile.token
    api_key = args.api_key or os.environ.get("TRS_API_KEY") or profile.api_key
    room_cookie = os.environ.get("TRS_ROOM_COOKIE") or profile.room_cookie
    timeout = float(args.timeout) if getattr(args, "timeout", None) else 30.0
    return TrsClient(base_url, token=token, api_key=api_key, room_cookie=room_cookie, timeout=timeout), cfg


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="Path to config file", default=None)
    p.add_argument("--profile", help="Profile name (default: $TRS_PROFILE or 'default')", default=None)
    p.add_argument("--base-url", help="Override base URL (env TRS_BASE_URL)", default=None)
    p.add_argument("--token", help="Override API token (env TRS_TOKEN)", default=None)
    p.add_argument("--api-key", help="Override API key (env TRS_API_KEY)", default=None)
    p.add_argument("--timeout", help="HTTP timeout seconds", type=float, default=None)
    p.add_argument("--json", help="Output raw JSON instead of tables", action="store_true")


def _common_parent(add_help: bool = False) -> argparse.ArgumentParser:
    """Build a *parent* parser that holds the common CLI flags.

    Subcommand parsers use ``parents=[_common_parent()]`` to inherit
    ``--config / --profile / --base-url / --token / --api-key / --timeout / --json``
    without repeating them on every leaf.  ``add_help`` defaults to
    ``False`` because subparsers get ``-h/--help`` automatically and the
    parent would otherwise conflict.
    """
    p = argparse.ArgumentParser(add_help=add_help)
    _add_common(p)
    return p


# ─── top-level arg parser ────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trs",
        description="Official CLI for The Room System",
    )
    p.add_argument("--version", action="version", version=f"trs {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # config
    pc = sub.add_parser("config", help="Manage trs config / profiles")
    pc.add_argument("--config", help="Path to config file (env TRS_CONFIG)", default=None)
    psc = pc.add_subparsers(dest="sub", required=True)
    psc.add_parser("show").set_defaults(fn=cmd_config_show)
    psc.add_parser("path").set_defaults(fn=cmd_config_path)
    psc.add_parser("profiles").set_defaults(fn=cmd_config_profiles)
    pset = psc.add_parser("set")
    pset.add_argument("key", help="base_url|token|api_key|default")
    pset.add_argument("value")
    pset.set_defaults(fn=cmd_config_set)
    punset = psc.add_parser("unset")
    punset.add_argument("key")
    punset.set_defaults(fn=cmd_config_unset)
    pnew = psc.add_parser("new-profile")
    pnew.add_argument("name")
    pnew.add_argument("--base-url", default=None)
    pnew.set_defaults(fn=cmd_config_new_profile)

    # auth
    pa = sub.add_parser("auth", help="Manage API tokens")
    _add_common(pa)
    psa = pa.add_subparsers(dest="sub", required=True)
    _cp = _common_parent
    psa.add_parser("list", parents=[_cp()]).set_defaults(fn=cmd_auth_list)
    pbootstrap = psa.add_parser("bootstrap", parents=[_cp()])
    pbootstrap.add_argument("--password", required=True, help="Admin bootstrap password")
    pbootstrap.add_argument("--name", default="bootstrap-token")
    pbootstrap.add_argument("--scope", default="admin")
    pbootstrap.set_defaults(fn=cmd_auth_bootstrap)
    pcreate = psa.add_parser("create", parents=[_cp()])
    pcreate.add_argument("--name", required=True)
    pcreate.add_argument("--scope", default="user")
    pcreate.add_argument("--room", default=None, help="Bind to a specific room hash")
    pcreate.add_argument("--expires", type=float, default=None,
                          help="Expiry in hours from now (omit = permanent)")
    pcreate.set_defaults(fn=cmd_auth_create)
    pshow = psa.add_parser("show", parents=[_cp()])
    pshow.add_argument("tid", type=int)
    pshow.set_defaults(fn=cmd_auth_show)
    pren = psa.add_parser("rename", parents=[_cp()])
    pren.add_argument("tid", type=int)
    pren.add_argument("name")
    pren.set_defaults(fn=cmd_auth_rename)
    pexp = psa.add_parser("expire", parents=[_cp()])
    pexp.add_argument("tid", type=int)
    pexp.add_argument("ts", type=float, help="Unix timestamp (0=permanent, -1=no change)")
    pexp.set_defaults(fn=cmd_auth_expire)
    pexp2 = psa.add_parser("revoke", parents=[_cp()])
    pexp2.add_argument("tid", type=int)
    pexp2.set_defaults(fn=cmd_auth_revoke)

    # rooms / admin
    pr = sub.add_parser("rooms", help="Admin: rooms, audit, cleanup, stats")
    _add_common(pr)
    psr = pr.add_subparsers(dest="sub", required=True)
    psl = psr.add_parser("list", parents=[_cp()])
    psl.add_argument("--q", default="")
    psl.add_argument("--page", type=int, default=1)
    psl.add_argument("--per-page", type=int, default=50)
    psl.set_defaults(fn=cmd_rooms_list)
    pss = psr.add_parser("show", parents=[_cp()])
    pss.add_argument("room")
    pss.set_defaults(fn=cmd_rooms_show)
    psa2 = psr.add_parser("audit", parents=[_cp()])
    psa2.add_argument("--page", type=int, default=1)
    psa2.add_argument("--per-page", type=int, default=100)
    psa2.add_argument("--action", default="")
    psa2.add_argument("--room", dest="room_hash", default="")
    psa2.add_argument("--ip", default="")
    psa2.set_defaults(fn=cmd_rooms_audit)
    psc2 = psr.add_parser("cleanup", parents=[_cp()]).set_defaults(fn=cmd_rooms_cleanup)
    pss2 = psr.add_parser("stats", parents=[_cp()]).set_defaults(fn=cmd_rooms_stats)

    # files
    pf = sub.add_parser("files", help="Manage files in a room")
    _add_common(pf)
    psf = pf.add_subparsers(dest="sub", required=True)
    pf_list = psf.add_parser("list", parents=[_cp()])
    pf_list.add_argument("room")
    pf_list.add_argument("--q", default="")
    pf_list.add_argument("--parent", default=None)
    pf_list.add_argument("--ext", default=None, help="Comma-separated ext filter")
    pf_list.add_argument("--sort", default="time")
    pf_list.add_argument("--page", type=int, default=1)
    pf_list.add_argument("--per-page", type=int, default=50)
    pf_list.add_argument("--include-deleted", action="store_true")
    pf_list.set_defaults(fn=cmd_files_list)
    pf_show = psf.add_parser("show", parents=[_cp()])
    pf_show.add_argument("room")
    pf_show.add_argument("fid", type=int)
    pf_show.set_defaults(fn=cmd_files_show)
    pf_ren = psf.add_parser("rename", parents=[_cp()])
    pf_ren.add_argument("room")
    pf_ren.add_argument("fid", type=int)
    pf_ren.add_argument("new_name")
    pf_ren.add_argument("--parent", default=None)
    pf_ren.set_defaults(fn=cmd_files_rename)
    pf_del = psf.add_parser("delete", parents=[_cp()])
    pf_del.add_argument("room")
    pf_del.add_argument("fid", type=int)
    pf_del.set_defaults(fn=cmd_files_delete)
    pf_res = psf.add_parser("restore", parents=[_cp()])
    pf_res.add_argument("room")
    pf_res.add_argument("fid", type=int)
    pf_res.set_defaults(fn=cmd_files_restore)
    pf_pur = psf.add_parser("purge", parents=[_cp()])
    pf_pur.add_argument("room")
    pf_pur.add_argument("fid", type=int)
    pf_pur.set_defaults(fn=cmd_files_purge)
    pf_batch = psf.add_parser("batch", parents=[_cp()])
    pf_batch.add_argument("room")
    pf_batch.add_argument("op", choices=["delete", "restore", "purge"])
    pf_batch.add_argument("ids", nargs="+", type=int)
    pf_batch.set_defaults(fn=cmd_files_batch)
    pf_rec = psf.add_parser("recycle", parents=[_cp()])
    pfr_sub = pf_rec.add_subparsers(dest="rsub", required=True)
    pfr_list = pfr_sub.add_parser("list", parents=[_cp()])
    pfr_list.add_argument("room")
    pfr_list.set_defaults(fn=cmd_files_recycle_list)
    pfr_emp = pfr_sub.add_parser("empty", parents=[_cp()])
    pfr_emp.add_argument("room")
    pfr_emp.set_defaults(fn=cmd_files_recycle_empty)
    pf_dl = psf.add_parser("download", parents=[_cp()])
    pf_dl.add_argument("room")
    pf_dl.add_argument("fid", type=int)
    pf_dl.add_argument("dest")
    pf_dl.set_defaults(fn=cmd_files_download)
    pf_up = psf.add_parser("upload", parents=[_cp()])
    pf_up.add_argument("room")
    pf_up.add_argument("path")
    pf_up.add_argument("--as", dest="as_name", default=None)
    pf_up.set_defaults(fn=cmd_files_upload)

    # messages
    pm = sub.add_parser("msg", help="Room chat messages")
    _add_common(pm)
    psm = pm.add_subparsers(dest="sub", required=True)
    pml = psm.add_parser("list", parents=[_cp()])
    pml.add_argument("room")
    pml.set_defaults(fn=cmd_msg_list)
    pmp = psm.add_parser("post", parents=[_cp()])
    pmp.add_argument("room")
    pmp.add_argument("body")
    pmp.add_argument("--nick", default=None)
    pmp.set_defaults(fn=cmd_msg_post)

    # share
    psh = sub.add_parser("share", help="Share link management")
    _add_common(psh)
    pssh = psh.add_subparsers(dest="sub", required=True)
    pshc = pssh.add_parser("create", parents=[_cp()])
    pshc.add_argument("room")
    pshc.add_argument("--ttl", type=float, default=None, help="Hours until expiry")
    pshc.add_argument("--label", default="")
    pshc.set_defaults(fn=cmd_share_create)
    pshl = pssh.add_parser("list", parents=[_cp()])
    pshl.add_argument("room")
    pshl.set_defaults(fn=cmd_share_list)
    pshr = pssh.add_parser("revoke", parents=[_cp()])
    pshr.add_argument("room")
    pshr.add_argument("token")
    pshr.set_defaults(fn=cmd_share_revoke)

    # webhook
    pwh = sub.add_parser("webhook", help="Admin: webhook subscriptions")
    _add_common(pwh)
    pswh = pwh.add_subparsers(dest="sub", required=True)
    pswh.add_parser("list", parents=[_cp()]).set_defaults(fn=cmd_webhook_list)
    pswhc = pswh.add_parser("create", parents=[_cp()])
    pswhc.add_argument("url")
    pswhc.add_argument("--name", default="cli-webhook")
    pswhc.add_argument("--secret", required=True, help="HMAC secret (min 4 chars)")
    pswhc.add_argument("--event", action="append", default=None,
                       help="Event name, repeatable")
    pswhc.set_defaults(fn=cmd_webhook_create)
    pswhs = pswh.add_parser("show", parents=[_cp()])
    pswhs.add_argument("wid", type=int)
    pswhs.set_defaults(fn=cmd_webhook_show)
    pswhu = pswh.add_parser("update", parents=[_cp()])
    pswhu.add_argument("wid", type=int)
    pswhu.add_argument("--url", default=None)
    pswhu.add_argument("--secret", default=None)
    pswhu.add_argument("--enable", action="store_true", default=None)
    pswhu.add_argument("--disable", action="store_true", default=None)
    pswhu.add_argument("--event", action="append", default=None)
    pswhu.set_defaults(fn=cmd_webhook_update)
    pswhd = pswh.add_parser("delete", parents=[_cp()])
    pswhd.add_argument("wid", type=int)
    pswhd.set_defaults(fn=cmd_webhook_delete)
    pswhl = pswh.add_parser("logs", parents=[_cp()])
    pswhl.add_argument("wid", type=int)
    pswhl.set_defaults(fn=cmd_webhook_logs)

    return p


# ─── config commands ─────────────────────────────────────────────
def cmd_config_show(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    data = {"default": cfg.default, "path": str(cfg.path),
            "profiles": {n: {"base_url": p.base_url,
                             "token": ("***" + p.token[-4:] if p.token and len(p.token) > 4 else p.token),
                             "api_key": ("***" + p.api_key[-4:] if p.api_key and len(p.api_key) > 4 else p.api_key),
                             **p.extra}
                         for n, p in cfg.profiles.items()}}
    _print_json(data)
    return 0


def cmd_config_path(args: argparse.Namespace) -> int:
    print(str(load_config(args.config).path))
    return 0


def cmd_config_profiles(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if cfg.default:
        print(f"{cfg.default} (default)")
    for n in sorted(cfg.profiles):
        if n != cfg.default:
            print(n)
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    name = active_profile_name()
    prof = cfg.get(name)
    if args.key == "base_url":
        prof.base_url = args.value
    elif args.key == "token":
        prof.token = args.value
    elif args.key == "api_key":
        prof.api_key = args.value
    elif args.key == "default":
        cfg.default = args.value
    else:
        prof.extra[args.key] = args.value
    cfg.upsert(prof)
    save_config(cfg)
    print(f"profile '{name}' updated: {args.key} set")
    return 0


def cmd_config_unset(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    name = active_profile_name()
    prof = cfg.get(name)
    if args.key == "token":
        prof.token = ""
    elif args.key == "api_key":
        prof.api_key = ""
    else:
        _err(f"can't unset {args.key!r}; remove it from {cfg.path} manually")
        return 1
    cfg.upsert(prof)
    save_config(cfg)
    return 0


def cmd_config_new_profile(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    prof = Profile(name=args.name, base_url=args.base_url or "http://127.0.0.1:8000")
    cfg.upsert(prof)
    save_config(cfg)
    print(f"profile '{args.name}' created")
    return 0


# ─── auth commands ───────────────────────────────────────────────
async def _auth_list(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.list_tokens()


def cmd_auth_list(args: argparse.Namespace) -> int:
    items = asyncio.run(_auth_list(args))
    if args.json:
        _print_json(items); return 0
    _print_table(items, [("ID", "id"), ("NAME", "name"), ("SCOPE", "scope"),
                          ("ROOM", "room_hash"), ("EXPIRES", "expires_at"),
                          ("REVOKED", "revoked")])
    return 0


async def _auth_bootstrap(args: argparse.Namespace) -> Any:
    # bootstrap requires no token, so build a *fresh* client without one.
    cfg = load_config(args.config)
    prof = cfg.get(args.profile or active_profile_name())
    base_url = args.base_url or prof.base_url
    async with TrsClient(base_url) as cli:
        return await cli.create_token(
            name=args.name, scope=args.scope,
            bootstrap_password=args.password,
        )


def cmd_auth_bootstrap(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_auth_bootstrap(args))
    except TrsError as e:
        _err(str(e)); return 2
    # Bootstrap may be the very first token; persist it into the active profile.
    cfg = load_config(getattr(args, "config", None))
    name = getattr(args, "profile", None) or active_profile_name()
    prof = cfg.get(name)
    prof.base_url = args.base_url or prof.base_url
    prof.token = rec.get("token", prof.token)
    cfg.upsert(prof)
    save_config(cfg)
    print(f"bootstrap token created and saved to profile '{name}'")
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


async def _auth_create(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    exp = None
    if args.expires is not None:
        exp = time.time() + float(args.expires) * 3600
    async with cli:
        return await cli.create_token(name=args.name, scope=args.scope,
                                       room_hash=args.room, expires_at=exp)


def cmd_auth_create(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_auth_create(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec)
    return 0


async def _auth_show(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.get_token(args.tid)


def cmd_auth_show(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_auth_show(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _auth_rename(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.patch_token(args.tid, name=args.name)


def cmd_auth_rename(args: argparse.Namespace) -> int:
    try:
        asyncio.run(_auth_rename(args))
    except TrsError as e:
        _err(str(e)); return 2
    print(f"token {args.tid} renamed to {args.name!r}"); return 0


async def _auth_expire(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.patch_token(args.tid, expires_at=args.ts)


def cmd_auth_expire(args: argparse.Namespace) -> int:
    try:
        asyncio.run(_auth_expire(args))
    except TrsError as e:
        _err(str(e)); return 2
    print(f"token {args.tid} expires_at = {args.ts}"); return 0


async def _auth_revoke(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.revoke_token(args.tid)


def cmd_auth_revoke(args: argparse.Namespace) -> int:
    try:
        asyncio.run(_auth_revoke(args))
    except TrsError as e:
        _err(str(e)); return 2
    print(f"token {args.tid} revoked"); return 0


# ─── rooms / admin commands ─────────────────────────────────────
async def _rooms_list(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        # Reuse admin_rooms - it already returns {items, pagination}
        return await cli._request("GET", "/api/v3/admin/rooms",
                                  params={"q": args.q, "page": args.page, "per_page": args.per_page})


def cmd_rooms_list(args: argparse.Namespace) -> int:
    try:
        body = asyncio.run(_rooms_list(args))
    except TrsError as e:
        _err(str(e)); return 2
    items = body.get("items", []) if isinstance(body, dict) else body
    if args.json:
        _print_json(body); return 0
    _print_table(items, [("ROOM", "room_hash"), ("NAME", "name"), ("FILES", "fcnt"),
                          ("SIZE", "fsize_h"), ("LAST", "last_h")])
    return 0


async def _rooms_show(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.admin_room(args.room)


def cmd_rooms_show(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_rooms_show(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _rooms_audit(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.admin_audit(page=args.page, per_page=args.per_page,
                                      action=args.action, room_hash=args.room_hash,
                                      ip=args.ip)


def cmd_rooms_audit(args: argparse.Namespace) -> int:
    try:
        body = asyncio.run(_rooms_audit(args))
    except TrsError as e:
        _err(str(e)); return 2
    items = body.get("items", []) if isinstance(body, dict) else []
    if args.json:
        _print_json(body); return 0
    _print_table(items, [("WHEN", "ts_h"), ("ROOM", "room_hash"), ("ACTION", "action"),
                          ("IP", "ip"), ("DETAIL", "detail")])
    return 0


async def _rooms_cleanup(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.admin_cleanup()


def cmd_rooms_cleanup(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_rooms_cleanup(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _rooms_stats(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.admin_stats()


def cmd_rooms_stats(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_rooms_stats(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


# ─── files commands ──────────────────────────────────────────────
async def _files_list(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.list_files(args.room, q=args.q, parent_dir=args.parent,
                                     ext=args.ext, sort=args.sort,
                                     page=args.page, per_page=args.per_page,
                                     include_deleted=args.include_deleted)


def cmd_files_list(args: argparse.Namespace) -> int:
    try:
        body = asyncio.run(_files_list(args))
    except TrsError as e:
        _err(str(e)); return 2
    items = body.get("items", []) if isinstance(body, dict) else []
    if args.json:
        _print_json(body); return 0
    _print_table(items, [("ID", "id"), ("NAME", "name"), ("SIZE", "size_h"),
                          ("WHEN", "created_h"), ("EXPIRES", "expire_h")])
    return 0


async def _files_show(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.get_file(args.room, args.fid)


def cmd_files_show(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_files_show(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _files_rename(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.update_file(args.room, args.fid,
                                      name=args.new_name, parent_dir=args.parent)


def cmd_files_rename(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_files_rename(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _files_delete(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.delete_file(args.room, args.fid)


def cmd_files_delete(args: argparse.Namespace) -> int:
    try:
        asyncio.run(_files_delete(args))
    except TrsError as e:
        _err(str(e)); return 2
    print(f"file {args.fid} deleted (soft)"); return 0


async def _files_restore(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    # The v3 API doesn't have a per-id restore; use batch-restore.
    async with cli:
        return await cli.batch_restore(args.room, [args.fid])


def cmd_files_restore(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_files_restore(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _files_purge(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.batch_purge(args.room, [args.fid])


def cmd_files_purge(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_files_purge(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _files_batch(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    fn = {"delete": cli.batch_delete, "restore": cli.batch_restore, "purge": cli.batch_purge}[args.op]
    async with cli:
        return await fn(args.room, args.ids)


def cmd_files_batch(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_files_batch(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _files_recycle_list(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.list_recycle(args.room)


def cmd_files_recycle_list(args: argparse.Namespace) -> int:
    try:
        items = asyncio.run(_files_recycle_list(args))
    except TrsError as e:
        _err(str(e)); return 2
    if args.json:
        _print_json(items); return 0
    _print_table(items, [("ID", "id"), ("NAME", "name"), ("SIZE", "size_h"),
                          ("DELETED", "deleted_at_h")])
    return 0


async def _files_recycle_empty(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.empty_recycle(args.room)


def cmd_files_recycle_empty(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_files_recycle_empty(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _files_download(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.download_presigned(args.room, args.fid, dest=args.dest)


def cmd_files_download(args: argparse.Namespace) -> int:
    try:
        path = asyncio.run(_files_download(args))
    except TrsError as e:
        _err(str(e)); return 2
    print(f"downloaded to {path}"); return 0


async def _files_upload(args: argparse.Namespace) -> Any:
    import httpx  # local import to keep the SDK import clean
    cli, cfg = _resolve(args)
    prof = cfg.get()
    headers = cli._headers()
    p = Path(args.path)
    with p.open("rb") as fp:
        # The upload endpoint takes a single ``file`` field; the SDK
        # form field is named ``file`` (singular) on the v2 route.
        files = {"file": (args.as_name or p.name, fp)}
        async with httpx.AsyncClient(timeout=30.0) as raw:
            resp = await raw.post(f"{cli.base_url}/upload/{args.room}",
                                  files=files, headers=headers)
    if resp.status_code >= 400:
        raise TrsError(f"upload failed: {resp.status_code} {resp.text}",
                       status=resp.status_code, body=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def cmd_files_upload(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_files_upload(args))
    except (TrsError, OSError) as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


# ─── messages commands ───────────────────────────────────────────
async def _msg_list(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.list_messages(args.room)


def cmd_msg_list(args: argparse.Namespace) -> int:
    try:
        items = asyncio.run(_msg_list(args))
    except TrsError as e:
        _err(str(e)); return 2
    if args.json:
        _print_json(items); return 0
    for m in items:
        print(f"[{m.get('when','')}] {m.get('author','')}: {m.get('body','')}")
    return 0


async def _msg_post(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.post_message(args.room, args.body, nick=args.nick)


def cmd_msg_post(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_msg_post(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


# ─── share commands ──────────────────────────────────────────────
async def _share_create(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.create_share(args.room, ttl_hours=args.ttl, label=args.label)


def cmd_share_create(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_share_create(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _share_list(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.list_shares(args.room)


def cmd_share_list(args: argparse.Namespace) -> int:
    try:
        items = asyncio.run(_share_list(args))
    except TrsError as e:
        _err(str(e)); return 2
    if args.json:
        _print_json(items); return 0
    _print_table(items, [("TOKEN", "token"), ("LABEL", "label"), ("CREATED", "created_h"),
                          ("EXPIRES", "expires_h")])
    return 0


async def _share_revoke(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.revoke_share(args.room, args.token)


def cmd_share_revoke(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_share_revoke(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


# ─── webhook commands ────────────────────────────────────────────
async def _webhook_list(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.list_webhooks()


def cmd_webhook_list(args: argparse.Namespace) -> int:
    try:
        items = asyncio.run(_webhook_list(args))
    except TrsError as e:
        _err(str(e)); return 2
    if args.json:
        _print_json(items); return 0
    _print_table(items, [("ID", "id"), ("URL", "url"), ("EVENTS", "events"),
                          ("ENABLED", "enabled")])
    return 0


async def _webhook_create(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    events = args.event if args.event else None
    async with cli:
        return await cli.create_webhook(args.url, name=args.name, secret=args.secret, events=events)


def cmd_webhook_create(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_webhook_create(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _webhook_show(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.get_webhook(args.wid)


def cmd_webhook_show(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_webhook_show(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _webhook_update(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    enabled: bool | None = None
    if args.enable and args.disable:
        _err("--enable and --disable are mutually exclusive"); return 1
    if args.enable:
        enabled = True
    elif args.disable:
        enabled = False
    async with cli:
        return await cli.patch_webhook(args.wid, url=args.url, secret=args.secret,
                                        events=args.event, enabled=enabled)


def cmd_webhook_update(args: argparse.Namespace) -> int:
    try:
        rec = asyncio.run(_webhook_update(args))
    except TrsError as e:
        _err(str(e)); return 2
    _print_json(rec); return 0


async def _webhook_delete(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.delete_webhook(args.wid)


def cmd_webhook_delete(args: argparse.Namespace) -> int:
    try:
        asyncio.run(_webhook_delete(args))
    except TrsError as e:
        _err(str(e)); return 2
    print(f"webhook {args.wid} deleted"); return 0


async def _webhook_logs(args: argparse.Namespace) -> Any:
    cli, _ = _resolve(args)
    async with cli:
        return await cli.webhook_deliveries(args.wid)


def cmd_webhook_logs(args: argparse.Namespace) -> int:
    try:
        items = asyncio.run(_webhook_logs(args))
    except TrsError as e:
        _err(str(e)); return 2
    if args.json:
        _print_json(items); return 0
    _print_table(items, [("ID", "id"), ("EVENT", "event"), ("STATUS", "status_code"),
                          ("WHEN", "ts_h"), ("ERROR", "error")])
    return 0


# ─── entry point ──────────────────────────────────────────────────
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fn = getattr(args, "fn", None)
    if fn is None:
        parser.print_help(); return 0
    try:
        return int(fn(args) or 0)
    except TrsError as e:
        _err(str(e))
        return 2
    except KeyboardInterrupt:
        _err("interrupted")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
