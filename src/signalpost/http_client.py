"""Small HTTP client: retries, content hashes, and a public-URL check for company sites."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

USER_AGENT = "SignalpostResearch/1.0 (public-registry research; +https://builderr.ai/challenges/signalpost)"
PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class UnsafeUrl(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            any(ip in network for network in PRIVATE_NETWORKS),
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def assert_public_http_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise UnsafeUrl(f"unsupported scheme for {url}")
    host = parts.hostname
    if not host:
        raise UnsafeUrl(f"missing host for {url}")
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "metadata.google.internal"} or lowered.endswith(".local") or lowered.endswith(".internal"):
        raise UnsafeUrl(f"blocked host {host}")
    try:
        literal = ipaddress.ip_address(lowered)
    except ValueError:
        literal = None
    if literal is not None and _is_blocked_ip(literal):
        raise UnsafeUrl(f"blocked address {host}")
    try:
        infos = socket.getaddrinfo(lowered, None)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"dns failure for {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(ip):
            raise UnsafeUrl(f"{host} resolves to a non-public address")


def normalize_website(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered.startswith(("javascript:", "data:", "file:")):
        return None
    if not lowered.startswith(("http://", "https://")):
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return raw


@dataclass
class Fetch:
    url: str
    final_url: str
    status: int | None
    body: bytes
    text: str
    json_body: Any
    content_sha256: str
    retrieved_at: str
    elapsed_ms: int
    error: str | None = None
    attempts: int = 1
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200


class HttpClient:
    def __init__(self, *, timeout: float = 20.0, retries: int = 2, max_bytes: int = 2_000_000) -> None:
        self.timeout = timeout
        self.retries = retries
        self.max_bytes = max_bytes
        self.request_count = 0
        self._lock = threading.Lock()
        self._opener = build_opener()

    def get(self, url: str, *, accept: str, timeout: float | None = None, max_bytes: int | None = None, public_only: bool = False) -> Fetch:
        started = time.monotonic()
        retrieved_at = utc_now()
        limit = max_bytes or self.max_bytes
        if public_only:
            try:
                assert_public_http_url(url)
            except UnsafeUrl as exc:
                return self._empty(url, started, retrieved_at, error=f"blocked_url: {exc}")
        delay = 0.4
        last_error = "request failed"
        status: int | None = None
        attempts = 0
        for attempt in range(self.retries + 1):
            attempts = attempt + 1
            try:
                request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
                with self._lock:
                    self.request_count += 1
                with self._opener.open(request, timeout=timeout or self.timeout) as response:
                    status = getattr(response, "status", None) or response.getcode()
                    raw = response.read(limit + 1)
                    final_url = response.geturl()
                    headers = {key.lower(): value for key, value in response.headers.items()}
                if public_only:
                    try:
                        assert_public_http_url(final_url)
                    except UnsafeUrl as exc:
                        return self._empty(url, started, retrieved_at, error=f"blocked_url: {exc}", status=status, attempts=attempts)
                truncated = len(raw) > limit
                body = raw[:limit]
                return self._fetch(
                    url,
                    final_url,
                    status,
                    body,
                    headers,
                    started,
                    retrieved_at,
                    error="truncated" if truncated else None,
                    attempts=attempts,
                )
            except HTTPError as exc:
                status = exc.code
                body = exc.read(limit) if exc.fp else b""
                if status in {404, 410, 401, 403}:
                    return self._fetch(url, url, status, body, {}, started, retrieved_at, error=f"http_{status}", attempts=attempts)
                last_error = f"http_{status}"
            except (URLError, TimeoutError, socket.timeout, OSError) as exc:
                last_error = str(exc)
                status = None
            if attempt < self.retries and status in {None, 429, 500, 502, 503, 504}:
                time.sleep(delay)
                delay *= 2
        return self._empty(url, started, retrieved_at, error=last_error, status=status, attempts=attempts)

    def get_json(self, url: str, **kwargs: Any) -> Fetch:
        fetched = self.get(url, accept="application/json", **kwargs)
        if fetched.body and fetched.status == 200:
            import json

            try:
                fetched.json_body = json.loads(fetched.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                fetched.error = f"invalid_json: {exc}"
                fetched.json_body = None
        return fetched

    def get_text(self, url: str, **kwargs: Any) -> Fetch:
        return self.get(url, accept="text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5", **kwargs)

    def _fetch(
        self,
        url: str,
        final_url: str,
        status: int | None,
        body: bytes,
        headers: dict[str, str],
        started: float,
        retrieved_at: str,
        error: str | None,
        attempts: int,
    ) -> Fetch:
        encoding = "utf-8"
        content_type = headers.get("content-type", "")
        if "charset=" in content_type:
            encoding = content_type.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        try:
            text = body.decode(encoding, errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        return Fetch(
            url=url,
            final_url=final_url or url,
            status=status,
            body=body,
            text=text,
            json_body=None,
            content_sha256=hashlib.sha256(body).hexdigest(),
            retrieved_at=retrieved_at,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=error,
            attempts=attempts,
            headers=headers,
        )

    def _empty(self, url: str, started: float, retrieved_at: str, error: str, status: int | None = None, attempts: int = 0) -> Fetch:
        return Fetch(
            url=url,
            final_url=url,
            status=status,
            body=b"",
            text="",
            json_body=None,
            content_sha256=hashlib.sha256(b"").hexdigest(),
            retrieved_at=retrieved_at,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=error,
            attempts=attempts,
        )


def availability_for_http(status: int | None) -> str:
    if status == 200:
        return "available"
    if status in {404, 410}:
        return "not_available"
    if status in {401, 403, 429}:
        return "blocked"
    return "failed"
