"""JUDO i-dos API — raw SSL socket injected into http.client for correct HTTP parsing.

Why not aiohttp / requests?
    HA Core runs on OpenSSL 3.x. The old JUDO server (TLS 1.2 only, self-signed,
    weak cert) gets dropped by OpenSSL 3.x defaults:
      * TLS 1.3 ClientHello → server closes connection → SSLEOFError
      * SECLEVEL=2 → server cert rejected during handshake
    We build the SSL socket manually so we control TLS version, security level
    and SNI hostname, then hand it to http.client for correct HTTP parsing
    (chunked transfer encoding, content-length, keep-alive).

Host resolution strategy (robust / future-proof):
    1. Resolve API_HOST via normal DNS — preferred, survives a server move.
    2. If DNS fails (or as a last resort), use the hardcoded API_IP fallback.
    SNI always uses API_HOST regardless of which IP we connect to, because the
    server validates the SNI hostname.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import socket
import ssl
import urllib.parse

from .const import API_HOST, API_IP, API_PORT, API_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)


def _make_ssl_ctx() -> ssl.SSLContext:
    """SSL context tuned for the old JUDO server (TLS 1.2, weak self-signed cert)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    except (AttributeError, ValueError):
        pass
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


def _candidate_ips() -> list[str]:
    """DNS-resolved IPs first, hardcoded fallback IP last (deduplicated)."""
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(
            API_HOST, API_PORT, socket.AF_INET, socket.SOCK_STREAM
        ):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        if ips:
            _LOGGER.debug("JUDO DNS resolved %s -> %s", API_HOST, ips)
    except Exception as exc:
        _LOGGER.debug("JUDO DNS resolve failed for %s: %s", API_HOST, exc)

    if API_IP and API_IP not in ips:
        ips.append(API_IP)
    return ips


def _connect(ip: str, ctx: ssl.SSLContext) -> ssl.SSLSocket:
    """TCP + SSL handshake to a single IP. SNI uses API_HOST. Raises on failure."""
    raw = socket.create_connection((ip, API_PORT), timeout=API_TIMEOUT)
    try:
        return ctx.wrap_socket(raw, server_hostname=API_HOST)
    except Exception:
        try:
            raw.close()
        except Exception:
            pass
        raise


def _http(ssl_sock: ssl.SSLSocket, ctx: ssl.SSLContext, params: dict) -> dict:
    """Send the HTTP GET over an established SSL socket and parse JSON."""
    conn = http.client.HTTPSConnection(
        API_HOST, API_PORT, context=ctx, timeout=API_TIMEOUT
    )
    conn.sock = ssl_sock  # inject already-wrapped socket, bypass http.client connect()
    try:
        query = urllib.parse.urlencode(params)
        conn.request(
            "GET",
            "/?" + query,
            headers={"User-Agent": _UA, "Accept": "application/json"},
        )
        resp = conn.getresponse()
        body = resp.read()
        return json.loads(body.decode())
    finally:
        conn.close()


def _sync_request(params: dict) -> dict:
    """Blocking HTTPS GET. Tries DNS IPs first, falls back to hardcoded IP.

    Only connection-level failures (TCP/SSL) trigger a retry on the next IP.
    Once a socket is connected, the HTTP phase runs only once — so a slow
    device-relay response never causes a double timeout.
    """
    cmd = params.get("command", "?")
    ctx = _make_ssl_ctx()

    ssl_sock: ssl.SSLSocket | None = None
    used_ip: str | None = None
    last_exc: Exception | None = None

    for ip in _candidate_ips():
        try:
            ssl_sock = _connect(ip, ctx)
            used_ip = ip
            _LOGGER.debug("JUDO [%s] connected via %s (cipher=%s)", cmd, ip, ssl_sock.cipher())
            break
        except Exception as exc:
            last_exc = exc
            _LOGGER.debug("JUDO [%s] connect via %s failed: %s", cmd, ip, type(exc).__name__)
            continue

    if ssl_sock is None:
        _LOGGER.warning("JUDO [%s] could not connect to any host: %s", cmd, last_exc)
        raise last_exc if last_exc else OSError("no candidate hosts")

    try:
        return _http(ssl_sock, ctx, params)
    except Exception as exc:
        _LOGGER.warning(
            "JUDO [%s] HTTP failed via %s: %s - %s",
            cmd, used_ip, type(exc).__name__, exc,
        )
        raise


async def judo_get(params: dict) -> dict:
    """Async wrapper — runs the blocking request in a thread (non-blocking for HA)."""
    try:
        return await asyncio.to_thread(_sync_request, params)
    except Exception:
        # Detailed logging already done inside _sync_request.
        return {}
