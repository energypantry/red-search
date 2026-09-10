# 架构与签名原理

## 1. 目标侧的签名门

小红书 Web（`edith.xiaohongshu.com`）每个 API 请求必须携带：

```
X-s          XYS_<customBase64(JSON{ x0..x7 })>     # 请求签名
X-S-Common   <customBase64(JSON{ s0..x12 })>        # 设备/环境指纹
X-t          毫秒时间戳
```

[可选] `X-Mns`（`window.mns` 存在时）、`Sc-T`、`X-Sign`、`x-b3-traceid`、`x-rap-param`（feed/搜索等高压接口）。

缺签名时：POST 返回 `406 {"code":-1,"success":false}`；GET 返回 `500 create invoker failed`。

## 2. 签名算法（源码级确证）

源码位置：`fe-static.xhscdn.com/formula-static/xhs-pc-web/public/resource/js/vendor-dynamic.0d98fa0a.js`，
webpack module `384`（md5 / custom-base64 / crc32）+ module `4455`（`signV2Init`，注入 `window.mnsv2`）。

```text
webBuild = "4.4.3"        appVer = "6.52.0"        platform = navigator.userAgentData.platform

content = path                                   # GET
        | path + JSON.stringify(body)            # POST(object/array)
        | path + body                            # POST(string)

x5 = MD5(content)          p = MD5(path)
x3 = window.mnsv2(content, x5, p)                # 核心签名器，非确定性（内含 nonce）
{x6, x7} = buildEncSskSign(x5)                   # localStorage ssk map + SHA1 + nonce

X-s = "XYS_" + customB64(utf8(JSON.stringify(
        {x0: webBuild, x1: "xhs-pc-web", x2: platform, x3,
         x4: typeof(body) | "", x5, x6, x7})))

X-S-Common = customB64(utf8(JSON.stringify(
        {s0: 4, s1: "", x0: 1, x1: "4.4.3", x2: platform, x3: "xhs-pc-web", x4: "6.52.0",
         x5: <cookie a1>, x6: "", x7: "", x8: <2KB 指纹 blob>,
         x9: crc32(...), x10: 签名计数, x11: "normal", x12: "<ts>;<ts>"})))

customB64 字母表 = "ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5"
```

> **实现差异（实测）**：真机抓包的 `X-s` payload 是 `x0..x7`（含 `x5`=md5、`x6/x7`=encSsk）；
> `xhshow` 的纯算实现只发 `x0..x4`，服务端一样返回 200。可见 `x5/x6/x7` 至少在 Web 端不是硬校验项。
> 本项目的测试按实际实现断言。

### 已验证的部分

| 断言 | 证据 |
|---|---|
| `x5 = MD5(path[+body])` | 用 12/21 条真实抓包逐一反算命中 |
| App 自身调用 `window.mnsv2(content, x5, MD5(path))` | 钩住 `window.mnsv2` 重载页面，逐字捕获 23 次调用 |
| `window.mnsv2` / `window._webmsxyw` 全局可调 | 页面内求值确认 |

原始证据：抓包脚本与输出见 [recon-2026-09-10.md](recon-2026-09-10.md)。

### 为什么不能手搓（直接复用 xhshow，不要自己拼）

1. `x6/x7`（encSsk）依赖浏览器 `localStorage` 的 ssk map + SHA1 nonce，**无法离线重建**
2. `X-S-Common` 的 `x8` 是 2KB+ 设备指纹 blob（含 GPU/Canvas/WebGL/字体/屏幕等），且与 `a1` 绑定
3. 手动调 `mnsv2` 得到 `mns0301_*`，而 App 自身调用是 `mns0101_*`（同函数、同参数、同页面，内部分支未对齐）
4. 自算 `X-s` 长度 ~408，真实 556~564——缺的正是 `x6/x7`

## 3. 本方案怎么绕过去

用 [`xhshow`](https://github.com/Cloxl/xhshow)（PyPI v0.2.0，MIT）——它把整套算法**完整重实现为纯计算**：

| 原阻塞点 | xhshow 的解法 |
|---|---|
| `x6/x7` encSsk | `sign_xs_get/post()` 纯算产出完整 `XYS_` |
| `x8` 设备指纹 blob | `generators/fingerprint.py` 本地伪造（GPU/屏幕/canvas/WebGL/字体从候选池组合），`generate_b1()` 打包 |
| `mnsv2` 分支 | 完全绕开 |
| feed/搜索风控头 | `x_rap=True` → `x-rap-param` |
| 会话状态 | `SessionManager` 维护 `page_load_timestamp` / `sequence_value` / `window_props_length` |

**供应链审计**（下载 sdist 只读审查）：无网络/外联调用、无 `subprocess`/`eval`/`exec`/`pickle`，依赖仅 `pycryptodome`。

## 4. 本项目的加固层

`src/xhs_scraper/client.py` 在 xhshow 之上做了四件事：

| 加固 | 实现 | 为什么 |
|---|---|---|
| 指纹固定化 | `resolve_fingerprint()` 猴补 `FingerprintGenerator` | xhshow 原生每请求随机换指纹 → 强异常信号。见 [risk-control.md](risk-control.md) |
| UA 自洽 | `_headers()` 用与指纹匹配的 UA | 避免"HTTP 头说 macOS、指纹 x1 说 Windows Edge" |
| 会话复用 | 单个 `SessionManager` 贯穿所有请求 | pageLoadTs 稳定、sequence 递增 |
| 熔断 + 重试 | 指数退避、5 次熔断、网络层 3 次重试 | 风控与偶发 TLS 重置 |

## 5. 请求链路

```
bin/xhs ──> python -m xhs_scraper.cli
              │
              ├── client.XhsClient
              │      ├─ 签名: xhshow（纯算；指纹已固定）
              │      ├─ 节流/抖动/熔断/重试
              │      └─ requests ──HTTPS──> edith.xiaohongshu.com
              │                                 /api/sns/web/v1/search/notes    POST
              │                                 /api/sns/web/v1/feed            POST
              │                                 /api/sns/web/v2/comment/page    GET
              │                                 /api/sns/web/v2/comment/sub/page GET
              │                                 /api/sns/web/v1/user/otherinfo  GET
              │                                 /api/sns/web/v1/user_posted     GET
              └── collect  四段流水线，JSONL 追加安全 + 断点续采
```

## 6. 身份/状态存储

```
~/.local/share/xhs/           (chmod 700)
├── cookies.json              (600)  会话 cookies —— 用 tools/get_xhs_cookies.js 生成
├── device_fingerprint.json   (600)  真机指纹 pin —— 用 tools/capture_fingerprint.js 生成
└── synthetic_fingerprint.json(600)  持久化合成指纹（首次用 synthetic 模式时自动生成）
```

venv 默认在 `~/.local/share/xhs-venv`（`XHS_VENV` 可覆盖）。

## 相关文档

- [风控与封控概率](risk-control.md)
- [API 参考](api-reference.md)
- [排障](troubleshooting.md)
- [原始侦察记录](recon-2026-09-10.md)
