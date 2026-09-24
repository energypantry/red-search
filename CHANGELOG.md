# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.1] - 2026-09-10

### Added

- **`xhs verify [--quick]`** — 运行时自检，改版后一键定位坏在哪一环。
  覆盖：签名连通、包导出面、5 个 sort 枚举、`type`/`time`/`scope`/`location` 筛选、
  组合筛选、feed / comments / sub_comments / user / user_posted、错误处理。
  `--quick` 约 22 次请求，全量约 46 次；退出码 0/1 可用于 CI。
- **`xhs filters <关键词>`** / `client.filter_options()` — 拉取服务端**动态下发**的筛选面板定义
  （6 组：排序依据 / 内容类型 / 发布时间 / 搜索范围 / 位置距离 / 热门词），
  平台改版后不必再自行分析就能看到有哪些筛选。
- **`xhs stats <notes.jsonl|目录>`** — 量化统计（均赞 / 中位 / 最高 / 近 90 天占比 / Top5）。
- 搜索筛选支持（`--time` / `--type` / `--scope` / `--location` / `--hot`），
  含时间窗分层方法论（全部档会被老爆款拉高，一周档才反映新帖真实水位）。

### Fixed

- **`sort` 枚举传错被服务端静默忽略**：`--sort likes` 此前直接把友好名发给 API，
  服务端不认，退化成"综合"（实测均赞 2616 vs 正确 `popularity_descending` 的 10377）。
  现映射为服务端枚举 `time_descending` / `popularity_descending` / `comment_descending` /
  `collect_descending`。
- **`xhs search` 支持筛选参数**：原先 CLI 只接受 `关键词 [N]`，且 `N` 被当作 `page_size`
  （服务端强制 20，导致 `N` 实际无效、恒返回 20 条）。现在
  `xhs search <关键词> [条数] [--sort/--time/--type/--scope/--location/--hot]`，
  `条数` 为**目标总数**（自动翻页，如 40 会拉 2 页）。
- **`xhs search` 对非法筛选取值直接报错**：服务端对非法 `sort` / `filters` tag 是**静默忽略**
  （返回 200 但退化成默认值）。现在本地校验并列出允许取值。
- **补齐包导出**：`build_filters` / `SORT_MAP` / `TIME_MAP` / `TYPE_MAP` / `SCOPE_MAP` /
  `LOCATION_MAP` / `decode_custom_b64` 现在可从 `xhs_scraper` 直接导入
  （此前只能 `from xhs_scraper.client import ...`，与文档示例不符）。

### Verified（实测结论，非代码变更）

- **筛选全部真实生效**，且是**判别性**验证（不是"返回 200 就算过"）：
  - `sort`：5 个枚举与 `general` 结果集重叠 0–19%，各不相同
  - `--type`：客观断言通过（`video` 档返回项全为 `video`，`image` 档全为 `normal`）
  - `--time`：客观抽查通过（`day` ≤0.98 天 / `week` ≤5.45 天 / `half_year` ≤168 天，且各档可区分）
  - `--scope`：与"不限"重叠 `seen` 0% / `unseen` 90% / `followed` 0%
  - `--location`：与"不限"重叠 `city` 29% / `nearby` 29%
- **排序语义客观成立**：`popularity_descending` 返回的 `liked_count` 严格递减（0 逆序对）、
  `comment_descending` 的 `comment_count` 递减、`collect_descending` 的 `collected_count` 递减。
- **评论列表与作者作品列表没有排序参数**：`sort` / `sort_type` / `order` / `order_type` 等
  7 种参数名组合喂给 `/v2/comment/page` 与 `/v1/user_posted`，返回与不传**完全一致**（被静默忽略）。
  只有搜索结果可排序；要"某作者的爆款"只能全量拉回本地排序。

## [0.1.0] - 2026-09-10

首次作为独立项目发布（此前散落在个人 agent 工作区的 `xhs-sign/` 目录里）。

### Added

- `XhsClient`：纯算签名客户端（基于 `xhshow`），覆盖 suggest / search / feed / comments / sub_comments / user / user_posted
- 搜索联想词（`GET /api/sns/web/v1/search/recommend`）也已纯算覆盖 → 关键词调研全流程（联想词 → 搜索 → 验证）
  不再需要浏览器路线
- 批量检索器 `xhs_scraper.collect`：`search` / `enrich` / `comments` / `authors` / `run` 四段流水线，
  JSONL 追加安全 + 断点续采
- 统一 CLI `bin/xhs`（自动建 venv、转发子命令、`doctor` 自检）
- `tools/get_xhs_cookies.js`：从 Agent Browser Runtime 的已登录 Chrome 经 CDP 提取 cookies
- `tools/capture_fingerprint.js`：抓取真机设备指纹（`x8`/`x9`/`ua`）并落盘 pin
- 文档：`docs/architecture.md`（请求链路与签名结构）、`docs/risk-control.md`（访问频次风险判断）、
  `docs/api-reference.md`（端点与参数契约）、`docs/troubleshooting.md`
- 离线测试 `tests/`

### Security / Risk

- **修复**：`xhshow` 原生在每个请求里随机重建整套设备指纹（实测同一 cookies 连续三次
  `x8` 哈希 `dc8418b1` / `f9079a03` / `89ba5abf` 全不同），等价于"同账号每秒换一台新电脑"。
  现改为固定指纹：真机 pin 优先，否则持久化合成指纹（跨进程复用）。
- **修复**：合成指纹自称 Windows Edge，而请求头是 macOS Chrome，形成自相矛盾。
  现 `User-Agent` 跟随指纹模式自动同步。
- 新增网络层 3 次重试（`ConnectionResetError` / `SSLError` 是常态）。
- 新增熔断：连续异常指数退避（2→4→8…上限 120s），5 次抛 `XhsBlockedError`。

### Known limitations

- 未模拟页面加载前置序列（`config` → `user/me` → …），属弱信号，见 risk-control §2 R3
- 只覆盖 Web 端；移动端 App 协议（`shield` / `x-sign`）未涉及
- 签名算法随目标站发版可能失效，需跟随升级 `xhshow`
