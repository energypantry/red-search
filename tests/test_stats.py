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
