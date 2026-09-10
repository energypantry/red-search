#!/usr/bin/env python3
"""
xhs_collect.py — 小红书批量采集器（纯算签名，无需浏览器在线）

输出 JSONL（可断点续采）：搜索 → 笔记详情 → 评论（含二级） → 作者主页，四段可独立或串联执行。

示例:
  # 搜关键词，只要列表
  python3 xhs_collect.py search --keyword 咖啡 --keyword 手冲 --pages 2 --out ./out

  # 全链路：搜索 + 详情 + 评论 + 作者主页
  python3 xhs_collect.py run --keyword 咖啡 --pages 3 --max-notes 50 \
      --comments --authors --author-notes --out ./out --throttle 2.5

  # 断点续采：重跑同一条命令即可，已采过的 id 会自动跳过
  python3 xhs_collect.py run --keyword 咖啡 --pages 3 --out ./out

风险缓解（默认开启）:
  - 设备指纹固定化（进程内复用；若存在 device_fingerprint.json 则用真机指纹）
  - 会话状态复用 + 请求节流 + 抖动
  - 连续异常自动指数退避，5 次熔断
默认节奏偏保守（throttle=2.5s, jitter=1.0s）。批量任务请自评风险后再调低。

注意:
  - 采集结果仅用于你有权处理的数据；遵守目标站条款与当地法律。
  - xsec_token 会过期：断点续采时若详情报 461/300031，重新跑 search 段刷新 token。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from .client import XhsClient, XhsBlockedError  # noqa: E402


# ---------------- 工具 ----------------
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg, quiet=False):
    if not quiet:
        print(f"[{now()}] {msg}", flush=True)


def read_jsonl(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def seen_note_ids(path):
    return {r["note_id"] for r in read_jsonl(path) if r.get("note_id")}


def seen_comment_ids(path):
    return {r["comment_id"] for r in read_jsonl(path) if r.get("comment_id")}


def append_jsonl(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def is_real_note_id(nid):
    """真实笔记 id 是 24 位 hex；搜索结果里混有 UUID/直播等占位条目。"""
    return isinstance(nid, str) and len(nid) == 24 and all(c in "0123456789abcdef" for c in nid.lower())


def note_record(keyword, it):
    nc = it.get("note_card") or {}
    ii = nc.get("interact_info") or {}
    user = nc.get("user") or {}
    def num(v):
        try:
            return int(v)
        except Exception:
            return None
    return {
        "note_id": it.get("id"),
        "xsec_token": it.get("xsec_token"),
        "keyword": keyword,
        "title": nc.get("title") or nc.get("display_title"),
        "desc": None,                      # 详情段填充
        "note_type": nc.get("type"),
        "user_id": user.get("user_id"),
        "nickname": user.get("nickname"),
        "liked_count": num(ii.get("liked_count")),
        "collected_count": num(ii.get("collected_count")),
        "comment_count": num(ii.get("comment_count")),
        "cover": (nc.get("cover") or {}).get("url_default"),
        "detail": False,
        "comments_done": False,
        "collected_at": now(),
    }


def merge_detail(rec, nc):
    ii = nc.get("interact_info") or {}
    rec.update({
        "title": nc.get("title") or rec.get("title"),
        "desc": nc.get("desc"),
        "note_type": nc.get("type") or rec.get("note_type"),
        "liked_count": ii.get("liked_count") or rec.get("liked_count"),
        "collected_count": ii.get("collected_count") or rec.get("collected_count"),
        "comment_count": ii.get("comment_count") or rec.get("comment_count"),
        "image_count": len(nc.get("image_list") or []),
        "images": [i.get("url_default") for i in (nc.get("image_list") or [])][:20],
        "tags": [t.get("name") for t in (nc.get("tag_list") or [])][:20],
        "publish_time": nc.get("time"),
        "ip_location": nc.get("ip_location"),
        "detail": True,
    })
    return rec


def comment_record(note_id, c, parent_id=None):
    user = c.get("user_info") or {}
    return {
        "comment_id": c.get("id"),
        "note_id": note_id,
        "parent_id": parent_id,
        "content": c.get("content"),
        "like_count": c.get("like_count"),
        "user_id": user.get("user_id"),
        "nickname": user.get("nickname"),
        "create_time": c.get("create_time"),
        "sub_comment_count": c.get("sub_comment_count"),
        "collected_at": now(),
    }


# ---------------- 采集段 ----------------
def do_search(c, keywords, pages, page_size, sort, out_dir, quiet=False):
    path = os.path.join(out_dir, "notes.jsonl")
    have = seen_note_ids(path)
    added = 0
    for kw in keywords:
        for page, items in c.search_pages(kw, max_pages=pages, page_size=page_size, sort=sort):
            for it in items:
                nid = it.get("id")
                if not nid or nid in have:
                    continue
                if not is_real_note_id(nid) or not (it.get("note_card") or {}):
                    continue          # 跳过直播/AI 占位等非笔记条目
                append_jsonl(path, note_record(kw, it))
                have.add(nid)
                added += 1
            log(f"search '{kw}' p{page}: +{len(items)} 条 (累计新增 {added})", quiet)
    log(f"搜索段完成，新增 {added} 条 -> {path}", quiet)
    return added


def do_enrich(c, out_dir, limit=None, quiet=False, min_likes=None):
    path = os.path.join(out_dir, "notes.jsonl")
    todo = [r for r in read_jsonl(path) if not r.get("detail")]
    if min_likes is not None:
        todo = [r for r in todo if (r.get("liked_count") or 0) >= min_likes]
    if limit:
        todo = todo[:limit]
    if not todo:
        log("详情段：无需采集", quiet)
        return 0
    done = 0
    for r in todo:
        try:
            j = c.feed(r["note_id"], r["xsec_token"]).json()
        except XhsBlockedError as e:
            log(f"熔断，停止详情段：{e}", quiet)
            break
        nc = ((j.get("data") or {}).get("items") or [{}])[0].get("note_card")
        if not nc:
            log(f"  详情失败 note={r['note_id']} code={j.get('code')}", quiet)
            continue
        merge_detail(r, nc)
        _rewrite(path, todo_ids={r["note_id"]}, new=r)
        done += 1
        if done % 10 == 0:
            log(f"  详情 {done}/{len(todo)}", quiet)
    log(f"详情段完成，成功 {done} 条", quiet)
    return done


def do_comments(c, out_dir, limit=None, max_pages=2, quiet=False, min_likes=None):
    npath = os.path.join(out_dir, "notes.jsonl")
    cpath = os.path.join(out_dir, "comments.jsonl")
    have_c = seen_comment_ids(cpath)
    notes = [r for r in read_jsonl(npath) if not r.get("comments_done")]
    if min_likes is not None:
        notes = [r for r in notes if (r.get("liked_count") or 0) >= min_likes]
    if limit:
        notes = notes[:limit]
    total = 0
    for idx, r in enumerate(notes, 1):
        nid, tok = r["note_id"], r["xsec_token"]
        cnt = 0
        try:
            for page_cs in c.comment_pages(nid, tok, max_pages=max_pages):
                for cm in page_cs:
                    cid = cm.get("id")
                    if cid in have_c:
                        continue
                    append_jsonl(cpath, comment_record(nid, cm))
                    have_c.add(cid)
                    cnt += 1
                    for sub in (cm.get("sub_comments") or []):
                        sid = sub.get("id")
                        if sid and sid not in have_c:
                            append_jsonl(cpath, comment_record(nid, sub, parent_id=cid))
                            have_c.add(sid)
                            cnt += 1
        except XhsBlockedError as e:
            log(f"熔断，停止评论段：{e}", quiet)
            break
        _mark(npath, nid, "comments_done")
        total += cnt
        if idx % 5 == 0:
            log(f"  评论 {idx}/{len(notes)}（累计 {total} 条）", quiet)
    log(f"评论段完成，新增 {total} 条 -> {cpath}", quiet)
    return total


def user_record(user_id, data, sources):
    bi = (data or {}).get("basic_info") or {}
    inter = {x.get("type"): x.get("count") for x in ((data or {}).get("interactions") or [])}
    def num(v):
        try:
            return int(v)
        except Exception:
            return None
    return {
        "user_id": user_id,
        "nickname": bi.get("nickname"),
        "red_id": bi.get("red_id"),
        "gender": bi.get("gender"),
        "ip_location": bi.get("ip_location"),
        "desc": bi.get("desc"),
        "avatar": bi.get("images") or bi.get("imageb"),
        "follows": num(inter.get("follows")),
        "fans": num(inter.get("fans")),
        "interaction": num(inter.get("interaction")),
        "tags": [t.get("name") for t in ((data or {}).get("tags") or [])],
        "sources": sorted(sources),
        "collected_at": now(),
    }


# ---------------- 作者主页段 ----------------
def collect_user_ids(npath, cpath):
    """从笔记 + 评论里汇总 user_id -> 来源集合。"""
    out = {}
    for r in read_jsonl(npath):
        if r.get("user_id"):
            out.setdefault(r["user_id"], set()).add("note_author")
    for r in read_jsonl(cpath):
        if r.get("user_id"):
            out.setdefault(r["user_id"], set()).add("comment_author")
    return out


def do_authors(c, out_dir, limit=None, with_notes=False, max_author_notes=1,
               quiet=False, min_likes=None):
    npath = os.path.join(out_dir, "notes.jsonl")
    cpath = os.path.join(out_dir, "comments.jsonl")
    upath = os.path.join(out_dir, "users.jsonl")
    unpath = os.path.join(out_dir, "user_notes.jsonl")

    ids = collect_user_ids(npath, cpath)
    if not ids:
        log("作者段：未找到 user_id（先跑 search/comments）", quiet)
        return 0

    have = {r["user_id"] for r in read_jsonl(upath) if r.get("user_id")}
    todo = [(uid, src) for uid, src in ids.items() if uid not in have]
    if min_likes is not None:
        keep = {r.get("user_id") for r in read_jsonl(npath)
                if (r.get("liked_count") or 0) >= min_likes}
        todo = [(u, s) for u, s in todo if u in keep]
    if limit:
        todo = todo[:limit]
    if not todo:
        log("作者段：无新增", quiet)
        return 0

    have_notes = {r["note_id"] for r in read_jsonl(unpath) if r.get("note_id")}
    done = 0
    for idx, (uid, src) in enumerate(todo, 1):
        try:
            r = c.user(uid).json()
        except XhsBlockedError as e:
            log(f"熔断，停止作者段：{e}", quiet)
            break
        except Exception as e:
            log(f"  作者失败 {uid}: {type(e).__name__}", quiet)
            continue
        d = r.get("data")
        if not d:
            log(f"  作者无数据 {uid} code={r.get('code')}", quiet)
            continue
        append_jsonl(upath, user_record(uid, d, src))
        done += 1

        if with_notes and max_author_notes > 0:
            try:
                for notes in c.user_note_pages(uid, max_pages=max_author_notes):
                    for n in notes:
                        nid = n.get("note_id")
                        if not nid or nid in have_notes:
                            continue
                        ii = n.get("interact_info") or {}
                        append_jsonl(unpath, {
                            "note_id": nid,
                            "xsec_token": n.get("xsec_token"),
                            "user_id": uid,
                            "title": n.get("display_title"),
                            "note_type": n.get("type"),
                            "publish_time": n.get("time"),
                            "liked_count": ii.get("liked_count"),
                            "collected_at": now(),
                        })
                        have_notes.add(nid)
            except XhsBlockedError:
                raise
            except Exception as e:
                log(f"  作者笔记失败 {uid}: {type(e).__name__}", quiet)

        if idx % 5 == 0:
            log(f"  作者 {idx}/{len(todo)}（成功 {done}）", quiet)
    log(f"作者段完成，新增 {done} 条 -> {upath}", quiet)
    return done


# ---------------- notes.jsonl 就地更新 ----------------
def _rewrite(path, todo_ids, new):
    """把 todo_ids 中指定 note_id 的记录替换为 new（其余原样保留）。"""
    tmp = path + ".tmp"
    with open(path, encoding="utf-8") as fin, open(tmp, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                fout.write(line + "\n")
                continue
            if rec.get("note_id") in todo_ids:
                fout.write(json.dumps(new, ensure_ascii=False) + "\n")
            else:
                fout.write(line + "\n")
    os.replace(tmp, path)


def _mark(path, note_id, field):
    tmp = path + ".tmp"
    with open(path, encoding="utf-8") as fin, open(tmp, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                fout.write(line + "\n")
                continue
            if rec.get("note_id") == note_id:
                rec[field] = True
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


# ---------------- CLI ----------------
def build_parser():
    p = argparse.ArgumentParser(description="小红书批量采集器（纯算签名）",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--out", default="./xhs-out", help="输出目录（默认 ./xhs-out）")
        sp.add_argument("--throttle", type=float, default=2.5, help="请求最小间隔秒（默认 2.5）")
        sp.add_argument("--jitter", type=float, default=1.0, help="额外随机抖动上限秒（默认 1.0）")
        sp.add_argument("--cookie-file", default=None, help="cookies JSON 路径")
        sp.add_argument("--min-likes", type=int, default=None, help="仅处理点赞数 >= N 的笔记")
        sp.add_argument("--quiet", action="store_true")

    sp = sub.add_parser("search", help="搜索关键词，写 notes.jsonl")
    common(sp)
    sp.add_argument("--keyword", action="append", required=True, help="可多次传入")
    sp.add_argument("--pages", type=int, default=1, help="每个词采集页数（默认 1）")
    sp.add_argument("--page-size", type=int, default=20)
    sp.add_argument("--sort", default="general",
                    choices=["general", "latest", "likes", "comments", "collects"])

    sp = sub.add_parser("enrich", help="对 notes.jsonl 中未采详情的笔记抓详情")
    common(sp)
    sp.add_argument("--limit", type=int, default=None, help="本次最多处理多少条")

    sp = sub.add_parser("comments", help="对 notes.jsonl 中未采评论的笔记抓评论")
    common(sp)
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--max-pages", type=int, default=2, help="每条笔记最多翻几页（默认 2）")

    sp = sub.add_parser("authors", help="抓作者主页（笔记/评论里出现的 user_id）")
    common(sp)
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--with-notes", action="store_true", help="同时抓作者已发布笔记")
    sp.add_argument("--max-author-notes", type=int, default=1, help="每个作者翻几页笔记（默认 1）")

    sp = sub.add_parser("run", help="全链路：search → enrich → comments")
    common(sp)
    sp.add_argument("--keyword", action="append", required=True)
    sp.add_argument("--pages", type=int, default=1)
    sp.add_argument("--page-size", type=int, default=20)
    sp.add_argument("--sort", default="general",
                    choices=["general", "latest", "likes", "comments", "collects"])
    sp.add_argument("--max-notes", type=int, default=None, help="本次最多采多少条详情")
    sp.add_argument("--comments", action="store_true", help="是否抓评论")
    sp.add_argument("--max-comment-pages", type=int, default=2)
    sp.add_argument("--comment-notes", type=int, default=None, help="本次最多对多少条笔记抓评论")
    sp.add_argument("--authors", action="store_true", help="是否抓作者主页")
    sp.add_argument("--author-limit", type=int, default=None)
    sp.add_argument("--author-notes", action="store_true", help="作者段同时抓其已发布笔记")
    sp.add_argument("--max-author-notes", type=int, default=1)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    c = XhsClient(throttle=args.throttle, jitter=args.jitter,
                  cookies=(json.load(open(args.cookie_file)) if args.cookie_file else None),
                  verbose=not args.quiet)
    log(f"指纹模式: {c.fp_mode} | UA: {c.ua[:58]}..."
        f" | 节流 {args.throttle}s + 抖动 {args.jitter}s", args.quiet)
    try:
        if args.cmd == "search":
            do_search(c, args.keyword, args.pages, args.page_size, args.sort, args.out, args.quiet)
        elif args.cmd == "enrich":
            do_enrich(c, args.out, limit=args.limit, quiet=args.quiet, min_likes=args.min_likes)
        elif args.cmd == "comments":
            do_comments(c, args.out, limit=args.limit, max_pages=args.max_pages,
                        quiet=args.quiet, min_likes=args.min_likes)
        elif args.cmd == "authors":
            do_authors(c, args.out, limit=args.limit, with_notes=args.with_notes,
                       max_author_notes=args.max_author_notes, quiet=args.quiet,
                       min_likes=args.min_likes)
        elif args.cmd == "run":
            do_search(c, args.keyword, args.pages, args.page_size, args.sort, args.out, args.quiet)
            do_enrich(c, args.out, limit=args.max_notes, quiet=args.quiet, min_likes=args.min_likes)
            if args.comments:
                do_comments(c, args.out, limit=args.comment_notes,
                            max_pages=args.max_comment_pages, quiet=args.quiet,
                            min_likes=args.min_likes)
            if args.authors:
                do_authors(c, args.out, limit=args.author_limit, with_notes=args.author_notes,
                           max_author_notes=args.max_author_notes, quiet=args.quiet,
                           min_likes=args.min_likes)
    except XhsBlockedError as e:
        log(f"已熔断: {e}", args.quiet)
        return 2
    except KeyboardInterrupt:
        log("用户中断（已采集部分已落盘，可重跑续采）", args.quiet)
        return 130
    log(f"完成。请求 {c.request_count} 次 / 异常 {c.error_count} 次", args.quiet)
    log(f"产物: {os.path.join(args.out, 'notes.jsonl')}", args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
