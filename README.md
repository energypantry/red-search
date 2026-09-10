# xhs-scraper

小红书（xiaohongshu.com）Web API 采集工具。**纯算签名，不需要浏览器在线**——只用一次性取到的 cookies，之后全部请求由本地计算签名后直接发出。

2026-09-10 实测链路全部 HTTP 200：`search → feed → comment → sub_comment → user → user_posted`。

> ⚠️ **仅限私有使用**。本仓库记录了对第三方站点请求签名机制的分析，只应用于你有权处理的数据。见 [LICENSE](LICENSE)。

---

## 能力

| 能力 | 命令 | 产物 |
|---|---|---|
| 关键词搜索 | `xhs search` / `xhs collect search` | `notes.jsonl` |
| 笔记详情（正文/图片/标签/互动数） | `xhs feed` / `xhs collect enrich` | 回写 `notes.jsonl` |
| 一/二级评论 | `xhs comments` / `xhs collect comments` | `comments.jsonl` |
| 作者主页（简介/小红书号/粉丝/获赞/标签/IP属地） | `xhs user` | — |
| 作者已发布笔记 | `xhs usernotes` | — |
| 批量：笔记+评论+作者 | `xhs collect authors` / `run` | `users.jsonl` / `user_notes.jsonl` |

批量采集**断点续采**：重跑同一条命令，已采过的 `note_id` / `comment_id` / `user_id` 自动跳过。

## 安装

```bash
git clone git@github.com:energypantry/xhs-scraper.git
cd xhs-scraper
ln -sf "$PWD/bin/xhs" ~/.local/bin/xhs     # 首次运行会自动建 venv 并装依赖
xhs doctor
```

手动安装等价于：

```bash
python3 -m venv ~/.local/share/xhs-venv
~/.local/share/xhs-venv/bin/pip install -e .
npm install            # JS 侧工具需要 ws
```

## 快速开始

```bash
# 1) 首次：准备好"身份"（决定封控概率，务必先做）
xhs cookies            # 从已登录浏览器取出会话 cookies
xhs fp                 # 抓真机设备指纹并 pin（强烈建议）

# 2) 查询
xhs search "咖啡" 20
xhs user <user_id>
xhs usernotes <user_id> 30

# 3) 批量
xhs collect run --keyword 咖啡 --keyword 手冲 --pages 3 \
    --max-notes 50 --comments --authors --author-notes --out ./out
```

Python 里当库用：

```python
from xhs_scraper import XhsClient

c = XhsClient()                       # 默认读 ~/.local/share/xhs/cookies.json
items = c.search("咖啡").json()["data"]["items"]
nid, tok = items[0]["id"], items[0]["xsec_token"]   # token 在 item 级，不在 note_card 里
note = c.feed(nid, tok).json()
cmts = c.comments(nid, tok).json()
profile = c.user(note["data"]["items"][0]["note_card"]["user"]["user_id"]).json()
```

## 安全默认值（已内建，别关）

- **设备指纹固定化**——`xhshow` 原生默认**每个请求随机换一整套设备指纹**，等于"同一账号每秒换一台新电脑"，是极易被聚类的强异常。本工具把它固定：优先复用真机指纹，否则持久化一份合成指纹。
- **UA 自洽**——HTTP `User-Agent` 跟随指纹模式，避免"请求头说 macOS、指纹说 Windows"的自相矛盾。
- **会话状态复用**——`page_load_timestamp` 稳定、`sequence_value` 单调递增，贴近真实页面会话。
- **熔断 + 节流**——连续异常指数退避，5 次熔断；默认 `throttle=2.5s` + `jitter`。
- **凭据隔离**——cookies / 指纹存 `~/.local/share/xhs/`（chmod 700/600），仓库内 `.gitignore` 兜底。

指纹模式（`XHS_FP_MODE`）：

| 模式 | 身份 | 建议 |
|---|---|---|
| `real`（有 pin 文件时 `auto` 的默认） | 与你 cookies **同源同平台同设备** | ✅ 主号用这个 |
| `synthetic` | 持久化合成指纹（自称 Windows Edge） | 仅配副号 / 无浏览器的服务器 |
| `auto` | 有真机用真机，否则用持久化合成 | 默认 |

> **批量采集勿用主号。** 风控惩罚落在账号上。完整的风险分析见 [docs/risk-control.md](docs/risk-control.md)。

## 项目结构

```
xhs-scraper/
├── bin/xhs                     # 统一入口（shell；自动建 venv、转发子命令、doctor）
├── src/xhs_scraper/
│   ├── client.py               # XhsClient：签名、重试、熔断、指纹解析
│   ├── collect.py              # 批量采集器（四段流水线 + JSONL 断点续采）
│   └── cli.py                  # python -m xhs_scraper.cli
├── tools/
│   ├── get_xhs_cookies.js      # 从已登录浏览器 CDP 取 cookies
│   └── capture_fingerprint.js  # 抓真机设备指纹并 pin
├── docs/
│   ├── architecture.md         # 签名链逆向 + 请求链路（原理）
│   ├── risk-control.md         # 封控概率判断 + 降风险清单
│   ├── api-reference.md        # 已实测端点与参数契约 + 98 端点清单
│   ├── troubleshooting.md      # 踩坑清单
│   └── recon-2026-09-10.md     # 原始侦察证据（逆向全过程）
├── examples/quickstart.md
└── tests/
```

## 文档

- [架构与签名原理](docs/architecture.md) — 签名链、为什么不能手搓、本方案怎么绕过去
- [风控与封控概率](docs/risk-control.md) — 目标侧能看到什么、概率估计、操作清单
- [API 参考](docs/api-reference.md) — 端点、参数契约、返回结构
- [排障](docs/troubleshooting.md) — 踩过的坑与正解
- [原始侦察记录](docs/recon-2026-09-10.md) — 2026-09-10 逆向证据

## 已知边界

- 签名算法随小红书发版可能失效。升级 `xhshow`，或回退到浏览器路线（见 [docs/troubleshooting.md](docs/troubleshooting.md)）。
- `so.xiaohongshu.com` 对本机出口在 TLS 层 RST，走 `edith.xiaohongshu.com`。
- 搜索 `page_size` 必须为 20，其他值服务端返回 0 条。
- 笔记详情必须有新鲜 `xsec_token`（搜索/列表返回的即可；过期会报 `461 / 300031`）。
- 只覆盖 Web 端。移动端 App 协议（`shield` / `x-sign`）未涉及。
