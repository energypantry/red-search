# 示例

## 0. 准备（只需一次）

```bash
ln -sf "$PWD/bin/xhs" ~/.local/bin/xhs
xhs doctor          # 首次会自动建 venv 装依赖
xhs cookies         # 从已登录浏览器取会话 cookies
xhs fp              # 抓真机设备指纹并 pin  ← 决定封控概率，别跳过
```

`xhs doctor` 期望输出（关键行）：

```
project   : /Users/zhi/Desktop/Projects/xhs-scraper
指纹模式  : real | Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) …
            （真机指纹已 pin；切合成: XHS_FP_MODE=synthetic xhs ...）
cookies   : 已就绪 (~/.local/share/xhs/cookies.json)
node deps : 已安装
```

## 1. 单次查询

```bash
$ xhs suggest "咖啡"
{
  "keyword": "咖啡",
  "count": 10,
  "suggestions": ["咖啡推荐", "咖啡店", "咖啡冻干", "咖啡豆", "咖啡自制",
                  "咖啡文案", "咖啡的好处与坏处", "咖啡师", "咖啡渍怎么洗", "咖啡搭配什么好喝自制"]
}

$ xhs search "咖啡" 20
success=True items=22
  69fcbbd00000000023006dc5  tok=AB9kB-1OC-bZWBOJ…  青岛 咖啡搭子☕ 一个月50k  likes=58
  6a3e770c000000001503ed35  tok=ABYeLc1fPlQDXSSU…  楼顶咖啡☕️  likes=7477
  6a88fe7f000000003703d65c  tok=ABCZ_pCGJXg0ovOn…  青岛｜不能错过咖啡新店 瞧岛  likes=296
```

拿第一条的 `note_id` + `tok` 看详情和评论：

```bash
$ xhs feed 69fcbbd00000000023006dc5 'AB9kB-1OC-bZWBOJ...'
{
  "title": "青岛 咖啡搭子☕ 一个月50k",
  "desc": "……511 字正文……",
  "interact": {"liked_count": "58", "collected_count": "3", "comment_count": "123"},
  "images": 1
}

$ xhs comments 69fcbbd00000000023006dc5 'AB9kB-1OC-bZWBOJ...'
{ "success": true, "code": 0, "data": { "comments": [ ... ], "has_more": true } }
```

看作者：

```bash
$ xhs user 59d112e520e88f4092b2b3ce
{
  "user_id": "59d112e520e88f4092b2b3ce",
  "nickname": "是大西阿",
  "red_id": "cc1001cc",
  "gender": 1,
  "ip_location": "山东",
  "desc": "😁Enfj-a\n🧮前成本PM|✍🏻8年撰稿人\n☕咖啡发烧友|📸到处旅行",
  "avatar": "https://sns-avatar-qc.xhscdn.com/avatar/…",
  "counts": { "follows": "161", "fans": "2654", "interaction": "72240" },
  "tags": ["天秤座", "旅行博主", "运动博主"]
}

$ xhs usernotes 59d112e520e88f4092b2b3ce 5
success=True notes=7
  65dbeb40000000000b023e8d  青岛❗反复去不腻的宝藏品质咖啡厅！合集！   赞=1095  1708911424000
```

## 2. 全链路批量

```bash
$ xhs collect run \
    --keyword 咖啡 --keyword 手冲 --pages 3 \
    --max-notes 50 --comments --authors --author-notes \
    --out ./out --throttle 2.5
[2026-09-10 22:22:54] 指纹模式: real | UA: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) …
[2026-09-10 22:22:57] search '冷萃' p1: +22 条 (累计新增 20)
[2026-09-10 22:22:57] 搜索段完成，新增 20 条 -> ./out/notes.jsonl
[2026-09-10 22:23:03] 详情段完成，成功 2 条
[2026-09-10 22:23:07] 评论段完成，新增 36 条 -> ./out/comments.jsonl
[2026-09-10 22:23:25] 作者段完成，新增 3 条 -> ./out/users.jsonl
[2026-09-10 22:23:25] 完成。请求 11 次 / 异常 0 次
```

产物：

| 文件 | 内容 |
|---|---|
| `notes.jsonl` | 笔记：`note_id` / `xsec_token` / `title` / `desc` / `tags` / `images` / 互动数 / `keyword` |
| `comments.jsonl` | 评论：`comment_id` / `note_id` / `parent_id`（二级评论有值）/ `content` / `like_count` |
| `users.jsonl` | 作者：`nickname` / `red_id` / `follows` / `fans` / `interaction` / `ip_location` / `desc` / `tags` / `sources` |
| `user_notes.jsonl` | 作者已发布笔记（`--author-notes` 时） |

**断点续采**：重跑同一条命令即可，已采过的 id 自动跳过。

## 3. 当库用

```python
from xhs_scraper import XhsClient

c = XhsClient(throttle=2.0, jitter=0.8)

items = c.search("咖啡").json()["data"]["items"]
nid, tok = items[0]["id"], items[0]["xsec_token"]     # token 在 item 级，不在 note_card 里

note = c.feed(nid, tok).json()
uid = note["data"]["items"][0]["note_card"]["user"]["user_id"]
profile = c.user(uid).json()
his_notes = c.user_notes(uid, num=30).json()
first_page = c.comments(nid, tok).json()
```

翻页：

```python
for page, items in c.search_pages("咖啡", max_pages=3):
    print(page, len(items))

for notes in c.user_note_pages(uid, max_pages=2):
    print(len(notes))
```

## 4. 只采作者（复用已有 notes/comments）

```bash
# 假设 ./out 里已有 notes.jsonl
xhs collect authors --out ./out --limit 50 --with-notes --max-author-notes 2
```

## 5. 切成合成指纹（副号场景）

```bash
XHS_FP_MODE=synthetic xhs collect run --keyword 咖啡 --pages 2 --out ./out-burner
```

首次会自动生成并持久化一份合成指纹（`~/.local/share/xhs/synthetic_fingerprint.json`），
之后每次都用同一份。**主号不要这么干**，见 [../docs/risk-control.md](../docs/risk-control.md)。
