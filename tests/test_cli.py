"""xhs search 的参数解析与筛选校验（纯离线）。

背景：服务端对非法的 sort/filters 取值**静默忽略**——传 `--sort hot` 会返回 200
但实际退化成"综合"，看不出任何异常。所以 CLI 必须本地校验，这些测试就是锁住
"非法值报错而不是悄悄放过"这个契约。
"""
import pytest

from xhs_scraper.client import parse_search_args, build_filters
from xhs_scraper import (SORT_MAP, TIME_MAP, TYPE_MAP, SCOPE_MAP,  # noqa: F401
                         LOCATION_MAP, build_filters as bf_export)


# ---------- 基本解析 ----------

def test_keyword_only():
    kw, n, opts = parse_search_args(["咖啡"])
    assert (kw, n, opts) == ("咖啡", 20, {})


def test_keyword_and_count():
    kw, n, opts = parse_search_args(["青岛房东直租", "40"])
    assert (kw, n, opts) == ("青岛房东直租", 40, {})


def test_all_filters():
    kw, n, o = parse_search_args(
        ["咖啡", "60", "--sort", "likes", "--time", "week",
         "--type", "video", "--scope", "unseen", "--location", "city"])
    assert kw == "咖啡" and n == 60
    assert o == {"sort": "likes", "time": "week", "type": "video",
                 "scope": "unseen", "location": "city"}


def test_flags_before_keyword_and_hot():
    kw, n, o = parse_search_args(["--time", "day", "露营", "--hot", "青岛"])
    assert kw == "露营" and n == 20
    assert o == {"time": "day", "hot": "青岛"}


# ---------- 非法取值必须报错（核心契约）----------

@pytest.mark.parametrize("flag, bad", [
    ("--sort", "hot"),          # 服务端枚举是 popularity_descending，不是 hot
    ("--sort", "time_descending"),
    ("--time", "yesterday"),
    ("--time", "month"),
    ("--type", "text"),
    ("--scope", "liked"),
    ("--location", "district"),
])
def test_invalid_value_rejected(flag, bad):
    with pytest.raises(SystemExit) as e:
        parse_search_args(["咖啡", flag, bad])
    msg = str(e.value)
    assert "取值非法" in msg and bad in msg
    assert "允许" in msg          # 报错里要给出可选项


def test_unknown_flag_rejected():
    with pytest.raises(SystemExit):
        parse_search_args(["咖啡", "--colour", "red"])


def test_missing_value_rejected():
    with pytest.raises(SystemExit):
        parse_search_args(["咖啡", "--time"])


def test_no_keyword_shows_usage():
    with pytest.raises(SystemExit):
        parse_search_args(["--time", "week"])


def test_extra_positional_rejected():
    with pytest.raises(SystemExit):
        parse_search_args(["咖啡", "20", "30"])


# ---------- any/不限 语义 ----------

@pytest.mark.parametrize("val", ["any", "不限", "全部", ""])
def test_any_means_no_filter(val):
    _, _, o = parse_search_args(["咖啡", "--time", val])
    assert "time" not in o
    assert build_filters(time=o.get("time")) == []


# ---------- 映射后确实是服务端枚举 ----------

def test_filters_map_to_server_tags():
    f = build_filters(time="week", note_type="video", scope="unseen",
                      location="city", hot="青岛")
    assert {"type": "filter_note_time", "tags": ["一周内"]} in f
    assert {"type": "filter_note_type", "tags": ["视频笔记"]} in f
    assert {"type": "filter_note_range", "tags": ["未看过"]} in f
    assert {"type": "filter_pos_distance", "tags": ["同城"]} in f
    assert {"type": "filter_hot", "tags": ["青岛"]} in f
    assert len(f) == 5


def test_invalid_value_in_build_filters_is_dropped():
    """库层对非法值静默丢弃（CLI 层负责拦），保证不会发脏 tag 给服务端。"""
    assert build_filters(time="nonsense") == []


# ---------- 导出面 ----------

def test_public_exports_match_internal():
    assert bf_export is build_filters
    assert SORT_MAP["likes"] == "popularity_descending"
    assert TIME_MAP["week"] == "一周内"
    assert TYPE_MAP["video"] == "视频笔记"
    assert SCOPE_MAP["followed"] == "已关注"
    assert LOCATION_MAP["nearby"] == "附近"
