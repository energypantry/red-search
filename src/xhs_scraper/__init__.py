"""red-search — 一个可以快速在社交媒体搜索信息的工具。"""

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
