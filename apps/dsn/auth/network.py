# auth/network.py
# NetworkDetector — 内外网判断

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("NetworkDetector")

DEFAULT_INTERNAL_CIDRS = [
    "192.168.0.0/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "127.0.0.0/8",
]


class NetworkDetector:
    """基于请求 IP 判断内外网环境"""

    def __init__(self, internal_cidrs: list[str] | None = None):
        self._cidrs_str = internal_cidrs or DEFAULT_INTERNAL_CIDRS
        self._cidrs = self._parse_cidrs(self._cidrs_str)

    @staticmethod
    def _parse_cidrs(cidrs: list[str]) -> list:
        try:
            from ipaddress import ip_network
            return [ip_network(c) for c in cidrs]
        except ImportError:
            return []

    def is_internal(self, ip: str) -> bool:
        if not ip or ip in ("127.0.0.1", "::1", "localhost"):
            return True
        if not self._cidrs:
            return ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.")
        try:
            from ipaddress import ip_address
            addr = ip_address(ip)
            return any(addr in cidr for cidr in self._cidrs)
        except (ValueError, ImportError):
            return False

    def get_network_level(self, ip: str) -> str:
        if not ip or ip in ("127.0.0.1", "::1", "localhost"):
            return "loopback"
        return "internal" if self.is_internal(ip) else "external"

    @staticmethod
    def get_client_ip(request) -> str:
        if request is None:
            return ""
        x_forwarded = request.headers.get("X-Forwarded-For", "")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
        return getattr(request, "remote_addr", "") or getattr(
            getattr(request, "environ", {}), "get", lambda *a: ""
        )("REMOTE_ADDR", "")
