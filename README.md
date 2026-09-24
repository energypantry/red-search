# red-search

一个可以快速在社交媒体搜索信息的工具。

> ⚠️ **仅限私有使用**。只应用于你有权处理的数据。见 [LICENSE](LICENSE)。

---

## 能力

| 能力 | 命令 | 产物 |
|---|---|---|
| 联想词（下拉推荐） | `xhs suggest` / `xhs collect suggest` | `suggestions.jsonl` |
| 关键词搜索（含排序 / 时间窗 / 类型 / 范围 / 位置筛选） | `xhs search` / `xhs collect search` | `notes.jsonl` |
| 量化统计（均赞 / 中位 / 最高 / 近 90 天占比 / Top5） | `xhs stats <out目录>` | 终端输出 |
| 运行时自检（平台改版后定位坏在哪一环） | `xhs verify [--quick]` | 终端输出 |
| 内容详情（正文 / 图片 / 标签 / 互动数） | `xhs feed` / `xhs collect enrich` | 回写 `notes.jsonl` |
| 一级 / 二级评论 | `xhs comments` / `xhs collect comments` | `comments.jsonl` |
| 作者主页（简介 / 平台号 / 粉丝 / 获赞 / 标签 / IP 属地） | `xhs user` | — |
| 作者已发布内容 | `xhs usernotes` | — |
| 批量：内容 + 评论 + 作者 | `xhs collect authors` / `run` | `users.jsonl` / `user_notes.jsonl` |

批量检索支持**断点续跑**：重跑同一条命令，已取过的 `note_id` / `comment_id` / `user_id` 自动跳过。

## 安装

```bash
git clone git@github.com:energypantry/red-search.git
cd red-search
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
# 1) 首次：准备好本地身份状态（强烈建议先做）
xhs cookies            # 从已登录浏览器取出会话 cookies
xhs fp                 # 抓取并固定本机设备标识

# 2) 查询
xhs suggest "咖啡"      # 联想词
xhs search "咖啡" 20
xhs search "青岛 房东直租" 40 --time week --sort latest   # 搜索支持筛选（条数=总数，自动翻页）
xhs search --help                                        # 全部筛选参数
xhs user <user_id>
xhs usernotes <user_id> 30

# 3) 批量
xhs collect run --keyword 咖啡 --keyword 手冲 --pages 3 \
    --max-notes 50 --comments --authors --author-notes --out ./out

# 时间窗分层（关键：全部档会被老爆款拉高，一周档才反映新帖真实水位）
xhs search "咖啡" 60 --sort likes --time week          # 单次查询
xhs collect search --keyword 咖啡 --pages 3 --sort likes --time week --out ./out-week
xhs stats ./out-week
```

`--sort` 取值：`general` | `latest` | `likes` | `comments` | `collects`
（内部映射为服务端枚举 `time_descending` / `popularity_descending` / …；**直接传 `likes` 给 API 会被静默忽略**，本工具已处理）

`--time` `day|week|half_year` ｜ `--type` `video|image` ｜ `--scope` `seen|unseen|followed` ｜ `--location` `city|nearby`

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

## 稳定性默认值（已内建）

- **设备标识固定化** —— 底层签名库原生默认**每个请求随机换一整套设备标识**，等于"同一账号每秒换一台新电脑"，是极易被聚类的强异常。本工具把它固定：优先复用真机标识，否则持久化一份合成标识。
- **UA 自洽** —— HTTP `User-Agent` 跟随标识模式，避免"请求头说 macOS、标识说 Windows"的自相矛盾。
- **会话状态复用** —— `page_load_timestamp` 稳定、`sequence_value` 单调递增，贴近真实页面会话。
- **熔断 + 节流** —— 连续异常指数退避，5 次熔断；默认 `throttle=2.5s` + `jitter`。
- **凭据隔离** —— cookies / 设备标识存 `~/.local/share/xhs/`（chmod 700/600），仓库内 `.gitignore` 兜底。

标识模式（`XHS_FP_MODE`）：

| 模式 | 身份 | 建议 |
|---|---|---|
| `real`（有 pin 文件时 `auto` 的默认） | 与你 cookies **同源同平台同设备** | ✅ 主号用这个 |
| `synthetic` | 持久化合成标识（自称 Windows Edge） | 仅配副号 / 无浏览器的服务器 |
| `auto` | 有真机用真机，否则用持久化合成 | 默认 |

> **批量检索勿用主号。** 访问限制的惩罚落在账号上。完整的风险评估见 [docs/risk-control.md](docs/risk-control.md)。

## 自检

平台改动接口或筛选后，跑一遍就知道坏在哪一环（会发起真实请求）：

```bash
xhs verify --quick     # ≈22 次请求
xhs verify             # ≈46 次请求，含发布时间窗口的客观抽查
```

覆盖：请求签名连通 → 5 个 sort 枚举互不相同 → `type` 筛选（断言返回类型）→ `time` 筛选（抽查发布时间是否真在窗口内）→ `scope` / `location` 筛选（对比结果集重叠率）→ 组合筛选 → feed / comments / sub_comments / user / user_posted → 错误处理。

## 项目结构

```
red-search/
├── bin/xhs                     # 统一入口（shell；自动建 venv、转发子命令、doctor）
├── src/xhs_scraper/
│   ├── client.py               # XhsClient：请求签名、重试、熔断、设备标识解析
│   ├── collect.py              # 批量检索器（四段流水线 + JSONL 断点续跑）
│   └── cli.py                  # python -m xhs_scraper.cli
├── tools/
│   ├── get_xhs_cookies.js      # 从已登录浏览器 CDP 取 cookies
│   └── capture_fingerprint.js  # 抓取真机设备标识并 pin
├── docs/
│   ├── architecture.md         # 请求链路与签名结构（原理）
│   ├── risk-control.md         # 访问频次风险判断 + 降风险清单
│   ├── api-reference.md        # 已实测端点与参数契约 + 端点全量清单
│   └── troubleshooting.md      # 踩坑清单
├── examples/quickstart.md
└── tests/
```

## 文档

- [架构与请求链路](docs/architecture.md) — 签名结构、为什么不自己拼、本方案怎么处理
- [访问频次与风险](docs/risk-control.md) — 目标侧能看到什么、概率估计、操作清单
- [API 参考](docs/api-reference.md) — 端点、参数契约、返回结构
- [排障](docs/troubleshooting.md) — 踩过的坑与正解

## 与浏览器路线的关系

本工具是**默认路线**。另有基于 Agent Browser Runtime 驱动已登录 Chrome 的浏览器路线
（入口是本地 agent 工作区里的一份 `xhs.sh` 封装，不随本仓库分发），**仅作备用**，只在以下情况启用：

1. 本工具返回 **406 / 网关错误**（请求签名失效，等 `xhshow` 跟进发版）
2. 需要页面级截图或 HTML
3. 需要真人级行为信号的场景（高风险账号 / 养号）
4. cookies 失效且无法重新取，但浏览器已登录

> 浏览器路线与本项目共享同一套 cookies（在同一个浏览器 profile 里）。回退是**例外**，不是默认。

## 已知边界

- 签名算法随平台发版可能失效。升级 `xhshow`，或回退到浏览器路线（见 [docs/troubleshooting.md](docs/troubleshooting.md)）。
- 搜索 `page_size` 必须为 20，其他值服务端返回 0 条。
- 内容详情必须有新鲜的 `xsec_token`（搜索 / 列表返回的即可；过期会报 `461 / 300031`）。
- 只覆盖 Web 端；移动端 App 协议（`shield` / `x-sign`）未涉及。
