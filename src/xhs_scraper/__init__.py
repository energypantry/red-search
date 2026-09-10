"""xhs-scraper — 小红书 Web API 采集工具（纯算签名，无需浏览器在线）。"""

__version__ = "0.1.1"

from .client import XhsClient, XhsBlockedError  # noqa: F401
from .client import resolve_fingerprint, load_cookies  # noqa: F401
from .client import build_filters, decode_custom_b64  # noqa: F401
from .client import (  # noqa: F401
    SORT_MAP, TIME_MAP, TYPE_MAP, SCOPE_MAP, LOCATION_MAP,
)

__all__ = [
    "XhsClient", "XhsBlockedError", "resolve_fingerprint", "load_cookies",
    # 筛选：传友好值，内部映射成服务端 tag
    "build_filters",
    "SORT_MAP", "TIME_MAP", "TYPE_MAP", "SCOPE_MAP", "LOCATION_MAP",
    # 调试
    "decode_custom_b64",
    "__version__",
]
