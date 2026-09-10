"""运行时自检：验证签名与各端点/筛选是否仍然可用。

⚠️ 本命令会发起真实请求（约 30–60 次，视 --quick 而定）。请用低频率、非主号使用。
小红书改版后（签名或筛选失效）跑一遍即可定位坏在哪一环。

    xhs verify            # 全量
    xhs verify --quick    # 精简（约 15 次请求，跳过时间窗抽查）
"""
import argparse
import sys
import time

from .client import XhsClient, build_filters
from .collect import is_real_note_id

SORTS = ["general", "time_descending", "popularity_descending",
         "comment_descending", "collect_descending"]
TIME_LIM = {"day": 1, "week": 7, "half_year": 183}
KW = "咖啡"


class Verifier:
    def __init__(self, quick=False):
        self.c = XhsClient(throttle=1.5, jitter=0.4)
        self.quick = quick
        self.passed = []
        self.failed = []

    def check(self, name, cond, detail=""):
        (self.passed if cond else self.failed).append(name)
        print(f"  {'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))

    # ---- 原语 ----
    def probe(self, **kw):
        sort = kw.pop("sort", "general")
        filters = kw.pop("filters", [])
        body = {"keyword": KW, "page": 1, "page_size": 20,
                "search_id": self.c.client.get_search_id(), "sort": sort, "note_type": 0,
                "ext_flags": [], "filters": filters,
                "image_formats": ["jpg", "webp", "avif"], "need_filter_image": False}
        r = self.c.post("/api/sns/web/v1/search/notes", body)
        j = r.json()
        items = (j.get("data") or {}).get("items") or []
        likes = []
        for it in items:
            v = ((it.get("note_card") or {}).get("interact_info") or {}).get("liked_count")
            try:
                likes.append(int(v))
            except Exception:
                pass
        return {"http": r.status_code, "ok": bool(j.get("success")), "items": items,
                "ids": [i.get("id") for i in items if i.get("id")],
                "types": [((i.get("note_card") or {}).get("type")) for i in items],
                "mean": round(sum(likes) / len(likes), 1) if likes else None}

    @staticmethod
    def overlap(a, b):
        sa, sb = set(a), set(b)
        return len(sa & sb) / max(1, min(len(sa), len(sb)))

    def age_days(self, items, n=8):
        out = []
        for it in items[:n]:
            # 搜索结果混有直播/AI 占位条目（非 24 位 hex id），喂给 feed 会报 461
            if not it.get("xsec_token") or not is_real_note_id(it.get("id")):
                continue
            try:
                nc = (((self.c.feed(it["id"], it["xsec_token"]).json().get("data")
                        or {}).get("items") or [{}])[0].get("note_card") or {})
                if nc.get("time"):
                    out.append(round((time.time() * 1000 - int(nc["time"])) / 86400000, 2))
            except Exception:
                pass
        return out

    # ---- 各段 ----
    def run(self):
        c = self.c
        print("① 签名 / 基础连通")
        words = c.suggestions(KW)
        self.check("suggest() 联想词", len(words) >= 5, f"n={len(words)}")
        base = self.probe()
        self.check("search() 基础搜索", base["ok"] and len(base["items"]) >= 10, f"n={len(base['items'])}")
        if not base["items"]:
            print("\n签名可能已失效，后续跳过。")
            return self.report()
        first = next((i for i in base["items"] if i.get("xsec_token")), None)
        nid, tok = first["id"], first["xsec_token"]
        self.check("item 级 xsec_token", len(tok) >= 40, f"len={len(tok)}")

        print("①b 筛选面板定义（服务端下发）")
        opts = c.filter_options(KW)
        self.check("filter_options() 拉到面板", bool(opts.get("sort_type", {}).get("tags")),
                   f"组数={len(opts)}")
        self.check("面板含全部 6 组",
                   {"sort_type", "filter_note_type", "filter_note_time",
                    "filter_note_range", "filter_pos_distance", "filter_hot"} <= set(opts),
                   f"{sorted(opts)}")

        print("①c 包导出面 + CLI 参数校验（离线）")
        try:
            from . import build_filters as _bf, SORT_MAP as _sm   # noqa: F401
            from .client import parse_search_args as _psa
            self.check("包根可导入 build_filters/SORT_MAP", True, "")
            bad_rejected = False
            try:
                _psa(["kw", "--sort", "hot"])
            except SystemExit:
                bad_rejected = True
            self.check("非法 --sort 被本地拒绝", bad_rejected,
                       "服务端会静默忽略，必须本地拦")
        except Exception as e:
            self.check("包导出面", False, f"{type(e).__name__}: {e}")

        print("② sort 枚举（必须 5 个各不相同）")
        means = {}
        for s in SORTS:
            r = self.probe(sort=s)
            ov = self.overlap(base["ids"], r["ids"]) if s != "general" else 1.0
            means[s] = r["mean"]
            flag = ov > 0.95 and s != "general"
            self.check(f"sort={s}", r["ok"] and not flag,
                       f"n={len(r['items'])} mean={r['mean']} vs general 重叠={ov:.0%}")

        print("③ 筛选：type（客观断言）")
        for t, expect in [("video", "video"), ("image", "normal")]:
            r = self.probe(filters=build_filters(note_type=t))
            kinds = {x for x in r["types"] if x}
            self.check(f"type={t}", bool(kinds) and kinds.issubset({expect}), f"返回类型={kinds}")

        print("④ 筛选：time" + ("（--quick 跳过）" if self.quick else "（客观抽查发布时间）"))
        if not self.quick:
            ages = {}
            for t in ["day", "week", "half_year"]:
                r = self.probe(sort="popularity_descending", filters=build_filters(time=t))
                a = self.age_days(r["items"])
                ages[t] = a
                ok = bool(a) and max(a) <= TIME_LIM[t] + 0.7
                self.check(f"time={t} 全在窗口内", ok,
                           f"max={max(a) if a else '-'}天 / 上限{TIME_LIM[t]}")
            self.check("time 分档可区分（week 有 >1 天样本）",
                       any(x > 1 for x in ages.get("week", [])),
                       f"week样本={ages.get('week')}")
            self.check("time 分档可区分（half_year 有 >7 天样本）",
                       any(x > 7 for x in ages.get("half_year", [])),
                       f"half样本={ages.get('half_year')}")

        print("⑤ 筛选：scope / location")
        for sc in ["seen", "unseen", "followed"]:
            r = self.probe(filters=build_filters(scope=sc))
            ov = self.overlap(base["ids"], r["ids"])
            self.check(f"scope={sc}", r["ok"] and (ov < 0.95 or sc == "unseen"),
                       f"n={len(r['items'])} 重叠={ov:.0%}")
        for loc in ["city", "nearby"]:
            r = self.probe(filters=build_filters(location=loc))
            ov = self.overlap(base["ids"], r["ids"])
            self.check(f"location={loc}", r["ok"] and ov < 0.95,
                       f"n={len(r['items'])} 重叠={ov:.0%}")

        print("⑥ 组合筛选")
        r = self.probe(sort="likes", filters=build_filters(time="week", note_type="image", location="city"))
        self.check("time+type+location+sort 组合", r["ok"] and len(r["items"]) > 0, f"n={len(r['items'])}")

        print("⑦ 详情 / 评论 / 作者")
        nc = (((c.feed(nid, tok).json().get("data") or {}).get("items") or [{}])[0]
              .get("note_card") or {})
        self.check("feed()", bool(nc.get("title") or nc.get("desc")) and bool(nc.get("time")))
        cs = ((c.comments(nid, tok).json().get("data") or {}).get("comments") or [])
        self.check("comments()", len(cs) > 0, f"n={len(cs)}")
        sub = next((x for x in cs if x.get("sub_comment_count") or x.get("sub_comments")), None)
        if sub:
            ss = ((c.sub_comments(nid, sub["id"], tok).json().get("data") or {}).get("comments") or [])
            self.check("sub_comments()", len(ss) > 0, f"n={len(ss)}")
        uid = (nc.get("user") or {}).get("user_id")
        d = c.user(uid).json().get("data") or {}
        self.check("user() 主页", bool((d.get("basic_info") or {}).get("nickname")),
                   f"{(d.get('basic_info') or {}).get('nickname')}")
        un = (c.user_notes(uid, num=10).json().get("data") or {}).get("notes") or []
        self.check("user_notes() 作品", len(un) > 0 and bool(un[0].get("xsec_token")), f"n={len(un)}")
        self.check("user_posted 分页 token", bool(un and un[0].get("note_id")))

        print("⑧ 错误处理")
        bad = c.feed(nid, "INVALID_TOKEN_XXXX").json()
        self.check("坏 token 返回业务错误码", bad.get("success") is False or bad.get("code") not in (None, 0),
                   f"code={bad.get('code')}")
        bad2 = c.get("/api/sns/web/v1/user/otherinfo", {"target_user_id": "not_a_real_user"}).json()
        self.check("坏 user_id 不崩溃", isinstance(bad2, dict), f"code={bad2.get('code')}")

        return self.report()

    def report(self):
        c = self.c
        print(f"\n请求 {c.request_count} 次 ｜ 累计异常 {c.error_count} 次")
        print(f"通过 {len(self.passed)} ｜ 失败 {len(self.failed)}")
        if self.failed:
            print("\n失败项：")
            for f in self.failed:
                print("  -", f)
        return 0 if not self.failed else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="xhs-scraper 运行时自检（会发起真实请求）")
    p.add_argument("--quick", action="store_true", help="精简模式（跳过时间窗抽查）")
    args = p.parse_args(argv)
    print("xhs-scraper 运行时自检\n" + "=" * 60)
    return Verifier(quick=args.quick).run()


if __name__ == "__main__":
    sys.exit(main())
