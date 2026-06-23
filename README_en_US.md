<div align="center">

# 🚪 The Room System

### One password. One room. Everything beamed in seconds.

**The snappiest way to send files across your local network.**  
No accounts · No cloud · No size limits · Just a password and a browser.

🌐 Other languages: [简体中文](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/snake-aabb-wtf/the-room-system/actions/workflows/ci.yml/badge.svg)](https://github.com/snake-aabb-wtf/the-room-system/actions/workflows/ci.yml)

---

</div>

> 💡 A lightweight, private, zero-config LAN file-sharing system.

---

## 💥 Why you need it today

> "USB drive missing? WeChat won't send that big video? AirDrop ignores your PC? — Open a browser, drop it in, done."

**The Room System** turns your computer into a **shared vault on your local network**:
set a password for your files, and anyone (phone, tablet, a coworker's laptop) opens the page, types the password, and can upload or download — **no cloud involved, no sign-up, no size cap**.

It's not a tool. It's the **always-on, grab-and-go file portal** on your desk.

<div align="center">

```
        📱 Phone             💻 Your PC              💼 Coworker
            \                   |                   /
             \                  |                  /
              >>>>  🔑 One password · One room  🔑  <<<<
                          🚪 The Room 🚪
```

</div>

---

## ⚡ Get it in 3 seconds

| What you want | The old way | The Room System |
|---------------|-------------|-----------------|
| Send a 2GB video to a coworker | WeChat? ❌ 100MB cap. Cloud? ⏳ Upload then share. USB? 🔍 Lost it. | **Drop it in → give the password → they stream it instantly** ✅ |
| Browse PC photos on your phone | USB cable? 🔌 Send to self on chat? 🐌 | **Same Wi-Fi, open the page, see the gallery** ✅ |
| Hand out meeting materials | Group chat → send one by one → can't revoke | **One room link, everyone in sync, revoke anytime** ✅ |
| Show a friend one document | Email attachment size warning | **Password = room, seen then gone, no trace** ✅ |

---

## 🌟 Why it wins

- 🔑 **Zero friction** — No sign-up, no app, no server config. Open the page and use it. **Even your grandma can.**
- 🚀 **Blazing fast** — Direct LAN connection, gigabit saturated. A 2GB video? Dropped in and done.
- 🎬 **Preview as it lands** — No waiting to download; **seek through the video while it transfers**. Markdown / code / PDF / images all preview online.
- 🔒 **Private** — Files never leave your LAN, the password never enters the URL. **Your data stays on your own machine.**
- ♾️ **Unlimited** — No cloud size walls, no chat-app compression. **A 10GB file? 50GB? Send it anyway.**
- 📱 **Everywhere** — Phone, tablet, PC, Mac, Linux. **If it has a browser, it works.**
- 🆓 **Free forever & open source** — Not a cent, ever.

---

## 📑 Table of Contents

- [💥 Why you need it today](#-why-you-need-it-today)
- [⚡ Get it in 3 seconds](#-get-it-in-3-seconds)
- [🌟 Why it wins](#-why-it-wins)
- [🚀 30-second start](#-30-second-start)
- [📖 How to use](#-how-to-use)
- [✨ Full feature list](#-full-feature-list)
- [⚙️ Configuration](#️-configuration)
- [🛠️ Admin dashboard](#️-admin-dashboard)
- [🔒 Security](#-security)
- [📂 Project structure](#-project-structure)
- [❓ FAQ](#-faq)
- [🎯 Try it now](#-try-it-now)

---

## 🚀 30-second start

Requires Python 3.10+ (3.12 recommended).

```bash
python -m pip install -r requirements.txt   # once
python run.py
```

On launch the console prints your access URL and admin password:

```
======================================================
  →  http://192.168.1.4:3005
  Admin dashboard: http://192.168.1.4:3005/admin
  Admin password: MLY42YopH48
======================================================
```

Open that URL from **any device on the same network** and you're in.

---

## 📖 How to use

**Send files to someone:**
1. Open the URL, type a password (or click "random room"), enter the room
2. **Drag a file into the page**
3. Tell the other person the **password** — done

**To receive:**
1. Open the same URL
2. Type the password
3. Click a file to preview online, or download it

**Power moves:**
- 📟 **QR codes** — Generate one, scan with a phone to jump straight in
- 🔗 **Share links** — Forwardable and **revocable**
- ⏰ **Expiring files** — Set a lifetime; they vanish when it's up
- 💬 **Real-time chat** — Everyone in the room sees messages instantly
- ⌨️ **Command line** — Geek-friendly, see below

### Send files from the CLI (curl)

```bash
# Upload
curl -T bigvideo.mp4 http://YOUR_IP:3005/upload/ROOM_HASH/raw -H "X-Filename: bigvideo.mp4"

# Download
curl -OJ http://YOUR_IP:3005/raw/ROOM_HASH/filename
```

The room hash is the first 16 chars of sha256(password). You rarely need it — the browser is easier.

---

## 🆕 v3.0.0 — API coverage (v3.0.0-rc.1 first release)

**v3 major version. Theme: make curl / scripts / third-party integration 100% usable.**

### 1. API Token authentication
- Dual header support: `Authorization: Bearer xxx` **or** `X-API-Key: xxx`
- Token scopes: `admin` / `user` / `readonly`, comma-separated multi-value
- Tokens can be bound to a specific room
- Tokens have expiration, can be revoked, multiple can coexist
- First-run auto-generates an admin token (printed to console + stored in `data/rooms.db`)
- Cold-start supports `X-Bootstrap-Password` header to mint the first token (when no tokens exist yet)

### 2. RFC 7807 Problem Details error format
- All `/api/v3/*` endpoints return `application/problem+json`
- Fields: `type` / `title` / `status` / `detail` / `instance` / `trace_id` / `timestamp`
- Programmatically parseable; every response carries `trace_id` for debugging

### 3. Deprecation header on old paths
- Old paths (`/upload/`, `/delete/`, `/api/{rh}/`, etc.) now respond with:
  - `Deprecation: true`
  - `Sunset: 2026-12-31`
  - `Link: <...api/v3>; rel="successor-version"`
- v3.1 will remove old paths; 6-month migration window

### 4. First v3 endpoints (`/api/v3/auth/tokens` + rc.2 extensions)
- `GET  /api/v3/auth/tokens` — list all tokens (admin scope)
- `POST /api/v3/auth/tokens` — create new token (**plaintext returned only once**)
- `GET  /api/v3/auth/tokens/{id}` — single token details
- `PATCH /api/v3/auth/tokens/{id}` — update name / expires_at
- `DELETE /api/v3/auth/tokens/{id}` — revoke

### 4b. rc.2: file CRUD + batch + query + audit

**Files**:
- `GET    /api/v3/rooms/{rh}/files` — paged + filtered (`q` / `parent_dir` / `ext` / `sort` / `page` / `per_page` / `include_deleted`)
- `GET    /api/v3/rooms/{rh}/files/{id}` — single file metadata
- `PATCH  /api/v3/rooms/{rh}/files/{id}` — modify `name` / `parent_dir` / `expires_at` (rejected for `readonly` tokens)
- `DELETE /api/v3/rooms/{rh}/files/{id}` — soft-delete
- `POST   /api/v3/rooms/{rh}/files/batch-delete`  body=`{ids:[...]}` — batch soft-delete
- `POST   /api/v3/rooms/{rh}/files/batch-restore` — batch restore from recycle
- `POST   /api/v3/rooms/{rh}/files/batch-purge` — batch permanent-delete

**Recycle**:
- `GET  /api/v3/rooms/{rh}/recycle` — recycle paged
- `POST /api/v3/rooms/{rh}/recycle/empty` — **empty the entire recycle bin**

**Admin**:
- `GET /api/v3/admin/stats` — global stats
- `GET /api/v3/admin/rooms` — rooms list paged + searchable
- `GET /api/v3/admin/rooms/{rh}` — single room details
- `GET /api/v3/admin/audit` — audit paged + filtered (`action` / `room_hash` / `ip` / `since` / `before`)
- `POST /api/v3/admin/cleanup` — trigger cleanup

> 💡 **Upcoming**: rc3 adds presigned URLs (HMAC-signed short-lived download links); rc4 adds WebHooks (event subscription + HMAC delivery).

### 5. Quick try
```bash
# 1. Grab the auto-generated admin token (find it in startup console logs)
TOKEN="xxx..."

# 2. List tokens
curl -H "Authorization: Bearer $TOKEN" http://YOUR_IP:3005/api/v3/auth/tokens

# 3. Create a new token
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-deploy","scope":"user"}' \
  http://YOUR_IP:3005/api/v3/auth/tokens
```

---

## ✨ Full feature list

<details>
<summary><b>📁 Experience (click to expand)</b></summary>

- Drag-and-drop upload / multiple files / folders
- Per-file **live progress bar**
- Instant search + 4 sort modes
- Rename / soft delete
- Grid / list dual view
- Auto-detects every LAN IP (**survives Wi-Fi / Ethernet switching**)
- One-click copy address + QR codes
- 🆕 **Toast notifications** (replace native alert)
- 🆕 **Modal confirm/prompt** (replace native confirm/prompt)
- 🆕 **Global 401 intercept + friendly redirect** (expired session auto-returns to login)
- 🆕 **Full A11Y**: ARIA roles / aria-live / keyboard reachable / focus-visible
- 🆕 **ESC closes every overlay**
- 🆕 **Chat: own vs other messages** + system messages
- 🆕 **Smart scroll + unread message button**
- 🆕 **Upload concurrency limit (3 max)** + cancellable
- 🆕 **Retry on failure** (↻ button, no new row)
- 🆕 **ETA estimate** ("2 min 30 sec left")
- 🆕 **FIFO upload order** (doesn't steal focus)
- 🆕 **Drop overlay flicker fix**
- 🆕 **Image thumbnails** (Pillow auto-generates 256px JPEG)
- 🆕 **Folder upload** (preserves directory structure + tree view)
- 🆕 **Multi-select bulk download** (zipstream-ng streaming zip)

</details>

<details>
<summary><b>👀 Preview (click to expand)</b></summary>

- **Streaming video playback + seek** (HTTP Range)
- Image lightbox browsing
- **Markdown rendered online** (code blocks, lists, quotes, images)
- Text / code online viewer
- PDF embedded preview
- Audio player

</details>

<details>
<summary><b>🛠️ Management (click to expand)</b></summary>

- Admin **dashboard** (stats / rooms / audit)
- File TTL **auto-cleanup on expiry** (scans every 5 minutes)
- Traffic / download-count statistics
- Full audit log persisted
- One-click room purge
- 🆕 **Recycle bin**: soft-delete with 30-day retention, restore or permanently delete
- 🆕 **Optional deps**: Pillow (thumbnails) / zipstream-ng (bulk download) / ffmpeg (video thumbnails, optional)

</details>

<details>
<summary><b>💬 Collaboration (click to expand)</b></summary>

- **Real-time room chat** (WebSocket push, instant delivery)
- File expiry times
- Share links (password login → generate link → revocable)
- In-room nickname identity

</details>

---

## ⚙️ Configuration

Everything lives in `config.toml` — delete it and defaults still work.

```toml
[server]
host = "0.0.0.0"
port = 3005

[storage]
# Per-file cap in bytes, 0 = unlimited
max_file_size = 53687091200

[rooms.preset]
# Preset rooms: name → password. The password is the key you tell the other side.
# Any non-preset password also instantly creates a temporary room.
agnes = "agnes2024"

[admin]
# Leave empty / "admin" and a random password is auto-generated on first run,
# printed to the console, and written back here. Or set your own.
password = ""
```

Restart `python run.py` after editing.

---

## 🛠️ Admin dashboard

Open `http://YOUR_IP:3005/admin` and enter the admin password (printed on first launch; editable in `config.toml [admin]`).

Features:
- 📊 **Overview** — rooms / files / total size / downloads / messages
- 🏠 **Rooms** — per-room file count, size, last active; purge with one click
- 📋 **Audit log** — timeline of every login / upload / download / delete
- 🧹 **Cleanup** — manually purge expired files (also auto-runs every 5 minutes)

---

## 🔒 Security

Built for **LAN / trusted-circle** use. Hardened by default:

| Threat | Protection |
|--------|-----------|
| Path traversal (`../../etc/passwd`) | `ensure_within()` rejects any escape — returns 404 |
| Password in the URL | Login sets a cookie session; URLs contain only a one-way hash |
| "Any password opens any room" | Strict preset match or explicit room creation |
| Memory blow-up on big files | Streaming 1MB chunks, never loads the whole file |
| XSS via Markdown / messages | All user content escaped before rendering |
| Unauthorized admin / WebSocket access | 403 / 4403 across the board |

**Not designed** for direct public exposure. For remote access, use a VPN or SSH tunnel, or put a reverse proxy with HTTPS in front.

---

## 📂 Project structure

```
The Room system/
├── run.py                  # 🚀 Entry point
├── requirements.txt
├── config.toml             # ⚙️ Config
├── roomsystem/             # Backend
│   ├── app.py              #   FastAPI app factory
│   ├── config.py           #   Config loader
│   ├── store.py            #   SQLite persistence layer
│   ├── auth.py             #   Authentication
│   ├── security.py         #   Path sanitizing + escape detection
│   ├── streaming.py        #   Streaming upload/download + Range
│   ├── net.py              #   LAN IP discovery
│   ├── realtime.py         #   WebSocket broadcast
│   ├── cleanup.py          #   Expiry cleanup task
│   └── routes.py           #   All routes
├── templates/              # Pages
│   ├── login.html · room.html · admin.html · share.html
├── static/style.css
└── data/                   # Auto-generated, don't edit by hand
    ├── rooms.db
    └── files/
```

---

## ❓ FAQ

**Q: The port is already in use?**  
`run.py` auto-detects the conflict and tells you the PID to kill, or change `port` in `config.toml`.

**Q: My phone can't connect?**  
Make sure phone and PC are on the **same Wi-Fi**, and use the `192.168.x.x:3005` address (not localhost). Allow port 3005 through your firewall.

**Q: The IP changed after switching Wi-Fi / plugging in Ethernet?**  
No problem — it re-detects all IPs on every launch, and the room page shows every working address.

**Q: Does data survive a restart?**  
Yes — rooms and files live in SQLite + disk and survive restarts. Only **browser sessions** reset (re-enter the password).

**Q: How do I fully reset?**  
Delete the `data/` directory and restart (clears all files and room metadata).

---

<div align="center">

## 🎯 Try it now

```bash
git clone https://github.com/snake-aabb-wtf/the-room-system.git
cd the-room-system
python -m pip install -r requirements.txt
python run.py
```

**Then open your browser and drop in a file. It's that simple.**

---

⭐ Like it? Drop a Star so others find it too.

*For everyone who just wants their files to **get there**, fast.*

</div>
