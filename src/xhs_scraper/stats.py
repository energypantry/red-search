"""关键词/笔记统计分析（替代浏览器路线的 xhs_keyword_stats.py）。

输入：`xhs collect` 产出的 notes.jsonl（或任意含 note 记录的 JSONL / 目录）。
输出：命中数、均赞、最高赞、中位赞、发布时间分布、Top N 帖。
"""
import json
import os
import statistics
import sys
from datetime import datetime, timedelta


def _iter_notes(path):
    if os.path.isdir(path):
        path = os.path.join(path, "notes.jsonl")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _ts(v):
    """发布/采集时间统一成毫秒时间戳。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if v > 1e11 else int(v * 1000)
    if isinstance(v, str):
        if v.isdigit():
            n = int(v)
            return n if n > 1e11 else n * 1000
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return int(datetime.strptime(v[:19], fmt).timestamp() * 1000)
            except Exception:
                continue
    return None


def compute(path, top_n=5, recent_days=90):
    rows = list(_iter_notes(path))
    likes = [n for n in (_num(r.get("liked_count")) for r in rows) if n is not None]
    if not likes:
        return {"total": len(rows), "with_likes": 0}
    cutoff = int((datetime.now() - timedelta(days=recent_days)).timestamp() * 1000)
    times = [t for t in (_ts(r.get("publish_time")) for r in rows) if t]
    recent = sum(1 for t in times if t >= cutoff) if times else 0
    ranked = sorted(rows, key=lambda r: _num(r.get("liked_count")) or 0, reverse=True)
    return {
        "total": len(rows),
        "with_likes": len(likes),
        "mean_likes": round(statistics.mean(likes), 1),
        "median_likes": statistics.median(likes),
        "max_likes": max(likes),
        "min_likes": min(likes),
        "recent_days": recent_days,
        "recent_ratio": round(recent / len(times), 3) if times else None,
        "dated": len(times),
        "top": [
            {
                "note_id": r.get("note_id"),
                "title": r.get("title"),
                "likes": _num(r.get("liked_count")),
                "url": f"https://www.xiaohongshu.com/explore/{r.get('note_id')}",
            }
            for r in ranked[:top_n]
        ],
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 1
    path = argv[0]
    if not os.path.exists(path):
        print(f"找不到: {path}", file=sys.stderr)
        return 1
    res = compute(path)
    if not res.get("with_likes"):
        print(f"共 {res['total']} 条，但没有任何 liked_count（先跑 `xhs collect enrich`）")
        return 0
    print(f"命中数      : {res['total']}")
    print(f"均赞        : {res['mean_likes']}")
    print(f"中位赞      : {res['median_likes']}")
    print(f"最高/最低   : {res['max_likes']} / {res['min_likes']}")
    if res.get("recent_ratio") is not None:
        print(f"近{res['recent_days']}天占比 : {res['recent_ratio']:.1%}  （{res['dated']} 条带时间）")
    else:
        print(f"近{res['recent_days']}天占比 : 无时间字段（先跑 `xhs collect enrich`）")
    print("\nTop 帖：")
    for i, t in enumerate(res["top"], 1):
        print(f"  {i}. [{t['likes']:>6}] {str(t['title'])[:44]:46} {t['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
