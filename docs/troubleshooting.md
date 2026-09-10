# 排障

## 先跑自检

任何异常先跑一遍，它会指出坏在哪一环（签名 / 某个端点 / 某个筛选）：

```bash
xhs verify --quick
```

## 症状速查

| 症状 | 原因 | 解法 |
|---|---|---|
| `406 {"code":-1,"success":false}` | 请求未带签名，**或**带 params 的 GET 参数编码与签名失配 | 用 `XhsClient`（自动签名）；GET 必须用 `client.build_url()`，别用 `requests` 的 `params=` |
| `500 create invoker failed, service: jarvis-gateway-default` | 网关缺 `X-S-Common` 等必要头 | 用 `XhsClient`（自动注入全套头） |
| `461 / code 300031` 当前笔记暂时无法浏览 | `xsec_token` 缺失或过期 | 重新跑 `search` 拿新鲜 token |
| `400 required param check: target_user_id` | `otherinfo` 传了 `user_id` | 参数名必须是 **`target_user_id`** |
| `404 page not found` | 端点版本或主机不对 | 搜索用 **v1**（不是 v2）；`user_posted` 用 **v1**；只走 `edith.xiaohongshu.com` |
| 搜索返回 `items=0` 但 `success=true` | `page_size` 不是 20 | 强制 20（`XhsClient.search` 已处理） |
| `ConnectionResetError` / `SSLError` | 偶发 TLS 层重置（`so.xiaohongshu.com` 必现） | 已内建 3 次重试；不要用 `so.*` |
| 命中 0 条 + 页面异常 | 触发验证墙 | 停 1–2 分钟，降低频率 |
| `XhsBlockedError` 熔断 | 连续 5 次异常 | 停一段时间；检查 cookies 是否失效；重跑 `xhs cookies` |
| `未找到 cookies` | 状态目录没有 cookies.json | 跑 `xhs cookies` |
| `xhs: command not found` | `~/.local/bin` 不在 PATH | `ln -sf <project>/bin/xhs ~/.local/bin/xhs` |

## 端点与主机

| 主机 | 状态 |
|---|---|
| `edith.xiaohongshu.com` | ✅ 唯一可用主机 |
| `so.xiaohongshu.com` | ❌ 对本机出口 **TLS 层 RST**（curl `--http2` 也一样）。虽然页面 JS 会用它，但从本机直连不可用 |
| `fe-static.xhscdn.com` | ✅ 静态资源无鉴权可拉（逆向签名时用） |

## 签名失效（小红书发版）

症状：原本 200 的请求开始返回 406，且 `X-s` 结构对不上。

处理顺序：

1. `pip install -U xhshow`（或用本项目 venv：`~/.local/share/xhs-venv/bin/pip install -U xhshow`）
2. 若仍失效，检查 vendor bundle 是否变了：
   ```bash
   curl -s https://www.xiaohongshu.com/explore | grep -oE 'vendor-dynamic\.[0-9a-f]+\.js'
   ```
   对照 [architecture.md](architecture.md) §2 的算法结构，确认 `customB64` 字母表与 `x` 字段是否变化。
3. 兜底：回退浏览器路线（用 Agent Browser Runtime 驱动已登录 Chrome 做 UI 自动化），不再依赖纯算签名。

## 指纹相关

| 症状 | 说明 |
|---|---|
| `xhs doctor` 显示 `synthetic` 但你以为是真机 | 没有 pin 文件。跑 `xhs fp`；或设 `XHS_FP_MODE=real` 让它直接报错而不是静默降级 |
| `XHS_FP_MODE=real` 报 `FileNotFoundError` | 这是**故意**的——避免静默降级到合成指纹 |
| 合成指纹与 HTTP UA 不一致 | 已在 `_headers()` 里同步。若自行改代码，注意必须同步 `fp["x1"]` |

## 采集器相关

| 症状 | 说明 |
|---|---|
| 重跑命令没采新数据 | 断点续采在生效（已采 id 跳过）。换 `--out` 目录或删对应 jsonl |
| `authors` 段没跑 | 需要先有 `notes.jsonl`（有 `user_id`）或 `comments.jsonl` |
| 请求数暴涨 | `--authors --author-notes` 会线性放大；用 `--author-limit` / `--max-author-notes` 限流 |

## 相关文档

- [架构与签名原理](architecture.md)
- [风控与封控概率](risk-control.md)
- [API 参考](api-reference.md)
