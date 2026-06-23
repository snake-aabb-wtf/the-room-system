# Changelog

All notable changes to **The Room System** are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [3.0.0] - 2026-06-23  —  Final

`v3.0.0 final` ships the official **`trs`** Python package: a single-binary
command-line tool plus an async Python SDK that wraps every v3 endpoint.

### Added

- 🐍 **`trs` Python package** (under `trs/`):
  - Async SDK `from trs import TrsClient` covering auth tokens, files
    (list/show/rename/delete/restore/purge/batch/recycle/presign/upload/download),
    admin stats / rooms / audit / cleanup, webhooks (full CRUD + delivery log),
    share links, chat messages.
  - Single-file `argparse` CLI with subcommands `auth / rooms / files /
    msg / share / webhook / config`. Every command supports `--json` for
    raw output and exits non-zero on error.
  - `trs auth bootstrap` — first-time admin token creation via
    `X-Bootstrap-Password`, with auto-save into the active profile.
  - Multi-profile config at `~/.config/theroom/config.toml` (POSIX
    `chmod 600`), env-var overrides (`TRS_BASE_URL` / `TRS_TOKEN` /
    `TRS_API_KEY` / `TRS_PROFILE` / `TRS_CONFIG` / `TRS_ROOM_COOKIE`).
  - `tests/test_cli.py` — 39-assertion subprocess + in-process integration
    test covering the full CLI workflow and every SDK method shape.
- 🆕 `download_presigned()` helper in the SDK that streams a file via the
  no-auth `/dl_presign/...` endpoint.
- 🆕 `iter_files()` async generator that transparently pages through a
  room's file list.

### Tests

- `tests/test_smoke.py` — 116/116 still green (no regression).
- `tests/test_cli.py` — 39/39 green (new).
- Total: **155/155**.

### Compatibility

- Python 3.10+ (3.11+ uses stdlib `tomllib`; 3.10 falls back to `tomli`).
- No breaking changes to the HTTP API surface vs `3.0.0-rc.4`.

---

## [3.0.0-rc.4] - 2026-06-22  —  WebHook 事件订阅

- `GET/POST/PATCH/DELETE /api/v3/admin/webhooks` for full subscription CRUD.
- `GET /api/v3/admin/webhooks/{id}/deliveries` for the last 50 deliveries.
- HMAC-SHA256 signature header `X-Room-Signature-256: t=…,v1=…`; auto-disable
  after 5 consecutive failures.
- Events: `file.uploaded` / `file.deleted` / `file.restored` / `file.purged`.

## [3.0.0-rc.3] - 2026-06-21  —  预签名 URL (HMAC)

- `GET /api/v3/rooms/{rh}/presign?file_id=…&op=get&ttl=300` returns a
  short-lived signed URL; no auth header needed to download.
- `GET /api/v3/dl_presign/{rh}/{fid}?sig=…&exp=…&op=get` — free download
  (HMAC verified; `410 Gone` on expiry; `403` on tampering).

## [3.0.0-rc.2] - 2026-06-20  —  文件 CRUD + 批量 + 查询增强 + 审计

- `GET/PATCH/DELETE /api/v3/rooms/{rh}/files/{fid}` for direct file ops.
- `POST /api/v3/rooms/{rh}/files/batch-{delete,restore,purge}`.
- `GET /api/v3/rooms/{rh}/recycle` + `POST .../recycle/empty`.
- Query / pagination / sort on `GET /api/v3/rooms/{rh}/files`.
- `GET /api/v3/admin/{stats,rooms,rooms/{rh},audit,cleanup}` admin
  endpoints with paging + action/room/ip filters on audit.

## [3.0.0-rc.1] - 2026-06-19  —  API Token + RFC 7807 + Deprecation header

- Token store + scopes (`admin` / `user` / `readonly`) + bootstrap path.
- `Authorization: Bearer …` and `X-API-Key` auth headers.
- All v3 errors returned as RFC 7807 `application/problem+json`.
- `Deprecation: true` / `Sunset: 2026-12-31` on every v2 path.

## Earlier

See [git log](https://github.com/snake-aabb-wtf/the-room-system/commits/main)
for v2.x history (file sharing, messages, share links, WebSocket realtime,
recursion-safe cleanup, recycle bin, thumbnails, batch zip, A11y, …).
