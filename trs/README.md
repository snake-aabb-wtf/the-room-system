# `trs` — Official CLI & Python SDK for The Room System

`trs` packages every `v3` API endpoint of [The Room System](../) into a
handful of ergonomic commands and a small async Python SDK.

## Features

- 🔐 **API token auth** (Bearer or `X-API-Key`) with optional `room_session`
  cookie for legacy v2 endpoints
- ⚡ **Async SDK** built on `httpx` — `from trs import TrsClient`
- 🧰 **Single binary CLI** with subcommands for every API surface:
  - `trs auth …` — list, create, rename, expire, revoke API tokens
  - `trs rooms …` — admin stats, rooms, audit, cleanup
  - `trs files …` — list, upload, download, rename, delete, batch, recycle
  - `trs msg …` — list / post chat messages
  - `trs share …` — create / list / revoke share links
  - `trs webhook …` — full CRUD + delivery log
  - `trs config …` — manage `~/.config/theroom/config.toml` profiles
- 🗂 **Multi-profile config** (`--profile staging`); env-var overrides;
  auto `chmod 600` on POSIX

## Install

```bash
# from the repo root
pip install -e trs/
```

## 5-second tour

```bash
# 1) Cold start: bootstrap the first admin token
trs auth bootstrap --password "$ROOM_ADMIN_PW" \
                   --base-url http://192.168.1.10:3005

# 2) List all tokens
trs auth list

# 3) Upload a file
trs files upload "$(trs rooms list --json | jq -r '.items[0].room_hash')" ./dist.zip

# 4) Stream every PDF in a room
trs files list myroom --ext pdf --sort size --json | jq '.items[].name'
```

## Python SDK

```python
import asyncio
from trs import TrsClient

async def main():
    async with TrsClient("http://192.168.1.10:3005", token="trs_xxx") as cli:
        # List every file (paged)
        async for f in cli.iter_files("myroom", ext="pdf"):
            print(f["id"], f["name"], f["size_h"])

        # Presigned download
        await cli.download_presigned("myroom", 42, dest="./big.bin")

asyncio.run(main())
```

## Configuration

`~/.config/theroom/config.toml` (Windows: `%APPDATA%\theroom\config.toml`):

```toml
default = "default"

[profile.default]
base_url = "http://192.168.1.10:3005"
token = "trs_xxxxxxxx"
room_cookie = "room_session=xxxxx"   # optional
```

Override with env vars: `TRS_BASE_URL`, `TRS_TOKEN`, `TRS_API_KEY`,
`TRS_PROFILE`, `TRS_CONFIG`, `TRS_ROOM_COOKIE`.

## License

MIT — see [../LICENSE](../LICENSE).
