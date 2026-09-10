"""xhs-scraper — 小红书 Web API 采集工具（纯算签名，无需浏览器在线）。"""

__version__ = "0.1.0"

from .client import XhsClient, XhsBlockedError  # noqa: F401
from .client import resolve_fingerprint, load_cookies  # noqa: F401

__all__ = ["XhsClient", "XhsBlockedError", "resolve_fingerprint", "load_cookies", "__version__"]
