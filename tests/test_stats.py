"""离线测试：stats 统计模块。"""
import json

from xhs_scraper.stats import compute


def _write(tmp_path, rows):
    p = tmp_path / "notes.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(p)


def test_compute_basic(tmp_path):
    path = _write(tmp_path, [
        {"note_id": "a" * 24, "title": "t1", "liked_count": "100", "publish_time": "1780000000000"},
        {"note_id": "b" * 24, "title": "t2", "liked_count": 300, "publish_time": 1780000000},
        {"note_id": "c" * 24, "title": "t3", "liked_count": None},
    ])
    res = compute(path, top_n=2)
    assert res["total"] == 3
    assert res["with_likes"] == 2
    assert res["mean_likes"] == 200.0
    assert res["median_likes"] == 200
    assert res["max_likes"] == 300
    assert len(res["top"]) == 2
    assert res["top"][0]["likes"] == 300          # 降序
    assert res["top"][0]["url"].endswith("b" * 24)


def test_compute_handles_seconds_and_millis(tmp_path):
    """publish_time 有秒和毫秒两种单位，都要能解析。"""
    path = _write(tmp_path, [
        {"note_id": "a" * 24, "liked_count": 1, "publish_time": 1780000000},        # 秒
        {"note_id": "b" * 24, "liked_count": 1, "publish_time": "1780000000000"},    # 毫秒字符串
    ])
    res = compute(path)
    assert res["dated"] == 2


def test_compute_empty(tmp_path):
    path = _write(tmp_path, [{"note_id": "a" * 24, "title": "x"}])
    res = compute(path)
    assert res["total"] == 1
    assert "with_likes" in res and res["with_likes"] == 0


# ---------- verify 模块（离线部分）----------

def test_verifier_report_exit_codes():
    """自检的退出码语义：全通过 0，有失败 1。"""
    from xhs_scraper.verify import Verifier
    v = Verifier.__new__(Verifier)          # 不走 __init__（会建网络客户端）
    v.passed, v.failed = ["a", "b"], []

    class _C:
        request_count, error_count = 3, 0
    v.c = _C()
    assert v.report() == 0
    v.failed = ["x"]
    assert v.report() == 1


def test_verifier_overlap():
    from xhs_scraper.verify import Verifier
    assert Verifier.overlap([], []) == 0.0
    assert Verifier.overlap(["a", "b"], ["a", "b"]) == 1.0
    assert Verifier.overlap(["a", "b"], ["a", "c"]) == 0.5


# ---------- 筛选面板解析（离线，mock 掉网络）----------

def test_filter_options_parsing():
    """filter_options() 要把服务端下发的面板结构整理成 {group_id: {name, tags}}。"""
    from xhs_scraper import XhsClient

    class FakeResp:
        @staticmethod
        def json():
            return {"success": True, "data": {"filters": [
                {"id": "sort_type", "name": "排序依据",
                 "filter_tags": [{"id": "general"}, {"id": "popularity_descending"}]},
                {"id": "filter_note_time", "name": "发布时间",
                 "filter_tags": [{"id": "不限"}, {"id": "一周内"}]},
            ]}}

    c = XhsClient.__new__(XhsClient)
    c.search_filters = lambda kw: FakeResp()
    got = c.filter_options("咖啡")
    assert got["sort_type"]["name"] == "排序依据"
    assert got["sort_type"]["tags"] == ["general", "popularity_descending"]
    assert got["filter_note_time"]["tags"] == ["不限", "一周内"]


def test_filter_options_survives_error():
    from xhs_scraper import XhsClient

    class Boom:
        @staticmethod
        def json():
            raise ValueError("bad")
    c = XhsClient.__new__(XhsClient)
    c.search_filters = lambda kw: Boom()
    assert c.filter_options("咖啡") == {}
