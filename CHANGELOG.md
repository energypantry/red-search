# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-09-10

首次作为独立项目发布（此前散落在个人 agent 工作区的 `xhs-sign/` 目录里）。

### Added

- `XhsClient`：纯算签名客户端（基于 `xhshow`），覆盖 suggest / search / feed / comments / sub_comments / user / user_posted
- 搜索联想词（`GET /api/sns/web/v1/search/recommend`）也已纯算覆盖 → 关键词调研全流程（联想词 → 搜索 → 验证）
  不再需要浏览器路线
- 批量采集器 `xhs_scraper.collect`：`search` / `enrich` / `comments` / `authors` / `run` 四段流水线，
  JSONL 追加安全 + 断点续采
- 统一 CLI `bin/xhs`（自动建 venv、转发子命令、`doctor` 自检）
- `tools/get_xhs_cookies.js`：从 Agent Browser Runtime 的已登录 Chrome 经 CDP 提取 cookies
- `tools/capture_fingerprint.js`：抓取真机设备指纹（`x8`/`x9`/`ua`）并落盘 pin
- 文档：`docs/architecture.md`（签名链逆向）、`docs/risk-control.md`（封控概率判断）、
  `docs/api-reference.md`（98 端点 + 参数契约）、`docs/troubleshooting.md`、
  `docs/recon-2026-09-10.md`（原始侦察证据）
- 离线测试 `tests/`

### Security / Risk

- **修复**：`xhshow` 原生在每个请求里随机重建整套设备指纹（实测同一 cookies 连续三次
  `x8` 哈希 `dc8418b1` / `f9079a03` / `89ba5abf` 全不同），等价于"同账号每秒换一台新电脑"。
  现改为固定指纹：真机 pin 优先，否则持久化合成指纹（跨进程复用）。
- **修复**：合成指纹自称 Windows Edge，而请求头是 macOS Chrome，形成自相矛盾。
  现 `User-Agent` 跟随指纹模式自动同步。
- 新增网络层 3 次重试（`ConnectionResetError` / `SSLError` 是常态）。
- 新增熔断：连续异常指数退避（2→4→8…上限 120s），5 次抛 `XhsBlockedError`。

### Added（续）

- `xhs filters <关键词>` / `client.filter_options()`：拉取服务端**动态下发**的筛选面板定义
  （6 组：排序依据/笔记类型/发布时间/搜索范围/位置距离/热门词），改版后无需再逆向。
- 实测确认：**排序语义客观成立**——`popularity_descending` 的 `liked_count` 严格递减（0 逆序对）、
  `comment_descending` 的 `comment_count` 递减、`collect_descending` 的 `collected_count` 递减。
- 实测确认：**评论列表与作者作品列表没有排序参数**（7 种参数名组合全部被静默忽略），
  只有搜索结果可排序。

- `xhs verify [--quick]`：运行时自检，覆盖签名连通、5 个 sort 枚举、`type`/`time`/`scope`/`location` 筛选、
  组合筛选、feed/comments/sub_comments/user/user_posted、错误处理。改版后据此定位坏点。
- 搜索筛选全部实测通过（此前 `--scope` / `--location` 标注为未验证）。

### Known limitations

- 未模拟页面加载前置序列（`config` → `user/me` → …），属弱信号，见 risk-control §2 R3
- 只覆盖 Web 端；移动端 App 协议（`shield` / `x-sign`）未涉及
- 签名算法随目标站发版可能失效，需跟随升级 `xhshow`
