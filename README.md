<div align="center">

# 🚪 The Room System

### 一个口令，一个房间，万物秒传。

**The snappiest way to beam files across your local network.**  
No accounts. No cloud. No limits. Just a password and a browser.

---

</div>

> 🇨🇳 [中文](#-中文介绍) ｜ 🇺🇸 [English](#-english)

---

## 💥 为什么你今天就需要它

> "U 盘找不到了？微信传大视频失败？AirDrop 不认你的 PC？—— 打开浏览器，拖进去，完事。"

**The Room System** 把你的电脑变成一个**局域网内的共享保险箱**：
给文件设一个口令，任何人（手机、平板、同事的电脑）打开网页、输入口令，就能上传和下载，**全程不经过任何云、不需要登录注册、没有体积限制**。

它不是一个工具，它是你桌面上那个**永远在线、随用随走的文件传送门**。

<div align="center">

```
        📱 手机              💻 你的电脑              💼 同事
            \                   |                   /
             \                  |                  /
              >>>>  🔑 一句口令 · 一个房间  🔑  <<<<
                          🚪 The Room 🚪
```

</div>

---

## ⚡ 三秒看懂

| 你想做的事 | 传统办法 | The Room System |
|-----------|---------|-----------------|
| 传 2GB 的视频给同事 | 微信? ❌ 限 100MB。网盘? ⏳ 先上传再分享。U盘? 🔍 找不到了。 | **拖进去 → 给口令 → 对方秒开流式播放** ✅ |
| 手机看电脑里的相册 | 数据线? 🔌 微信传自己? 🐌 | **同一 WiFi，浏览器打开即看大图墙** ✅ |
| 给会议分发资料 | 建群 → 逐个发 → 撤回不了 | **一个房间链接，全员实时同步，随时撤回** ✅ |
| 临时给朋友看个文档 | 邮件附件大小警告 | **口令即房间，看完即散，不留痕迹** ✅ |

---

## 🌟 核心卖点

- 🔑 **零门槛** —— 不用注册、不用装 App、不用配服务器。打开网页就能用，**连你奶奶都会**。
- 🚀 **极速** —— 局域网直连，千兆带宽跑满。2GB 视频？拖进去就传完了。
- 🎬 **即传即看** —— 视频不用等下载，**边传边拖进度条播放**。Markdown/代码/PDF/图片全部在线预览。
- 🔒 **私密** —— 文件不出局域网，口令不进 URL，**你的数据永远在你自己的机器上**。
- ♾️ **无限制** —— 没有云盘的体积墙，没有微信的压缩，**10GB 单文件？50GB？照传不误**。
- 📱 **全平台** —— 手机、平板、PC、Mac、Linux，**有浏览器就行**。
- 🆓 **永久免费 & 开源** —— 一行代码不收费，一辈子不收费。

---

## 🇨🇳 中文介绍

### 🚀 30 秒启动

需要 Python 3.10+（推荐 3.12）。

```bash
python -m pip install -r requirements.txt   # 只需一次
python run.py
```

启动后控制台会告诉你地址、和管理员口令：

```
======================================================
  →  http://192.168.1.4:3005
  管理后台: http://192.168.1.4:3005/admin
  管理员口令: MLY42YopH48
======================================================
```

任何同局域网的设备，浏览器打开这个地址就能用。

### 📖 怎么用

**传文件给别人：**
1. 打开网址，输入一个口令（或点「随机创建房间」），进入房间
2. 把文件**拖进网页**
3. 把**口令**告诉对方 —— 完事

**对方接收：**
1. 打开同一个网址
2. 输入口令
3. 点文件在线预览，或下载

**进阶玩法：**
- 📟 **二维码** —— 一键生成，手机扫码直入房间
- 🔗 **分享链接** —— 生成可转发、**可吊销**的链接
- ⏰ **到期文件** —— 传完设个有效期，到期自动消失
- 💬 **实时留言** —— 房间内所有人消息秒到
- ⌨️ **命令行** —— `curl -T 文件 http://IP:3000/upload/房间/raw` 极客友好

### ✨ 完整功能

<details>
<summary><b>📁 体验类（点击展开）</b></summary>

- 拖拽上传 / 多文件 / 文件夹
- 逐文件**实时进度条**
- 即时搜索 + 4 种排序
- 重命名 / 软删除
- 网格 / 列表双视图
- 自动探测所有局域网 IP（**WiFi/网线切换不失联**）
- 一键复制地址 + 二维码

</details>

<details>
<summary><b>👀 预览类（点击展开）</b></summary>

- **视频流式播放 + 拖进度**（HTTP Range）
- 图片大图浏览（lightbox）
- **Markdown 在线渲染**（代码块、列表、引用、图片）
- 文本 / 代码在线查看
- PDF 内嵌预览
- 音频播放器

</details>

<details>
<summary><b>🛠️ 管理类（点击展开）</b></summary>

- 管理员后台**仪表盘**（统计 / 房间 / 审计）
- 文件 TTL **到期自动清理**（后台每 5 分钟扫描）
- 流量 / 下载次数统计
- 完整审计日志持久化
- 房间一键清空

</details>

<details>
<summary><b>💬 协作类（点击展开）</b></summary>

- 房间内**实时留言**（WebSocket 推送，消息秒到）
- 文件到期时间
- 分享链接（口令登录 → 生成链接 → 可吊销）
- 房间内昵称身份

</details>

---

## 🇺🇸 English

### 🚀 30-second start

Requires Python 3.10+ (3.12 recommended).

```bash
python -m pip install -r requirements.txt   # once
python run.py
```

The console prints your LAN address and an auto-generated admin password. Open that URL from **any device on the same Wi-Fi**. Done.

### How it works

1. Open the URL → type any password (or click "random room")
2. **Drag a file in** → it uploads in a flash
3. Tell the other person the password → they open the same URL and grab it

**Advanced:**
- 📟 QR codes for instant mobile access
- 🔗 Revocable share links with optional TTL
- ⏰ Self-destructing files (set expiry, auto-cleanup)
- 💬 Real-time room chat (WebSocket)
- ⌨️ `curl -T file http://IP:3000/upload/<room>/raw` — CLI friendly

### Why not the alternatives?

| Need | Cloud drive | WeChat / AirDrop | **The Room System** |
|------|-------------|------------------|---------------------|
| 2GB video to a coworker | Slow upload | Blocked / size cap | **Instant, no limit** ✅ |
| Privacy | Hits a server | Hits a server | **Stays on your LAN** ✅ |
| Preview before download | Sometimes | No | **Stream + seek instantly** ✅ |
| Cost | Subscription | Free but capped | **Free forever, no caps** ✅ |

---

## ⚙️ 配置 / Configuration

Everything lives in `config.toml` — delete it and defaults still work.

```toml
[server]
host = "0.0.0.0"
port = 3005

[storage]
max_file_size = 53687091200   # 单文件上限（字节）/ per-file cap in bytes, 0=unlimited

[rooms.preset]                # 预置房间：名字 → 口令 / preset rooms: name → password
agnes = "agnes2024"

[admin]
password = "your-admin-password"
```

Edit, then `python run.py` again.

---

## 🛠️ 管理后台 / Admin Dashboard

`http://你的IP:3000/admin` → enter the admin password (printed on first launch, stored in `config.toml [admin]`).

- 📊 **Stats** — rooms / files / total size / downloads / messages
- 🏠 **Rooms** — per-room file count, size, last active; nuke with one click
- 📋 **Audit log** — every login / upload / download / delete, time-stamped
- 🧹 **Cleanup** — manually purge expired files (auto-runs every 5 min anyway)

---

## 🔒 安全 / Security

Built for **LAN / trusted-circle** use. Hardened by default:

| Threat | Protection |
|--------|-----------|
| Path traversal (`../../etc/passwd`) | `ensure_within()` rejects any escape — returns 404 |
| Password in URL | Login sets a cookie session; URLs contain only a one-way hash |
| "Any password opens any room" | Strict preset match or explicit room creation |
| Memory blow-up on big files | Streaming 1MB chunks, never loads whole file |
| XSS via Markdown / messages | All user content escaped before rendering |
| Unauthorized admin / WebSocket access | 403 / 4403 across the board |

**Not designed for direct public exposure.** For remote access, use a VPN or SSH tunnel, or put a reverse proxy with HTTPS in front.

---

## 📂 项目结构 / Project Structure

```
The Room system/
├── run.py                  # 🚀 启动入口 / entry point
├── requirements.txt
├── config.toml             # ⚙️ 配置 / config
├── roomsystem/             # 后端 / backend
│   ├── app.py              #   FastAPI 应用工厂 / app factory
│   ├── config.py           #   配置加载 / config loader
│   ├── store.py            #   SQLite 持久层 / persistence
│   ├── auth.py             #   认证 / authentication
│   ├── security.py         #   路径清洗 + 逃逸检测 / path safety
│   ├── streaming.py        #   流式上传下载 + Range / streaming + range
│   ├── net.py              #   局域网 IP 探测 / LAN IP discovery
│   ├── realtime.py         #   WebSocket 广播 / WS broadcast
│   ├── cleanup.py          #   过期清理任务 / expiry cleanup
│   └── routes.py           #   所有路由 / all routes
├── templates/              # 页面 / pages
│   ├── login.html · room.html · admin.html · share.html
├── static/style.css
└── data/                   # 自动生成 / auto-generated
    ├── rooms.db
    └── files/
```

---

## ❓ 常见问题 / FAQ

**Q: 端口被占 / Port in use?**  
`run.py` auto-detects the conflict and tells you the PID to kill, or change `port` in `config.toml`.

**Q: 手机连不上 / Phone can't connect?**  
Same Wi-Fi, use the `192.168.x.x:3005` address (not localhost), allow port 3005 through your firewall.

**Q: 换了 WiFi 地址变了 / IP changed after switching networks?**  
No problem — it re-detects all IPs on every launch and shows every working address in the UI.

**Q: 重启后数据还在吗 / Does data survive restart?**  
Yes — rooms and files live in SQLite + disk. Only browser sessions reset (re-enter the password).

**Q: 怎么彻底重置 / How to fully reset?**  
Delete the `data/` directory and restart.

---

<div align="center">

## 🎯 现在就用 / Try it now

```bash
git clone https://github.com/snake-aabb-wtf/the-room-system.git
cd the-room-system
python -m pip install -r requirements.txt
python run.py
```

**然后打开浏览器，拖个文件进去。就这么简单。**
**Then open your browser and drop in a file. It's that simple.**

---

⭐ 觉得好用？给个 Star 让更多人看到。
**Like it? Drop a ⭐ so others find it too.**

*Made for people who just want their files to **get there**, fast.*
</div>
