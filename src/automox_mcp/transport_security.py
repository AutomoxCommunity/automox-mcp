"""Transport-level security middleware for HTTP/SSE transports.

Implements:
- DNS rebinding protection (Origin/Host header validation) per MCP transport spec
- HTTP security response headers (defence-in-depth)

Configuration via environment variables:

    AUTOMOX_MCP_ALLOWED_ORIGINS   Comma-separated list of allowed Origin header
                                  values (e.g. "https://app.example.com").
                                  Automatically includes the server's own origin.

    AUTOMOX_MCP_ALLOWED_HOSTS     Comma-separated list of additional allowed Host
                                  header values.  The server's own host:port is
                                  always allowed.

    AUTOMOX_MCP_DNS_REBINDING_PROTECTION
                                  Set to "false" to disable DNS rebinding checks
                                  (NOT recommended for production).
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from collections.abc import MutableMapping
from typing import Any

from starlette.middleware import Middleware as ASGIMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import env_list

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security response headers middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware:
    """ASGI middleware that injects security-related HTTP response headers.

    Headers added:
      - X-Content-Type-Options: nosniff
      - X-Frame-Options: DENY
      - Cache-Control: no-store (prevents caching of API responses)
      - Referrer-Policy: strict-origin-when-cross-origin
      - Permissions-Policy: (restrictive default)
      - Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"cache-control", b"no-store"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"permissions-policy", b"microphone=(), camera=(), geolocation=()"),
                        (
                            b"content-security-policy",
                            b"default-src 'none'; frame-ancestors 'none'",
                        ),
                        (
                            b"strict-transport-security",
                            b"max-age=63072000; includeSubDomains",
                        ),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ---------------------------------------------------------------------------
# DNS rebinding protection middleware
# ---------------------------------------------------------------------------


class DNSRebindingProtectionMiddleware:
    """ASGI middleware that validates Host and Origin headers.

    Rejects requests from unexpected hosts/origins to prevent DNS rebinding
    attacks, as required by the MCP Streamable HTTP transport specification.

    Returns:
      - 421 Misdirected Request for invalid Host headers
      - 403 Forbidden for invalid Origin headers
    """

    def __init__(
        self,
        app: ASGIApp,
        allowed_hosts: list[str] | None = None,
        allowed_origins: list[str] | None = None,
    ) -> None:
        self.app = app
        # Normalize to lowercase for case-insensitive matching (RFC 4343)
        self.allowed_hosts: set[str] = {h.lower() for h in (allowed_hosts or [])}
        self.allowed_origins: set[str] = {o.lower() for o in (allowed_origins or [])}

    @staticmethod
    def _parse_host_port(value: str) -> tuple[str, str | None]:
        """Split a Host header into (host, port), handling IPv6 brackets."""
        if value.startswith("["):
            bracket_end = value.find("]")
            if bracket_end != -1:
                host_part = value[: bracket_end + 1]
                rest = value[bracket_end + 1 :]
                port_part = rest[1:] if rest.startswith(":") else None
                return host_part, port_part
        # Detect bare (non-bracketed) IPv6 by counting colons — IPv6 always has 2+
        colon_count = value.count(":")
        if colon_count >= 2:
            # Bare IPv6 address (e.g. "::1") — no port component
            return value, None
        if colon_count == 1:
            parts = value.rsplit(":", 1)
            return parts[0], parts[1]
        return value, None

    def _host_matches(self, host: str) -> bool:
        # Case-insensitive comparison (RFC 4343)
        host_lower = host.lower()
        if host_lower in self.allowed_hosts:
            return True
        # Support wildcard port: "host:*" matches "host:1234"
        host_base, host_port = self._parse_host_port(host_lower)
        for allowed in self.allowed_hosts:
            if allowed.endswith(":*") and host_base == allowed[:-2]:
                # Validate that the port is a valid TCP port number
                if host_port is not None and host_port.isdigit():
                    port_num = int(host_port)
                    if 1 <= port_num <= 65535:
                        return True
        return False

    def _origin_matches(self, origin: str) -> bool:
        # Case-insensitive comparison (RFC 4343)
        origin_lower = origin.lower()
        if origin_lower in self.allowed_origins:
            return True
        # Support wildcard port patterns — verify the suffix is a valid port
        for allowed in self.allowed_origins:
            if allowed.endswith(":*"):
                base = allowed[:-2]
                if origin_lower.startswith(base + ":"):
                    port_suffix = origin_lower[len(base) + 1 :]
                    if port_suffix.isdigit():
                        port_num = int(port_suffix)
                        if 1 <= port_num <= 65535:
                            return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        # Validate Host header (V-123: reject missing Host to prevent bypass)
        host = request.headers.get("host")
        if not host:
            logger.warning("DNS rebinding protection: rejected request with missing Host header")
            response = Response(
                content='{"error": "Bad request — missing Host header"}',
                status_code=400,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return
        if not self._host_matches(host):
            logger.warning("DNS rebinding protection: rejected Host header %r", host)
            response = Response(
                content='{"error": "Misdirected request — invalid Host header"}',
                status_code=421,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        # Validate Origin header (absent Origin is OK for same-origin requests)
        origin = request.headers.get("origin")
        if origin and not self._origin_matches(origin):
            logger.warning("DNS rebinding protection: rejected Origin header %r", origin)
            response = Response(
                content='{"error": "Forbidden — invalid Origin header"}',
                status_code=403,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Authentication rate-limiting middleware
# ---------------------------------------------------------------------------


class AuthRateLimitMiddleware:
    """ASGI middleware that rate-limits authentication failures per client IP.

    Tracks 401/403 responses and blocks clients that exceed the threshold
    within the configured window. This mitigates brute-force attacks against
    static API keys and JWT tokens.
    """

    _MAX_TRACKED_IPS = 10_000  # Cap to prevent memory exhaustion from IP rotation attacks

    def __init__(
        self,
        app: ASGIApp,
        max_failures: int = 10,
        window_seconds: float = 60.0,
        block_seconds: float = 300.0,
    ) -> None:
        self.app = app
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}
        self._last_cleanup: float = 0.0

    def _get_client_ip(self, scope: Scope) -> str:
        client = scope.get("client")
        if client:
            return str(client[0])
        return "unknown"

    def _cleanup_stale_entries(self, now: float) -> None:
        """Periodically evict expired blocks and empty failure deques."""
        # Run cleanup at most once per window_seconds
        if now - self._last_cleanup < self.window_seconds:
            return
        self._last_cleanup = now

        # Evict expired _blocked_until entries
        expired_blocks = [ip for ip, until in self._blocked_until.items() if now >= until]
        for ip in expired_blocks:
            del self._blocked_until[ip]

        # Evict empty or fully-expired failure deques
        cutoff = now - self.window_seconds
        stale_failures = []
        for ip, dq in self._failures.items():
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                stale_failures.append(ip)
        for ip in stale_failures:
            del self._failures[ip]

        # Hard cap: if still over limit, drop oldest entries
        total = len(self._failures) + len(self._blocked_until)
        if total > self._MAX_TRACKED_IPS:
            overflow = total - self._MAX_TRACKED_IPS
            # Evict oldest blocked entries first (sorted by expiry)
            for ip in sorted(self._blocked_until, key=self._blocked_until.get)[:overflow]:  # type: ignore[arg-type]
                del self._blocked_until[ip]
                overflow -= 1
                if overflow <= 0:
                    break
            # If still over cap, evict oldest failure entries (by earliest timestamp)
            if overflow > 0:
                evict_key = lambda k: self._failures[k][0] if self._failures[k] else 0  # noqa: E731
                for ip in sorted(self._failures, key=evict_key)[:overflow]:
                    del self._failures[ip]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(scope)
        now = time.monotonic()

        # Periodically clean up stale entries to prevent memory exhaustion
        self._cleanup_stale_entries(now)

        # Check if client is blocked
        blocked_until = self._blocked_until.get(client_ip, 0)
        if now < blocked_until:
            logger.warning(
                "Auth rate limit: blocking request from %s (blocked for %.0fs more)",
                client_ip,
                blocked_until - now,
            )
            response = Response(
                content='{"error": "Too many authentication failures. Try again later."}',
                status_code=429,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        # Track response status
        response_status: list[int] = []

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_status.append(message.get("status", 200))
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # Record auth failures (401 or 403)
        if response_status and response_status[0] in (401, 403):
            failures = self._failures[client_ip]
            failures.append(now)
            # Evict old entries outside the window
            cutoff = now - self.window_seconds
            while failures and failures[0] < cutoff:
                failures.popleft()
            if len(failures) >= self.max_failures:
                self._blocked_until[client_ip] = now + self.block_seconds
                logger.warning(
                    "Auth rate limit: blocking %s for %.0fs after %d failures",
                    client_ip,
                    self.block_seconds,
                    len(failures),
                )
                # Clean up failures tracking for this IP
                del self._failures[client_ip]


# ---------------------------------------------------------------------------
# Factory: build middleware list from environment & server configuration
# ---------------------------------------------------------------------------

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def build_transport_security_middleware(
    host: str = "127.0.0.1",
    port: int = 8000,
) -> list[ASGIMiddleware]:
    """Build a list of Starlette ``Middleware`` instances for transport security.

    Always includes ``SecurityHeadersMiddleware``.  Adds
    ``DNSRebindingProtectionMiddleware`` unless explicitly disabled via
    ``AUTOMOX_MCP_DNS_REBINDING_PROTECTION=false``.
    """
    middlewares: list[ASGIMiddleware] = []

    # --- Security headers (always on) ---
    middlewares.append(ASGIMiddleware(SecurityHeadersMiddleware))

    # --- Auth rate limiting (always on for HTTP/SSE) ---
    middlewares.append(ASGIMiddleware(AuthRateLimitMiddleware))

    # --- DNS rebinding protection ---
    dns_protection = _env_flag("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", default=True)
    if not dns_protection:
        logger.warning(
            "DNS rebinding protection is DISABLED via "
            "AUTOMOX_MCP_DNS_REBINDING_PROTECTION=false. "
            "This is NOT recommended for production."
        )
        return middlewares

    # Build allowed hosts
    allowed_hosts: list[str] = []

    def _add_host_variants(h: str, p: int) -> None:
        """Add a host:port entry, plus bracket variant for IPv6."""
        if ":" in h and not h.startswith("["):
            # Bare IPv6: add both bracketed form (standard) and bare form
            allowed_hosts.append(f"[{h}]:{p}")
            allowed_hosts.append(h)  # bare IPv6 without port
        else:
            allowed_hosts.append(f"{h}:{p}")

    # Always allow the bound host:port
    _add_host_variants(host, port)
    # For loopback, also allow common aliases
    if host in _LOOPBACK_HOSTS:
        for lb in _LOOPBACK_HOSTS:
            _add_host_variants(lb, port)
    # For wildcard bind addresses, also add loopback aliases
    if host in {"0.0.0.0", "::"}:
        for lb in _LOOPBACK_HOSTS:
            _add_host_variants(lb, port)
    # User-supplied extras
    allowed_hosts.extend(env_list("AUTOMOX_MCP_ALLOWED_HOSTS"))

    # Build allowed origins
    allowed_origins: list[str] = []

    def _add_origin_variants(h: str, p: int) -> None:
        """Add http://host:port origin, plus bracket variant for IPv6."""
        if ":" in h and not h.startswith("["):
            # IPv6: browsers use bracketed form in Origin headers
            allowed_origins.append(f"http://[{h}]:{p}")
        else:
            allowed_origins.append(f"http://{h}:{p}")

    # Allow the server's own origin
    _add_origin_variants(host, port)
    if host in _LOOPBACK_HOSTS:
        for lb in _LOOPBACK_HOSTS:
            _add_origin_variants(lb, port)
    if host in {"0.0.0.0", "::"}:
        for lb in _LOOPBACK_HOSTS:
            _add_origin_variants(lb, port)
    # User-supplied extras (e.g. "https://app.example.com")
    allowed_origins.extend(env_list("AUTOMOX_MCP_ALLOWED_ORIGINS"))

    logger.info(
        "DNS rebinding protection enabled — allowed_hosts=%s, allowed_origins=%s",
        allowed_hosts,
        allowed_origins,
    )

    middlewares.append(
        ASGIMiddleware(
            DNSRebindingProtectionMiddleware,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
    )

    return middlewares


__all__ = [
    "AuthRateLimitMiddleware",
    "DNSRebindingProtectionMiddleware",
    "SecurityHeadersMiddleware",
    "build_transport_security_middleware",
]
