#!/usr/bin/env python3
"""
xhs_scraper.client — 小红书 Web API 客户端（纯算签名，风险缓解版）

风险缓解（默认开启，别关）:
  1. 指纹固定化 —— xhshow 原生默认每次签名都随机换一套设备指纹（x8/x9 每次都变），
     等于“同一账号每请求自称一台新设备”，是极易被聚类的异常。
     本模块把它固定：优先用真机指纹（pin 文件），否则持久化一份合成指纹。
  2. UA 自洽 —— 请求头 User-Agent 跟随指纹模式，避免与指纹自称的平台矛盾。
  3. 会话状态复用 —— 复用 SessionManager，page_load_timestamp 稳定、sequence 单调递增。
  4. 熔断 + 重试 —— 连续异常指数退避，5 次熔断；网络层 3 次重试。

用法（库）:
    from xhs_scraper import XhsClient, XhsBlockedError, build_filters
    c = XhsClient()
    items = c.search("咖啡", sort="likes",
                     filters=build_filters(time="week", note_type="video")).json()["data"]["items"]
    nid, tok = items[0]["id"], items[0]["xsec_token"]   # token 在 item 级
    note  = c.feed(nid, tok).json()
    cmts  = c.comments(nid, tok).json()
    who   = c.user(note["data"]["items"][0]["note_card"]["user"]["user_id"]).json()

用法（CLI）:
    xhs search "青岛 房东直租" 40 --time week --sort latest
    xhs search --help          # 全部筛选参数

CLI（推荐用 bin/xhs，见项目 README）:
    python3 -m xhs_scraper.cli search "咖啡" 20
    python3 -m xhs_scraper.cli suggest "咖啡"           # 搜索联想词
    python3 -m xhs_scraper.cli filters "咖啡"           # 当前可用的筛选项（服务端下发）
    python3 -m xhs_scraper.cli feed <note_id> <xsec_token>
    python3 -m xhs_scraper.cli comments <note_id> <xsec_token>
    python3 -m xhs_scraper.cli user <user_id>
    python3 -m xhs_scraper.cli usernotes <user_id> [N]

Cookie 来源（优先级）:
    1) 环境变量 XHS_COOKIES（JSON 字符串）
    2) 文件：XHS_COOKIE_FILE > ~/.local/share/xhs/cookies.json > /tmp/xhs_cookies.json

批量采集见 xhs_scraper.collect。
"""
import json
import os
import random
import sys
import time

import requests
from xhshow import Xhshow
from xhshow.session import SessionManager

BASE = "https://edith.xiaohongshu.com"
STATE_DIR = os.environ.get("XHS_STATE_DIR") or os.path.expanduser("~/.local/share/xhs")
COOKIE_DEFAULT = os.path.join(STATE_DIR, "cookies.json")
FP_DEFAULT = os.path.join(STATE_DIR, "device_fingerprint.json")            # 真机指纹
FP_SYN_DEFAULT = os.path.join(STATE_DIR, "synthetic_fingerprint.json")     # 持久化合成指纹
# 兜底 UA（仅在真机 pin 文件里没存 ua 时用；正常取 pin 文件里的真机 UA）
REAL_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
REFERER = {
    "Referer": "https://www.xiaohongshu.com/",
    "Origin": "https://www.xiaohongshu.com",
    "Content-Type": "application/json;charset=UTF-8",
}

# 筛选映射（取值来自服务端 GET /api/sns/web/v1/search/filter）
SORT_MAP = {
    "general": "general",
    "latest": "time_descending",
    "likes": "popularity_descending",
    "comments": "comment_descending",
    "collects": "collect_descending",
}
TIME_MAP = {"day": "一天内", "week": "一周内", "half_year": "半年内", "halfYear": "半年内"}
TYPE_MAP = {"video": "视频笔记", "image": "普通笔记"}
SCOPE_MAP = {"seen": "已看过", "unseen": "未看过", "followed": "已关注"}
LOCATION_MAP = {"city": "同城", "nearby": "附近"}


def build_filters(time=None, note_type=None, scope=None, location=None, hot=None):
    """拼 search 接口的 filters 数组。传友好值，内部映射成服务端 tag。"""
    pairs = [
        ("filter_note_time", time, TIME_MAP),
        ("filter_note_type", note_type, TYPE_MAP),
        ("filter_note_range", scope, SCOPE_MAP),
        ("filter_pos_distance", location, LOCATION_MAP),
    ]
    out = []
    for fid, val, m in pairs:
        if val and val in m:
            out.append({"type": fid, "tags": [m[val]]})
    if hot:
        out.append({"type": "filter_hot", "tags": [hot]})
    return out


# 自定义 base64 字母表（小红书 X-s / X-S-Common 使用）
CUSTOM_B64 = "ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5"
STD_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def decode_custom_b64(s: str) -> str:
    """把自定义字母表的 base64 还原成 UTF-8 字符串（调试/测试用）。"""
    import base64 as _b64
    mapped = "".join("=" if ch == "=" else STD_B64[CUSTOM_B64.index(ch)]
                     if ch in CUSTOM_B64 else ch for ch in s)
    return _b64.b64decode(mapped).decode("utf-8", errors="replace")


# 风控/失效信号
BLOCK_CODES = {-1, 300031, 300012, 461, 471}
# 网络层重试次数（TLS/连接重置）
NET_RETRY = 3


class XhsBlockedError(RuntimeError):
    """连续命中风控/失效信号，已熔断。"""


def load_cookies(path=None):
    if os.environ.get("XHS_COOKIES"):
        return json.loads(os.environ["XHS_COOKIES"])
    if path:
        candidates = [path]
    else:
        candidates = [
            os.environ.get("XHS_COOKIE_FILE"),
            COOKIE_DEFAULT,
            "/tmp/xhs_cookies.json",
        ]
    for p in candidates:
        if p and os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    raise FileNotFoundError(
        f"未找到 cookies。先跑 `xhs cookies`（默认写入 {COOKIE_DEFAULT}），"
        "或设 XHS_COOKIE_FILE / XHS_COOKIES。")


def resolve_fingerprint(pin_file=None, mode=None):
    """
    决定用哪套设备指纹，并返回 (mode, ua)。

    mode:
      real      —— 用真机指纹（device_fingerprint.json，来自你登录的那个浏览器）
      synthetic —— 用合成指纹（持久化在 synthetic_fingerprint.json，跨命令复用）
      auto（默认）—— 有真机指纹就用真机，否则用持久化合成

    ua 返回与指纹**自洽**的 User-Agent：合成指纹自称 Windows Edge，
    若 HTTP 头仍发 macOS Chrome，会形成“同一请求头与指纹互相矛盾”的强信号。
    环境变量: XHS_FP_MODE（real/synthetic/auto）、XHS_FP_PIN、XHS_FP_SYN_FILE
    """
    import xhshow.generators.fingerprint as fpmod

    mode = (mode or os.environ.get("XHS_FP_MODE") or "auto").lower()

    # ---- 真机指纹 ----
    real = pin_file or os.environ.get("XHS_FP_PIN")
    if not real:
        for cand in (FP_DEFAULT,
                     os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "device_fingerprint.json")):
            if os.path.exists(cand):
                real = cand
                break

    if mode in ("auto", "real") and real and os.path.exists(real):
        with open(real) as f:
            pin = json.load(f)
        b1 = pin.get("x8")
        if b1:
            # 只固定 generate_b1；x9 由 CRC32.crc32_js_int(b1) 自动得出，保证自洽
            fpmod.FingerprintGenerator.generate_b1 = lambda self, fp, _b1=b1: _b1
            return "real", (pin.get("ua") or REAL_UA)

    if mode == "real":
        raise FileNotFoundError(
            f"XHS_FP_MODE=real 但未找到真机指纹文件。先跑 `xhs fp`（期望位置 {real}）。")

    # ---- 合成指纹（持久化，跨进程/跨命令复用）----
    syn_path = os.environ.get("XHS_FP_SYN_FILE") or FP_SYN_DEFAULT
    fp = None
    if os.path.exists(syn_path):
        try:
            with open(syn_path) as f:
                fp = json.load(f).get("fp")
        except Exception:
            fp = None

    if not fp:
        from xhshow.config import CryptoConfig
        gen = fpmod.FingerprintGenerator(CryptoConfig())
        fp = fpmod.FingerprintGenerator.generate(
            gen, {}, getattr(gen.config, "PUBLIC_USERAGENT", None))
        try:
            os.makedirs(os.path.dirname(syn_path), exist_ok=True)
            with open(syn_path, "w") as f:
                json.dump({"mode": "synthetic", "fp": fp},
                          f, ensure_ascii=False, indent=1)
            os.chmod(syn_path, 0o600)
        except Exception:
            pass

    fpmod.FingerprintGenerator.generate = lambda self, cookies, user_agent, _fp=fp: dict(_fp)
    return "synthetic", fp.get("x1") or REAL_UA


class XhsClient:
    def __init__(self, cookies=None, throttle=1.5, jitter=0.6,
                 pin=True, pin_file=None, fp_mode=None, auto_recover=True, verbose=False):
        self.cookies = cookies or load_cookies()
        self.throttle = throttle
        self.jitter = jitter
        self.verbose = verbose
        self.auto_recover = auto_recover
        if pin:
            self.fp_mode, self.ua = resolve_fingerprint(pin_file, fp_mode)
        else:
            self.fp_mode, self.ua = "none", REAL_UA
        self.client = Xhshow()
        # 复用同一 SessionManager：page_load_timestamp 稳定、sequence 单调递增
        self.session = SessionManager()
        self.s = requests.Session()
        for k, v in self.cookies.items():
            self.s.cookies.set(k, v, domain=".xiaohongshu.com")
        self._last = 0.0
        self._errors = 0
        self._cooldown = 0.0
        self.request_count = 0
        self.error_count = 0

    # ---------- 基础设施 ----------
    def _pace(self):
        wait = self.throttle - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        if self.jitter:
            time.sleep(random.uniform(0, self.jitter))
        if self._cooldown > 0:
            time.sleep(self._cooldown)
            self._cooldown = 0.0
        self._last = time.time()

    def _after(self, r):
        self.request_count += 1
        try:
            j = r.json()
        except Exception:
            j = {}
        bad = (r.status_code >= 400) or (j.get("code") in BLOCK_CODES) or (j.get("success") is False)
        if bad:
            self._errors += 1
            self.error_count += 1
            # 指数退避：2s, 4s, 8s, 16s…上限 120s
            self._cooldown = min(120.0, 2.0 ** min(self._errors, 6))
            if self.verbose:
                print(f"  [warn] HTTP {r.status_code} code={j.get('code')} "
                      f"连续异常={self._errors} 冷却={self._cooldown:.0f}s", file=sys.stderr)
            if self._errors >= 5 and self.auto_recover:
                raise XhsBlockedError(
                    f"连续 {self._errors} 次异常（最后 HTTP {r.status_code} code={j.get('code')}），已熔断。"
                    " 建议：停一段时间 / 重新取 cookies / 降低频率。")
        else:
            self._errors = 0
            self._cooldown = 0.0
        return j

    def _headers(self):
        return {"User-Agent": self.ua, **REFERER}

    def _send(self, fn, *a, **kw):
        """网络层重试：TLS/连接被重置/超时是常态（实测偶发 ConnectionReset）。"""
        last = None
        for attempt in range(NET_RETRY):
            try:
                return fn(*a, **kw)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.SSLError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.Timeout) as e:
                last = e
                if attempt < NET_RETRY - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise last

    def post(self, path, body, x_rap=True):
        self._pace()
        uri = BASE + path
        h = self._headers()
        h.update(self.client.sign_headers_post(uri=uri, cookies=self.cookies,
                                                   payload=body, session=self.session,
                                                   **({"x_rap": True} if x_rap else {})))
        r = self._send(self.s.post, uri, headers=h,
                       data=json.dumps(body, ensure_ascii=False), timeout=25)
        self._after(r)
        return r

    def get(self, path, params):
        self._pace()
        uri = BASE + path
        h = self._headers()
        h.update(self.client.sign_headers_get(uri=uri, cookies=self.cookies,
                                              params=params, session=self.session))
        # 必须用 build_url 产出与签名输入完全一致的 URL；
        # 用 requests 的 params= 会二次编码 → 与签名失配 → 406
        url = self.client.build_url(uri, params)
        r = self._send(self.s.get, url, headers=h, timeout=25)
        self._after(r)
        return r

    # ---------- 筛选面板定义 ----------
    def search_filters(self, keyword):
        """拉取服务端**动态下发**的搜索筛选项（排序依据/笔记类型/发布时间/搜索范围/位置距离/热门词）。

        用途：确认当前有哪些筛选可选（小红书改版后不用再逆向）。返回值可直接喂给 filters 参数。
        """
        return self.get("/api/sns/web/v1/search/filter",
                        {"keyword": keyword, "search_id": self.client.get_search_id()})

    def filter_options(self, keyword):
        """便捷：把筛选面板整理成 {group_id: {"name":..., "tags":[...]}} 。"""
        try:
            groups = (self.search_filters(keyword).json().get("data") or {}).get("filters") or []
        except Exception:
            return {}
        return {g.get("id"): {"name": g.get("name"),
                              "tags": [t.get("id") for t in (g.get("filter_tags") or [])]}
                for g in groups}

    # ---------- 搜索联想词 ----------
    def suggest(self, keyword):
        """搜索下拉联想词。原始响应中 `data.sug_items[].text` 为建议词。"""
        return self.get("/api/sns/web/v1/search/recommend", {"keyword": keyword})

    def suggestions(self, keyword):
        """便捷方法：直接返回建议词字符串列表（失败返回空列表）。"""
        try:
            d = (self.suggest(keyword).json().get("data") or {})
        except Exception:
            return []
        return [it.get("text") for it in (d.get("sug_items") or []) if it.get("text")]

    # ---------- 用户 / 作者主页 ----------
    def user(self, user_id):
        """他人主页 basic_info + interactions（关注/粉丝/获赞）。参数名必须是 target_user_id。"""
        return self.get("/api/sns/web/v1/user/otherinfo", {"target_user_id": user_id})

    def user_notes(self, user_id, num=30, cursor=""):
        """某用户已发布的笔记列表（v2 在 edith 是 404，用 v1）。"""
        return self.get("/api/sns/web/v1/user_posted",
                        {"num": num, "cursor": cursor, "user_id": user_id})

    def user_note_pages(self, user_id, max_pages=1, num=30):
        cursor = ""
        for _ in range(max_pages):
            try:
                d = (self.user_notes(user_id, num=num, cursor=cursor).json().get("data") or {})
            except Exception:
                break
            notes = d.get("notes") or []
            if not notes:
                break
            yield notes
            if not d.get("has_more"):
                break
            cursor = d.get("cursor") or ""

    # ---------- 已实测端点 ----------
    def search(self, keyword, page=1, page_size=20, sort="general", filters=None):
        # 实测：page_size 必须为 20，其他值服务端返回 0 条
        if page_size != 20:
            page_size = 20
        # 实测：sort 必须用服务端枚举（likes/latest 等友好名会被静默忽略！）
        sort = SORT_MAP.get(sort, sort)
        return self.post("/api/sns/web/v1/search/notes", {
            "keyword": keyword, "page": page, "page_size": page_size,
            "search_id": self.client.get_search_id(), "sort": sort, "note_type": 0,
            "ext_flags": [], "filters": filters or [],
            "image_formats": ["jpg", "webp", "avif"],
            "need_filter_image": False,
        })

    def feed(self, note_id, xsec_token, xsec_source="pc_search"):
        return self.post("/api/sns/web/v1/feed", {
            "source_note_id": note_id, "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"},
            "xsec_source": xsec_source, "xsec_token": xsec_token,
        })

    def comments(self, note_id, xsec_token, cursor=""):
        return self.get("/api/sns/web/v2/comment/page", {
            "note_id": note_id, "cursor": cursor, "top_comment_id": "",
            "image_formats": "jpg,webp,avif", "xsec_token": xsec_token,
        })

    def sub_comments(self, note_id, root_comment_id, xsec_token, num=10, cursor=""):
        return self.get("/api/sns/web/v2/comment/sub/page", {
            "note_id": note_id, "root_comment_id": root_comment_id, "num": num,
            "cursor": cursor, "image_formats": "jpg,webp,avif",
            "top_comment_id": "", "xsec_token": xsec_token,
        })

    # ---------- 分页 ----------
    def search_pages(self, keyword, max_pages=1, page_size=20, sort="general", filters=None):
        """逐页产出 (page, items)；子项含 id / xsec_token / note_card。"""
        for page in range(1, max_pages + 1):
            r = self.search(keyword, page=page, page_size=page_size, sort=sort, filters=filters)
            try:
                data = r.json().get("data") or {}
            except Exception:
                break
            items = data.get("items") or []
            if not items:
                break
            yield page, items
            if not data.get("has_more"):
                break

    def comment_pages(self, note_id, xsec_token, max_pages=3):
        cursor = ""
        for _ in range(max_pages):
            r = self.comments(note_id, xsec_token, cursor=cursor)
            try:
                d = r.json().get("data") or {}
            except Exception:
                break
            cs = d.get("comments") or []
            if not cs:
                break
            yield cs
            if not d.get("has_more"):
                break
            cursor = d.get("cursor") or ""


# ---------- CLI: search 参数解析 ----------
SEARCH_USAGE = """用法:
  xhs search <关键词> [条数] [选项]

选项（取值写错会被服务端**静默忽略**，所以这里做本地校验）:
  --sort      general|latest|likes|comments|collects   综合/最新/最多点赞/最多评论/最多收藏
  --time      day|week|half_year                       一天内/一周内/半年内
  --type      video|image                              视频笔记/普通笔记
  --scope     seen|unseen|followed                     已看过/未看过/已关注
  --location  city|nearby                              同城/附近
  --hot       <城市词>                                  热门词，如 青岛

取值写 any / 不限 / 全部 表示不加该筛选。

示例:
  xhs search "青岛 房东直租" 40 --time week --sort latest
  xhs search "咖啡" 60 --type video --time half_year
  xhs search "露营" --time day --location city
"""

# flag -> (取值说明, 允许值映射表或 None 表示自由取值)
SEARCH_FLAGS = {
    "--sort":     ("综合/最新/最多点赞/最多评论/最多收藏", SORT_MAP),
    "--time":     ("一天内/一周内/半年内", TIME_MAP),
    "--type":     ("视频笔记/普通笔记", TYPE_MAP),
    "--scope":    ("已看过/未看过/已关注", SCOPE_MAP),
    "--location": ("同城/附近", LOCATION_MAP),
    "--hot":      ("热门词（城市名）", None),
}
ANY_VALUES = {"any", "none", "", "不限", "全部"}


def parse_search_args(args):
    """把 `关键词 [条数] --time week ...` 拆成 (关键词, 条数, 筛选字典)。

    取值不在允许集合时**直接报错**而不是静默传给服务端——服务端对非法 tag
    会当没传，导致"看着成功但筛选根本没生效"。
    """
    kw, n, opts = None, None, {}
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-h", "--help"):
            print(SEARCH_USAGE, end="")
            raise SystemExit(0)
        if a in SEARCH_FLAGS:
            if i + 1 >= len(args):
                raise SystemExit(f"{a} 需要一个取值\n\n{SEARCH_USAGE}")
            key, val = a[2:], args[i + 1]
            if val not in ANY_VALUES:
                allowed = SEARCH_FLAGS[a][1]
                if allowed is not None and val not in allowed:
                    raise SystemExit(
                        f"{a} 取值非法: {val!r}\n"
                        f"  允许: {' | '.join(allowed)}（或 any/不限）\n"
                        f"  说明: {SEARCH_FLAGS[a][0]}")
                opts[key] = val
            i += 2
        elif a.startswith("--"):
            raise SystemExit(f"未知参数 {a}\n\n{SEARCH_USAGE}")
        elif kw is None:
            kw = a
            i += 1
        elif n is None and a.isdigit():
            n = int(a)
            i += 1
        else:
            raise SystemExit(f"多余参数 {a!r}\n\n{SEARCH_USAGE}")
    if not kw:
        raise SystemExit(SEARCH_USAGE)
    n = 20 if n is None else n
    if n <= 0:
        raise SystemExit("条数必须为正整数")
    return kw, n, opts


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    c = XhsClient(verbose=True)
    cmd = sys.argv[1]
    if cmd == "search":
        kw, n, o = parse_search_args(sys.argv[2:])
        filters = build_filters(time=o.get("time"), note_type=o.get("type"),
                                scope=o.get("scope"), location=o.get("location"),
                                hot=o.get("hot"))
        sort = o.get("sort", "general")
        max_pages = max(1, -(-n // 20))     # 服务端 page_size 固定 20
        shown = []
        for _page, items in c.search_pages(kw, max_pages=max_pages, sort=sort, filters=filters):
            for it in items:
                nc = it.get("note_card") or {}
                if not nc:
                    continue
                shown.append((it, nc))
                if len(shown) >= n:
                    break
            if len(shown) >= n:
                break
        eff = " ".join(f"{k}={v}" for k, v in o.items())
        print(f"keyword={kw!r} 条数={len(shown)} sort={sort}" + (f"  [{eff}]" if eff else ""))
        for it, nc in shown:
            u = (nc.get("user") or {}).get("nickname") or ""
            print(f"  {it['id']}  tok={it.get('xsec_token','')[:16]}…  "
                  f"{str(nc.get('display_title'))[:40]:42} "
                  f"likes={str((nc.get('interact_info') or {}).get('liked_count')):>6}  @{u}")
        if not shown:
            print("  （无结果）")
    elif cmd == "feed":
        nc = ((c.feed(sys.argv[2], sys.argv[3]).json().get("data") or {}).get("items")
              or [{}])[0].get("note_card") or {}
        print(json.dumps({"title": nc.get("title"), "desc": nc.get("desc"),
                          "interact": nc.get("interact_info"),
                          "images": len(nc.get("image_list") or [])},
                         ensure_ascii=False, indent=2)[:2000])
    elif cmd == "comments":
        print(json.dumps(c.comments(sys.argv[2], sys.argv[3]).json(),
                         ensure_ascii=False, indent=2)[:3000])
    elif cmd == "filters":
        kw = sys.argv[2] if len(sys.argv) > 2 else "咖啡"
        opts = c.filter_options(kw)
        print(json.dumps(opts, ensure_ascii=False, indent=1))
    elif cmd == "suggest":
        kw = sys.argv[2] if len(sys.argv) > 2 else "咖啡"
        words = c.suggestions(kw)
        print(json.dumps({"keyword": kw, "count": len(words), "suggestions": words},
                         ensure_ascii=False, indent=2))
    elif cmd == "user":
        d = (c.user(sys.argv[2]).json().get("data") or {})
        bi = d.get("basic_info") or {}
        inter = {x.get("type"): x.get("count") for x in (d.get("interactions") or [])}
        print(json.dumps({"user_id": sys.argv[2], "nickname": bi.get("nickname"),
                          "red_id": bi.get("red_id"), "gender": bi.get("gender"),
                          "ip_location": bi.get("ip_location"), "desc": bi.get("desc"),
                          "avatar": bi.get("images"), "counts": inter,
                          "tags": [t.get("name") for t in (d.get("tags") or [])]},
                         ensure_ascii=False, indent=2)[:2500])
    elif cmd == "usernotes":
        d = c.user_notes(sys.argv[2], num=int(sys.argv[3]) if len(sys.argv) > 3 else 30).json()
        notes = (d.get("data") or {}).get("notes") or []
        print(f"success={d.get('success')} notes={len(notes)}")
        for n in notes:
            ii = n.get("interact_info") or {}
            print(f"  {n.get('note_id')}  {str(n.get('display_title'))[:40]:42} "
                  f"赞={ii.get('liked_count')}  {n.get('time')}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
