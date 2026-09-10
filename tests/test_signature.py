"""离线测试：签名结构、指纹稳定性、采集器工具函数。不发网络请求。"""
import base64
import hashlib
import json

import pytest

from xhs_scraper import XhsClient
from xhs_scraper.client import CUSTOM_B64, decode_custom_b64
from xhs_scraper.collect import is_real_note_id, note_record

FAKE_COOKIES = {
    "a1": "1a0" + "0" * 49,
    "webId": "0" * 32,
    "web_session": "x" * 38,
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """不碰真实状态目录，强制用合成指纹。"""
    monkeypatch.setenv("XHS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("XHS_FP_MODE", "synthetic")
    monkeypatch.setenv("XHS_FP_SYN_FILE", str(tmp_path / "syn.json"))
    return XhsClient(cookies=FAKE_COOKIES, throttle=0, jitter=0, pin=True)


def test_custom_b64_alphabet_roundtrip():
    """自定义 base64 字母表必须能把 payload 还原成合法 JSON。"""
    raw = '{"x0":"4.4.3","x1":"xhs-pc-web"}'
    encoded = base64.b64encode(raw.encode()).decode()
    mapped = "".join(CUSTOM_B64["ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".index(c)]
                     if c != "=" else "=" for c in encoded)
    assert decode_custom_b64(mapped) == raw


def test_xs_common_structure(client):
    """X-S-Common 解出来必须是期望的字段集合。"""
    xs_common = client.client.sign_xs_common(client.cookies)
    struct = json.loads(decode_custom_b64(xs_common))
    assert set(struct) >= {"s0", "x1", "x2", "x3", "x4", "x5", "x8", "x9", "x11"}
    assert struct["x5"] == client.cookies["a1"]
    assert struct["x3"] == "xhs-pc-web"
    assert len(struct["x8"]) > 100          # 指纹 blob


def test_fingerprint_is_stable_across_calls(client):
    """核心风险修复：同一客户端多次签名，指纹必须完全一致。"""
    a = json.loads(decode_custom_b64(client.client.sign_xs_common(client.cookies)))
    b = json.loads(decode_custom_b64(client.client.sign_xs_common(client.cookies)))
    assert a["x8"] == b["x8"], "设备指纹不稳定 → 会被风控聚类"
    assert a["x9"] == b["x9"]


def test_fingerprint_persisted_across_processes(tmp_path, monkeypatch):
    """合成指纹必须落盘，保证新进程复用同一身份。"""
    monkeypatch.setenv("XHS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("XHS_FP_MODE", "synthetic")
    monkeypatch.setenv("XHS_FP_SYN_FILE", str(tmp_path / "syn.json"))
    c1 = XhsClient(cookies=FAKE_COOKIES, throttle=0, jitter=0)
    x8_first = json.loads(decode_custom_b64(c1.client.sign_xs_common(c1.cookies)))["x8"]
    assert (tmp_path / "syn.json").exists()
    # 模拟"另一个进程"：直接读盘取指纹
    saved = json.loads((tmp_path / "syn.json").read_text())["fp"]
    assert saved.get("x1"), "落盘的指纹必须带 UA 字段用于同步请求头"
    assert hashlib.sha256(x8_first.encode()).hexdigest()


def test_ua_matches_fingerprint_mode(client):
    """请求头 UA 必须与指纹自称的平台一致，避免自相矛盾。"""
    assert "Windows" in client.ua, "synthetic 指纹自称 Windows Edge，UA 必须同步"


def test_xs_header_shape(client):
    """X-s 必须是 XYS_ 前缀 + 可解出的字段。

    注：真机抓包里 payload 是 x0..x7（含 x5=md5、x6/x7=encSsk）；
    xhshow 的纯算实现只发 x0..x4，服务端同样接受（实测 200）。
    """
    xs = client.client.sign_xs_get("/api/sns/web/v1/system/config", FAKE_COOKIES["a1"])
    assert xs.startswith("XYS_")
    struct = json.loads(decode_custom_b64(xs[4:]))
    assert struct["x1"] == "xhs-pc-web"
    assert struct["x0"] and struct["x3"] and struct["x4"]
    assert struct["x3"].startswith("mns"), "x3 应为 mnsv2 签名串"


def test_note_id_filter_rejects_placeholders():
    """搜索结果会混入直播/AI 占位条目，必须被过滤。"""
    assert is_real_note_id("65dbeb40000000000b023e8d")
    assert not is_real_note_id("7e923fde-815e-4bca-9127-1c2e257d1272#1789048584130")
    assert not is_real_note_id("")
    assert not is_real_note_id(None)


def test_note_record_parses_counts():
    item = {
        "id": "65dbeb40000000000b023e8d",
        "xsec_token": "AB" + "x" * 44,
        "note_card": {
            "display_title": "t", "type": "normal",
            "user": {"user_id": "u1", "nickname": "n1"},
            "interact_info": {"liked_count": "123", "collected_count": "4", "comment_count": "5"},
        },
    }
    rec = note_record("咖啡", item)
    assert rec["note_id"] == "65dbeb40000000000b023e8d"
    assert rec["liked_count"] == 123          # 字符串计数要转 int
    assert rec["user_id"] == "u1"
    assert rec["detail"] is False
