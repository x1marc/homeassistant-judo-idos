"""JUDO i-dos API — raw SSL socket injected into http.client for correct HTTP parsing.

aiohttp's SSL stack fails for this server in HA's Python environment.
Solution: create SSL socket manually (controls SNI + TLS version + security
level), then inject into http.client.HTTPSConnection which handles chunked
transfer encoding, content-length, keep-alive.

Robustness:
  * Split timeouts — fast TCP/SSL connect, separate (moderate) read timeout.
    A JUDO server outage (socket connects but no HTTP answer) then fails in
    ~20 s instead of hanging 30 s.
  * DNS first, hardcoded IP fallback. Only connection-level failures retry the
    next IP; the HTTP phase runs once so a slow relay never double-times-out.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import socket
import ssl
import time
import urllib.parse

from .const import API_CONNECT_TIMEOUT, API_HOST, API_IP, API_PORT, API_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)

# Units per command — only for the debug log, so values read nicely
# (e.g. "65 L/d" instead of just "65"). Commands not listed have no unit.
_UNITS: dict[str, str] = {
    "water total": "L",
    "water current": "L/h",
    "water average": "L/d",
    "water daily": "L",
    "water weekly": "L",
    "water monthly": "L",
    "water yearly": "L",
    "actual quantity": "mL",
    "dilution quantity": "mL",
    "rfid tank type": "mL",
    "natural hardness": "°dH",
    "dilution range": "Tage",
}


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
    """TCP + SSL handshake to one IP, using the short connect timeout.

    SNI uses API_HOST. After the handshake the socket is switched to the
    (longer) read timeout for the HTTP phase. Raises on failure.
    """
    raw = socket.create_connection((ip, API_PORT), timeout=API_CONNECT_TIMEOUT)
    try:
        ssl_sock = ctx.wrap_socket(raw, server_hostname=API_HOST)
    except Exception:
        try:
            raw.close()
        except Exception:
            pass
        raise
    # Reads (waiting for the device relay) get the longer timeout.
    ssl_sock.settimeout(API_TIMEOUT)
    return ssl_sock


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
            headers={
                "User-Agent": _UA,
                "Accept": "application/json",
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            _LOGGER.warning(
                "JUDO [%s] HTTP %s response", params.get("command", "?"), resp.status
            )
            return {}
        if not body:
            return {}
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
    except (TimeoutError, socket.timeout) as exc:
        _LOGGER.warning("JUDO [%s] no response from server (timeout) via %s", cmd, used_ip)
        raise
    except Exception as exc:
        _LOGGER.warning(
            "JUDO [%s] HTTP failed via %s: %s - %s",
            cmd, used_ip, type(exc).__name__, exc,
        )
        raise


async def judo_get(params: dict) -> dict:
    """Async wrapper — runs the blocking request in a thread (non-blocking for HA).

    One-shot: opens a fresh connection per call. Kept for the config flow.
    For a full poll, prefer JudoSession (keep-alive) below.
    """
    try:
        return await asyncio.to_thread(_sync_request, params)
    except Exception:
        # Detailed logging already done inside _sync_request.
        return {}


# ---------------------------------------------------------------------------
# Keep-alive session: reuse ONE TLS connection for an entire poll cycle.
# The JUDO relay only handles one request at a time anyway (so we stay
# sequential), but reusing the socket saves ~22 TLS handshakes + DNS lookups
# per poll and removes the per-request "DNS resolved" log spam.
# ---------------------------------------------------------------------------
class JudoSession:
    """Holds one open SSL connection and sends requests over it sequentially."""

    def __init__(self) -> None:
        self._ctx = _make_ssl_ctx()
        self._sock: ssl.SSLSocket | None = None
        self._used_ip: str | None = None
        # Per-poll statistics (for the debug summary)
        self.req_count = 0
        self.ok_count = 0
        self.reconnects = 0
        self.handshakes = 0

    def _connect_sync(self) -> None:
        """Open a TCP+SSL connection, trying DNS IPs then the fallback IP."""
        last_exc: Exception | None = None
        for ip in _candidate_ips():
            try:
                self._sock = _connect(ip, self._ctx)
                self._used_ip = ip
                self.handshakes += 1
                _LOGGER.debug(
                    "JUDO  🔗 verbunden mit %s · TLS %s",
                    ip, self._sock.cipher()[0] if self._sock.cipher() else "?",
                )
                return
            except Exception as exc:
                last_exc = exc
                _LOGGER.debug("JUDO  ❌ Verbindung zu %s fehlgeschlagen: %s", ip, type(exc).__name__)
        raise last_exc if last_exc else OSError("no candidate hosts")

    def _request_sync(self, params: dict) -> dict:
        """Send one request over the (kept-alive) socket; reconnect once on drop."""
        cmd = params.get("command", "?")
        group = params.get("group", "?")
        idx = self.req_count + 1  # provisional; committed once a response arrives
        t0 = time.monotonic()
        for attempt in (1, 2):
            if self._sock is None:
                # A connect failure here propagates to session.get() -> {}.
                # req_count is only incremented after a real HTTP response,
                # so connect-only failures don't skew the stats.
                self._connect_sync()
            conn = http.client.HTTPSConnection(
                API_HOST, API_PORT, context=self._ctx, timeout=API_TIMEOUT
            )
            conn.sock = self._sock
            try:
                query = urllib.parse.urlencode(params)
                conn.request(
                    "GET",
                    "/?" + query,
                    headers={
                        "User-Agent": _UA,
                        "Accept": "application/json",
                        "Connection": "keep-alive",
                    },
                )
                resp = conn.getresponse()
                body = resp.read()
                conn.sock = None  # detach so conn.close() does NOT close it
                self.req_count += 1  # a real response arrived -> count it
                dt = time.monotonic() - t0
                if resp.status != 200:
                    _LOGGER.warning("JUDO #%02d [%s/%s] HTTP %s (%.2fs)",
                                    idx, group, cmd, resp.status, dt)
                    return {}
                data = json.loads(body.decode()) if body else {}
                status = data.get("status", "?")
                value = data.get("data", "")
                if status == "ok":
                    self.ok_count += 1
                # Short value preview with unit (the device returns small values)
                preview = str(value).strip()
                if len(preview) > 30:
                    preview = preview[:30] + "…"
                unit = _UNITS.get(cmd, "")
                shown = f"{preview} {unit}".strip() if preview else "(leer)"
                _LOGGER.debug("JUDO  #%02d  %-13s %-26s →  %-12s  %5.2fs",
                              idx, group, cmd, shown, dt)
                return data
            except (BrokenPipeError, ConnectionResetError, http.client.RemoteDisconnected,
                    OSError) as exc:
                conn.sock = None
                self.close()
                if attempt == 2:
                    _LOGGER.warning("JUDO #%02d [%s/%s] Verbindung verloren: %s",
                                    idx, group, cmd, type(exc).__name__)
                    raise
                self.reconnects += 1
                _LOGGER.debug("JUDO #%02d [%s/%s] Socket abgebrochen (%s) – reconnect",
                              idx, group, cmd, type(exc).__name__)
            except (TimeoutError, socket.timeout):
                conn.sock = None
                _LOGGER.warning("JUDO #%02d [%s/%s] keine Antwort (Timeout nach %.0fs)",
                                idx, group, cmd, time.monotonic() - t0)
                raise
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        return {}

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    async def get(self, params: dict) -> dict:
        """Async wrapper for one keep-alive request."""
        try:
            return await asyncio.to_thread(self._request_sync, params)
        except Exception:
            return {}

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)
