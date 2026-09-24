"""统一命令行入口（由 bin/xhs 调用，通常不直接使用）。

    xhs search|feed|comments|user|usernotes ...   -> client 子命令
    xhs collect [search|enrich|comments|authors|run] ...  -> 批量采集器
"""
import sys

USAGE = """red-search 命令：

  search <关键词> [N] [选项]      搜索笔记（N=条数，默认20；筛选见 xhs search --help）
  suggest <关键词>              搜索联想词（下拉推荐）
  filters <关键词>              当前可用的筛选项（服务端动态下发）
  feed <note_id> <xsec_token>    笔记详情
  comments <note_id> <xsec_token>  评论
  user <user_id>                 作者主页
  usernotes <user_id> [N]        作者已发布笔记
  collect <子命令> ...           批量采集（suggest/search/enrich/comments/authors/run）
  stats <notes.jsonl|目录>       量化统计（均赞/中位/最高/近90天占比/Top5）
  verify [--quick]              运行时自检：签名/端点/筛选是否仍可用（会发真实请求）

搜索筛选：--sort general|latest|likes|comments|collects
          --time day|week|half_year  --type video|image
          --scope seen|unseen|followed  --location city|nearby  --hot <城市词>

环境变量：XHS_FP_MODE=auto|real|synthetic，XHS_COOKIE_FILE，XHS_STATE_DIR
"""

API_CMDS = {"search", "suggest", "filters", "feed", "comments", "user", "usernotes"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE, end="")
        return 0

    cmd, rest = argv[0], argv[1:]

    if cmd in API_CMDS:
        from . import client
        sys.argv = ["xhs", cmd] + rest
        return client.main()

    if cmd == "verify":
        from . import verify
        return verify.main(rest)

    if cmd == "stats":
        from . import stats
        return stats.main(rest)

    if cmd == "collect":
        from . import collect
        if not rest:
            print("用法: xhs collect {search|enrich|comments|authors|run} [选项]", file=sys.stderr)
            return 1
        return collect.main(rest)

    print(f"未知命令: {cmd}", file=sys.stderr)
    print(USAGE, end="", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
