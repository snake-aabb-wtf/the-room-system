<div align="center">

# 🚪 The Room System

### 一个口令，一个房间，万物秒传。

**局域网内最快的文件传送门。**  
无需账号 · 不上云 · 没有体积限制 · 一个口令加一个浏览器就够了。

🌐 其他语言：[English](README_en_US.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/snake-aabb-wtf/the-room-system/actions/workflows/ci.yml/badge.svg)](https://github.com/snake-aabb-wtf/the-room-system/actions/workflows/ci.yml)

---

</div>

> 💡 这是一个轻量、私密、即开即用的局域网文件共享系统。

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
- 🎬 **即传即看** —— 视频不用等下载，**边传边拖进度条播放**。Markdown / 代码 / PDF / 图片全部在线预览。
- 🔒 **私密** —— 文件不出局域网，口令不进 URL，**你的数据永远在你自己的机器上**。
- ♾️ **无限制** —— 没有云盘的体积墙，没有微信的压缩，**10GB 单文件？50GB？照传不误**。
- 📱 **全平台** —— 手机、平板、PC、Mac、Linux，**有浏览器就行**。
- 🆓 **永久免费 & 开源** —— 一行代码不收费，一辈子不收费。

---

## 📑 目录

- [💥 为什么你今天就需要它](#-为什么你今天就需要它)
- [⚡ 三秒看懂](#-三秒看懂)
- [🌟 核心卖点](#-核心卖点)
- [🚀 30 秒启动](#-30-秒启动)
- [📖 怎么用](#-怎么用)
- [✨ 完整功能](#-完整功能)
- [⚙️ 配置](#️-配置)
- [🛠️ 管理后台](#️-管理后台)
- [🔒 安全说明](#-安全说明)
- [📂 项目结构](#-项目结构)
- [❓ 常见问题](#-常见问题)
- [🎯 现在就用](#-现在就用)

---

## 🚀 30 秒启动

需要 Python 3.10+（推荐 3.12）。

```bash
python -m pip install -r requirements.txt   # 只需一次
python run.py
```

启动后控制台会告诉你访问地址和管理员口令：

```
======================================================
  →  http://192.168.1.4:3005
  管理后台: http://192.168.1.4:3005/admin
  管理员口令: MLY42YopH48
======================================================
```

任何同局域网的设备，浏览器打开这个地址就能用。

---

## 📖 怎么用

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
- ⌨️ **命令行** —— 极客友好，见下方

### 命令行传文件（curl）

```bash
# 上传
curl -T 大视频.mp4 http://你的IP:3005/upload/房间hash/raw -H "X-Filename: 大视频.mp4"

# 下载
curl -OJ http://你的IP:3005/raw/房间hash/文件名
```

房间 hash 是 sha256(口令) 的前 16 位。一般不用记，浏览器里直接操作更方便。

---

## 🆕 v3.0.0 — API 全覆盖（首批 v3.0.0-rc.1）

**v3 大版本，主题：让 curl / 脚本 / 第三方集成 100% 能用。**

### 1. API Token 鉴权
- 双 header 支持：`Authorization: Bearer xxx` **或** `X-API-Key: xxx`
- Token 范围：`admin` / `user` / `readonly`，可多选逗号分隔
- Token 可绑房间（限定访问范围）
- Token 有期限、可吊销、可多个同时有效
- 首启自动生成 admin token（控制台打印 + `data/rooms.db` 存）
- 冷启动支持 `X-Bootstrap-Password` header 创建第一个 token（无现有 token 时）

### 2. RFC 7807 Problem Details 错误格式
- 所有 `/api/v3/*` 端点统一返回 `application/problem+json`
- 字段：`type` / `title` / `status` / `detail` / `instance` / `trace_id` / `timestamp`
- 客户端可编程解析；服务端每次响应附 `trace_id` 方便排查

### 3. 旧路径加 Deprecation header
- 旧路径（`/upload/`、`/delete/`、`/api/{rh}/` 等）响应加：
  - `Deprecation: true`
  - `Sunset: 2026-12-31`
  - `Link: <...api/v3>; rel="successor-version"`
- v3.1 之后移除旧路径；6 个月过渡期

### 4. v3 端点首批（`/api/v3/auth/tokens` + rc.2 补全）
- `GET  /api/v3/auth/tokens` —— 列出所有 token（admin scope）
- `POST /api/v3/auth/tokens` —— 创建新 token（**仅此一次返回明文 token**）
- `GET  /api/v3/auth/tokens/{id}` —— 单个 token 详情
- `PATCH /api/v3/auth/tokens/{id}` —— 改 name/expires_at
- `DELETE /api/v3/auth/tokens/{id}` —— 吊销

### 4b. rc.2 增补：文件 CRUD + 批量 + 查询增强 + 审计

**文件**：
- `GET    /api/v3/rooms/{rh}/files` —— 分页 + 过滤（`q`/`parent_dir`/`ext`/`sort`/`page`/`per_page`/`include_deleted`）
- `GET    /api/v3/rooms/{rh}/files/{id}` —— 单文件元数据
- `PATCH  /api/v3/rooms/{rh}/files/{id}` —— 改 `name` / `parent_dir` / `expires_at`（`readonly` token 拒）
- `DELETE /api/v3/rooms/{rh}/files/{id}` —— 软删除（返回 `recycle`）
- `POST   /api/v3/rooms/{rh}/files/batch-delete`  body=`{ids:[...]}` —— 批量软删
- `POST   /api/v3/rooms/{rh}/files/batch-restore` —— 批量恢复
- `POST   /api/v3/rooms/{rh}/files/batch-purge` —— 批量永久删

**回收站**：
- `GET  /api/v3/rooms/{rh}/recycle` —— 回收站分页
- `POST /api/v3/rooms/{rh}/recycle/empty` —— **清空回收站**

**管理员**：
- `GET /api/v3/admin/stats` —— 全局统计
- `GET /api/v3/admin/rooms` —— 房间列表分页 + 搜索
- `GET /api/v3/admin/rooms/{rh}` —— 单房间详情
- `GET /api/v3/admin/audit` —— 审计分页 + 过滤（`action`/`room_hash`/`ip`/`since`/`before`）
- `POST /api/v3/admin/cleanup` —— 触发清理

> 💡 **后续**：rc3 加预签名 URL（HMAC 签名短时下载链接）；rc4 加 WebHook（事件订阅 + HMAC 投递）。

### 5. 快速试用

### 5. 快速试用
```bash
# 1. 拿首启生成的 admin token（控制台日志里找）
TOKEN="xxx..."

# 2. 列 token
curl -H "Authorization: Bearer $TOKEN" http://你的IP:3005/api/v3/auth/tokens

# 3. 建一个新 token
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-deploy","scope":"user"}' \
  http://你的IP:3005/api/v3/auth/tokens
```

---

## ✨ 完整功能

<details>
<summary><b>📁 体验类（点击展开）</b></summary>

- 拖拽上传 / 多文件 / 文件夹
- 逐文件**实时进度条**
- 即时搜索 + 4 种排序
- 重命名 / 软删除
- 网格 / 列表双视图
- 自动探测所有局域网 IP（**WiFi / 网线切换不失联**）
- 一键复制地址 + 二维码
- 🆕 **Toast 非阻塞通知**（替代原生 alert）
- 🆕 **模态确认/输入框**（替代原生 confirm/prompt）
- 🆕 **全局 401 拦截 + 友好跳转**（会话过期自动回首页）
- 🆕 **完整 A11Y**：ARIA role / aria-live / 键盘可达 / focus-visible
- 🆕 **ESC 关闭所有弹层**
- 🆕 **消息自己/别人区分** + 系统消息
- 🆕 **智能滚动 + 未读消息按钮**
- 🆕 **上传并发限流（最多 3 个）** + 可取消
- 🆕 **失败可重试**（↻ 按钮，不弹新行）
- 🆕 **预估剩余时间**（"剩余 2 分 30 秒"）
- 🆕 **FIFO 上传顺序**（不抢占视线）
- 🆕 **拖入闪烁修复**
- 🆕 **图片缩略图**（Pillow 自动生成 256px JPEG）
- 🆕 **文件夹上传**（保留目录结构 + 树状视图）
- 🆕 **多选打包下载**（zipstream-ng 流式 zip）

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
- 🆕 **回收站**：软删除 30 天保留，可恢复 / 永久删除
- 🆕 **可选依赖**：Pillow（缩略图）/ zipstream-ng（打包下载）/ ffmpeg（视频缩略图，可选）

</details>

<details>
<summary><b>💬 协作类（点击展开）</b></summary>

- 房间内**实时留言**（WebSocket 推送，消息秒到）
- 文件到期时间
- 分享链接（口令登录 → 生成链接 → 可吊销）
- 房间内昵称身份

</details>

---

## ⚙️ 配置

所有配置都在 `config.toml`，删掉也能用默认值跑。

```toml
[server]
host = "0.0.0.0"
port = 3005

[storage]
# 单文件上限（字节），0 = 不限制
max_file_size = 53687091200

[rooms.preset]
# 预置房间：名字 → 口令。口令是你口头告诉对方的钥匙。
# 任意非预置口令也会即时创建一个临时房间。
agnes = "agnes2024"

[admin]
# 留空或写成 "admin"，首次启动会自动生成随机口令并打印到控制台，
# 同时写回本文件。你也可以直接在这里填一个自己的。
password = ""
```

改完重启 `python run.py` 生效。

---

## 🛠️ 管理后台

打开 `http://你的IP:3005/admin`，输入管理员口令（首次启动控制台打印的那个，在 `config.toml [admin]` 里可改）。

功能：
- 📊 **统计概览** —— 房间数 / 文件数 / 总占用 / 下载数 / 留言数
- 🏠 **房间列表** —— 每房间的文件数、占用、最后活跃时间；可一键清空
- 📋 **审计日志** —— 所有登录、上传、下载、删除操作的时间线
- 🧹 **过期清理** —— 手动触发扫描（系统每 5 分钟也会自动清理到期文件）

---

## 🔒 安全说明

本系统面向**局域网 / 熟人**场景。已内置防护：

| 威胁 | 防护措施 |
|------|---------|
| 路径穿越（`../../etc/passwd`） | `ensure_within()` 校验，任何逃逸一律返回 404 |
| 口令出现在 URL | 登录后用 cookie session，URL 只含单向 hash |
| 「任意口令进任意房间」 | 严格匹配预置房间，或显式创建临时房间 |
| 大文件吃爆内存 | 流式分块读写（1MB），从不整文件载入内存 |
| Markdown / 留言里的 XSS | 所有用户内容渲染前转义 |
| 未授权访问管理后台 / WebSocket | 全程 403 / 4403 拒绝 |

**不建议**直接暴露到公网。如需远程访问，请走 VPN 或 SSH 隧道，或自行加反向代理 + HTTPS。

---

## 📂 项目结构

```
The Room system/
├── run.py                  # 🚀 启动入口
├── requirements.txt
├── config.toml             # ⚙️ 配置
├── roomsystem/             # 后端
│   ├── app.py              #   FastAPI 应用工厂
│   ├── config.py           #   配置加载
│   ├── store.py            #   SQLite 持久层
│   ├── auth.py             #   认证
│   ├── security.py         #   路径清洗 + 逃逸检测
│   ├── streaming.py        #   流式上传下载 + Range
│   ├── net.py              #   局域网 IP 探测
│   ├── realtime.py         #   WebSocket 广播
│   ├── cleanup.py          #   过期清理任务
│   └── routes.py           #   所有路由
├── templates/              # 页面
│   ├── login.html · room.html · admin.html · share.html
├── static/style.css
└── data/                   # 自动生成，勿手动改
    ├── rooms.db
    └── files/
```

---

## ❓ 常见问题

**Q：端口被占怎么办？**  
`run.py` 会自动检测并提示占用进程的 PID。要么 `taskkill /pid 那个PID /f`，要么改 `config.toml` 的 `port`。

**Q：手机连不上？**  
确认手机和电脑在**同一 WiFi**，用控制台打印的 `192.168.x.x:3005` 地址（不是 localhost）。电脑防火墙需放行 3005 端口。

**Q：换了 WiFi / 插了网线地址变了？**  
没问题。系统每次启动都重新探测所有 IP，房间页也会显示当前所有可用地址。

**Q：重启服务后数据还在吗？**  
在。房间和文件存在 SQLite + 磁盘里，重启不丢；但**浏览器会话**会失效，需要重新输口令进入。

**Q：怎么彻底重置？**  
删掉 `data/` 目录后重启即可（文件和房间元数据全清）。

---

<div align="center">

## 🎯 现在就用

```bash
git clone https://github.com/snake-aabb-wtf/the-room-system.git
cd the-room-system
python -m pip install -r requirements.txt
python run.py
```

**然后打开浏览器，拖个文件进去。就这么简单。**

---

⭐ 觉得好用？给个 Star 让更多人看到。

*献给所有「只求文件赶紧传过去」的人。*

</div>
