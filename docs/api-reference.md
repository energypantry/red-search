# API 参考

主机：`edith.xiaohongshu.com`（唯一可用；`so.xiaohongshu.com` 对本机出口 TLS 层 RST）。
除特别说明外，全部需要签名头（由 `XhsClient` 自动注入）。

## 1. 已实测端点与参数契约

### `GET /api/sns/web/v1/search/notes` — ⚠️ 实为 POST

搜索笔记。**必须用 v1**（`v2` 在同主机返回 404）。

```python
c.search(keyword, page=1, page_size=20, sort="general")
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `keyword` | ✅ | 关键词 |
| `page` | ✅ | 从 1 开始 |
| `page_size` | ✅ | **必须为 20**，其他值服务端返回 0 条 |
| `search_id` | ✅ | base36，由 `Xhshow.get_search_id()` 生成 |
| `sort` | | `general` / `latest` / `likes` / `comments` / `collects` |
| `note_type` | | `0` 不限 |
| `ext_flags` / `image_formats` / `need_filter_image` | | 固定值，见实现 |

返回：`data.items[]`，每项含 `id`(note_id)、**`xsec_token`（item 级，46 字符）**、`note_card`。
搜索结果里混有直播/AI 占位条目，需过滤（`note_id` 必须是 24 位 hex 且 `note_card` 非空）。

### `GET /api/sns/web/v1/search/recommend` — 搜索联想词

```python
c.suggestions("咖啡")     # -> ["咖啡推荐", "咖啡店", ...]
```

参数：`keyword`（必填）、`source`（可选，如 `web_search_result_notes`）。
返回：`data.sug_items[].text` 为建议词；`data.search_cpl_id` / `data.word_request_id` 为会话标识。

> 注意成功码是 `code=1000`（不是 0），但 `success=true`。

### `POST /api/sns/web/v1/feed` — 笔记详情

```python
c.feed(note_id, xsec_token, xsec_source="pc_search")
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `source_note_id` | ✅ | note_id |
| `xsec_token` | ✅ | 来自搜索/列表；**过期会返回 461 / code 300031** |
| `xsec_source` | | `pc_search` / `pc_user` … |
| `image_formats` | | `["jpg","webp","avif"]` |
| `extra.need_body_topic` | | `"1"` |

返回：`data.items[0].note_card` → `title` / `desc` / `type` / `image_list` / `tag_list` / `time` / `ip_location` / `interact_info`(liked/collected/comment count)。

### `GET /api/sns/web/v2/comment/page` — 一级评论

```python
c.comments(note_id, xsec_token, cursor="")
```

参数：`note_id`、`cursor`、`top_comment_id`(空串)、`image_formats`(`"jpg,webp,avif"`)、`xsec_token`。
返回：`data.comments[]` / `data.has_more` / `data.cursor`。

> ⚠️ 带参数的 GET 必须用 `client.build_url(uri, params)` 产出最终 URL 再请求。
> 用 `requests` 的 `params=` 会二次编码，与签名输入失配 → **406**。

### `GET /api/sns/web/v2/comment/sub/page` — 二级评论

参数：`note_id`、`root_comment_id`、`num`、`cursor`、`image_formats`、`top_comment_id`、`xsec_token`。

### `GET /api/sns/web/v1/user/otherinfo` — 作者主页

| 参数 | 必填 | 说明 |
|---|---|---|
| `target_user_id` | ✅ | **注意不是 `user_id`**；传错报 `400 required param check: target_user_id` |
| `xsec_token` | | 可省 |

返回 `data`：

- `basic_info`：`nickname` / `red_id`(小红书号) / `gender` / `ip_location` / `desc`(简介) / `images`(头像)
- `interactions[]`：`{type: follows|fans|interaction, count}` — **count 是字符串**
- `tags[]`：星座/职业标签
- `tab_public` / `extra_info` / `result`

### `GET /api/sns/web/v1/user_posted` — 用户已发布笔记

| 参数 | 必填 | 说明 |
|---|---|---|
| `user_id` | ✅ | 这里是 `user_id` |
| `num` | | 默认 30 |
| `cursor` | | 翻页 |

> `v2/user_posted` 在 `edith` 返回 404，用 **v1**。
> 返回项结构与搜索结果一致（含 `note_id` + `xsec_token`）。

## 2. 端点全量清单（98 条，从 vendor bundle 的自动生成客户端提取）

> 由页面 JS 里的 `getApiSns*/postApiSns*` 函数表提取，含未实测端点。方法/路径可信，参数需自行验证。

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/api/im/redmoji/detail` | web  表情列表 |
| `GET` | `/api/im/redmoji/version` | web  表情列表 版本 |
| `POST` | `/api/sns/red/live/app/gift/v1/worldcup/web/host_team_change` | 世界杯 - 主队更换（web） |
| `GET` | `/api/sns/red/live/app/gift/v1/worldcup/web/host_team_info` | 世界杯 - 主队信息查询（web） |
| `POST` | `/api/sns/red/live/v1/web/room_user/viewer_heart` | 直播用户-观众心跳 |
| `GET` | `/api/sns/red/live/web/comment/v1/user_violation` | 【web】查询评论判罚信息 |
| `GET` | `/api/sns/red/live/web/feed/category` | 直播列表页垂类接口 |
| `GET` | `/api/sns/red/live/web/feed/v1/squarefeed` | web直播列表页 |
| `POST` | `/api/sns/red/live/web/gift/v1/batch_send_gift` | 礼物面板批量送礼（web） |
| `POST` | `/api/sns/red/live/web/gift/v1/batch_send_gift_finish` | 【web】【礼物】批量送礼结束 V1 |
| `GET` | `/api/sns/red/live/web/gift/v1/gift_panel` | 直播间礼物面板（web） |
| `POST` | `/api/sns/red/live/web/gift/v1/give/gift` | 直播 - 送礼（web） |
| `POST` | `/api/sns/red/live/web/gift/v1/give/gift/finish` | 直播 - 送礼结束（web） |
| `GET` | `/api/sns/red/live/web/group_live/entrance` | 团播成员信息 |
| `POST` | `/api/sns/red/live/web/paid_live/preview_report` | 【Web】付费直播-试看上报接口 |
| `POST` | `/api/sns/red/live/web/paid_live/purchase` | 【Web】付费直播-付费购买权益 |
| `POST` | `/api/sns/red/live/web/paid_live/query_price_info` | 付费直播-查询价格信息 |
| `GET` | `/api/sns/red/live/web/pay/v1/charge_panel` | 直播 -充值面板（web） |
| `POST` | `/api/sns/red/live/web/pay/v1/prepare_charge_transaction` | 直播 -充值 |
| `GET` | `/api/sns/red/live/web/pay/v1/wallet/coins/balance` | 直播 -钱包薯币余额（web） |
| `GET` | `/api/sns/red/live/web/resource_by_id` | web端礼物特效资源获取 |
| `POST` | `/api/sns/red/live/web/room/share` | 房间分享上报(web观播) |
| `GET` | `/api/sns/red/live/web/share` | 直播间分享 |
| `GET` | `/api/sns/red/live/web/v1/activity_platform/world_cup_calendar` | 世界杯 - 查询赛事日历详情 |
| `POST` | `/api/sns/red/live/web/v1/activity_platform/world_cup_live_info` | 世界杯 - 查询实时赛况 |
| `POST` | `/api/sns/red/live/web/v1/activity_platform/world_cup_match_lineup` | 世界杯 - 查询比赛阵容 |
| `POST` | `/api/sns/red/live/web/v1/activity_platform/world_cup_query_player_single_base` | 查询球员基础信息-含官号、圈子明细信息 |
| `POST` | `/api/sns/red/live/web/v1/center/room/join/room` | web-通过直播间id进房 |
| `POST` | `/api/sns/red/live/web/v1/line/mic_relation` | 拉取麦上用户信息-web |
| `GET` | `/api/sns/red/live/web/v1/room/aggregate_business_info` | 多直播间/多机位列表 |
| `GET` | `/api/sns/red/live/web/v1/room/current_room_info` | web-进房获取直播间信息 |
| `GET` | `/api/sns/red/live/web/v1/room/join_business_base_info` | 进房获取基础业务信息 |
| `GET` | `/api/sns/red/live/web/v1/room/join_comment_info` | web-进房获取评论区信息 |
| `POST` | `/api/sns/red/live/web/v1/trailer/cancel_subscribe` | 直播预告 - 取消订阅（web） |
| `POST` | `/api/sns/red/live/web/v1/trailer/subscribe` | 直播预告 - 订阅（web） |
| `GET` | `/api/sns/red/live/web/{sourceId}/user_card` | 资料卡 |
| `GET` | `/api/sns/v1/live/web/activity/world/cup26/incidents` | 26世界杯-web端查询某场赛事的全量的事件信息 |
| `POST` | `/api/sns/v1/live/web/interaction/send_comment` | 直播互动 - 评论-web |
| `GET` | `/api/sns/v6/relatedfeed/web` | 【web】高光视频 |
| `POST` | `/api/sns/web/ares/config` | 获取申述页面配置 |
| `POST` | `/api/sns/web/ares/submit` | 申述提交入口 |
| `GET` | `/api/sns/web/global/config` | 首页全局加载 |
| `POST` | `/api/sns/web/nio/feed` | nio笔详feed |
| `POST` | `/api/sns/web/nio/init` | nio视频精选首页 |
| `POST` | `/api/sns/web/report/list` | web获取举报项 |
| `POST` | `/api/sns/web/report/submit` | web提交举报 |
| `POST` | `/api/sns/web/v1/board` | web创建专辑 |
| `GET` | `/api/sns/web/v1/board/note` | web专辑笔记列表 |
| `GET` | `/api/sns/web/v1/board/user` | web查询用户的专辑 |
| `GET` | `/api/sns/web/v1/board/{boardId}` | web获取专辑信息 |
| `POST` | `/api/sns/web/v1/comment/delete` | web-删除评论 |
| `POST` | `/api/sns/web/v1/comment/dislike` | web-评论取消点赞 |
| `POST` | `/api/sns/web/v1/comment/like` | web-评论点赞 |
| `POST` | `/api/sns/web/v1/comment/post` | web-创建评论 |
| `GET` | `/api/sns/web/v1/common/dual_feed` | web精选视频feed |
| `POST` | `/api/sns/web/v1/feed` | 【web】- feed |
| `GET` | `/api/sns/web/v1/get_liked_num` | 【web】获取登录后的真实点赞数 |
| `POST` | `/api/sns/web/v1/homefeed` | 【web】- homefeed |
| `GET` | `/api/sns/web/v1/homefeed/category` | 【web】- homefeed_category |
| `POST` | `/api/sns/web/v1/homefeed/initial_load` | 【web】首刷homefeed  |
| `GET` | `/api/sns/web/v1/intimacy/intimacy_list` | web At用户列表 |
| `GET` | `/api/sns/web/v1/intimacy/intimacy_list/search` | web查询At搜索用户 |
| `POST` | `/api/sns/web/v1/login/activate` | web登录-用户激活 |
| `GET` | `/api/sns/web/v1/login/check_code` | web登录-验证验证码 |
| `POST` | `/api/sns/web/v1/login/code` | web登录-验证码登录 |
| `GET` | `/api/sns/web/v1/login/logout` | web登录-用户退登 |
| `POST` | `/api/sns/web/v1/login/qrcode/create` | web登录-创建二维码 |
| `GET` | `/api/sns/web/v1/login/qrcode/status` | web登录-获取二维码状态 |
| `GET` | `/api/sns/web/v1/login/send_code` | web登录-发送验证码 |
| `POST` | `/api/sns/web/v1/login/social` | web端三方登录 |
| `POST` | `/api/sns/web/v1/note/collect` | web笔记收藏 |
| `POST` | `/api/sns/web/v1/note/dislike` | WEB-笔记取消点赞 |
| `POST` | `/api/sns/web/v1/note/like` | WEB-笔记点赞 |
| `GET` | `/api/sns/web/v1/note/like/page` | web-个人页点赞列表 |
| `POST` | `/api/sns/web/v1/note/metrics_report` | 笔记详情页进入和退出时调取的指标上报接口-web |
| `POST` | `/api/sns/web/v1/note/move` | web专辑间移动笔记 |
| `POST` | `/api/sns/web/v1/note/uncollect` | web笔记取消收藏 |
| `POST` | `/api/sns/web/v1/nps` | 【web】-NPS |
| `GET` | `/api/sns/web/v1/resource_load` | [web]活动资源位预加载 |
| `GET` | `/api/sns/web/v1/search/filter` | web搜索-筛选项 |
| `POST` | `/api/sns/web/v1/search/onebox` | onebox |
| `GET` | `/api/sns/web/v1/search/recommend` | search-recommend |
| `POST` | `/api/sns/web/v1/search/usersearch` | 用户搜索 |
| `GET` | `/api/sns/web/v1/system/config` | web系统配置 |
| `POST` | `/api/sns/web/v1/user/follow` | web 用户关注 |
| `GET` | `/api/sns/web/v1/user/hover_card` | web hover展示用户卡片 |
| `POST` | `/api/sns/web/v1/user/info` | web端编辑资料 |
| `GET` | `/api/sns/web/v1/user/otherinfo` | web他人页 |
| `GET` | `/api/sns/web/v1/user/selfinfo` | web个人页 |
| `POST` | `/api/sns/web/v1/user/unfollow` | web 用户取消关注 |
| `GET` | `/api/sns/web/v1/user_posted` | 【web】- user_posted |
| `GET` | `/api/sns/web/v2/comment/page` | web-查询一级评论列表 |
| `GET` | `/api/sns/web/v2/comment/sub/page` | web-查询二级评论 |
| `POST` | `/api/sns/web/v2/login/code` | web短信验证码登录注册 |
| `GET` | `/api/sns/web/v2/login/send_code` | web登录-发送验证码v2 |
| `GET` | `/api/sns/web/v2/note/collect/page` | web-个人页收藏列表 |
| `GET` | `/api/sns/web/v2/user/me` | web用户-个人信息V2 |
| `GET` | `/api/sns/web/v2/user_posted` | 【web】- user_posted v2 |

## 3. 其它值得注意的端点

| 端点 | 说明 |
|---|---|
| `GET /api/sns/web/v1/search/filter` | 搜索筛选项 |
| `POST /api/sns/web/v1/search/usersearch` | 用户搜索 |
| `POST /api/sns/web/v1/homefeed` | 首页推荐流 |
| `GET /api/sns/web/v1/note/like/page` | 个人页点赞列表 |
| `GET /api/sns/web/v2/note/collect/page` | 个人页收藏列表 |
| `GET /api/sns/web/v1/board/{boardId}` | 专辑信息 / 专辑笔记 |
| `GET /api/sns/web/v1/user/hover_card` | 用户悬浮卡片 |

## 相关文档

- [架构与签名原理](architecture.md)
- [排障](troubleshooting.md)
- [原始侦察记录](recon-2026-09-10.md)
