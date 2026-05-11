from __future__ import annotations

from urllib.parse import urlparse


PLATFORM_DOMAIN_MAP = {
    "bilibili.com": "bilibili",
    "b23.tv": "bilibili",
    "douyin.com": "douyin",
    "iesdouyin.com": "douyin",
    "xiaohongshu.com": "xiaohongshu",
    "xiaohongshu.cn": "xiaohongshu",
    "xhslink.com": "xiaohongshu",
    "kuaishou.com": "kuaishou",
    "chenzhongtech.com": "kuaishou",
    "gifshow.com": "kuaishou",
}


def detect_platform(url: str, platform_hint: str | None = None) -> str:
    if platform_hint:
        return platform_hint.strip().lower()

    hostname = urlparse(url).netloc.lower().strip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]

    for suffix, platform in PLATFORM_DOMAIN_MAP.items():
        if hostname == suffix or hostname.endswith(f".{suffix}"):
            return platform

    return "unknown"
