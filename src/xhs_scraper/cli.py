"""统一命令行入口（由 bin/xhs 调用，通常不直接使用）。

    xhs search|feed|comments|user|usernotes ...   -> client 子命令
    xhs collect [search|enrich|comments|authors|run] ...  -> 批量采集器
"""
import sys

USAGE = """xhs-scraper 命令：

  search <关键词> [N]            搜索笔记
  suggest <关键词>              搜索联想词（下拉推荐）
  feed <note_id> <xsec_token>    笔记详情
  comments <note_id> <xsec_token>  评论
  user <user_id>                 作者主页
  usernotes <user_id> [N]        作者已发布笔记
  collect <子命令> ...           批量采集（search/enrich/comments/authors/run）

环境变量：XHS_FP_MODE=auto|real|synthetic，XHS_COOKIE_FILE，XHS_STATE_DIR
"""

API_CMDS = {"search", "suggest", "feed", "comments", "user", "usernotes"}


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
