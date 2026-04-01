"""Tests for transport security middleware (DNS rebinding protection & security headers)."""

from __future__ import annotations

import time

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from automox_mcp.transport_security import (
    AuthRateLimitMiddleware,
    DNSRebindingProtectionMiddleware,
    SecurityHeadersMiddleware,
    _env_flag,
    build_transport_security_middleware,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _echo_app(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _make_client(
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
    include_security_headers: bool = False,
) -> TestClient:
    """Build a Starlette test client with the DNS rebinding middleware."""
    middleware = []
    if include_security_headers:
        middleware.append(Middleware(SecurityHeadersMiddleware))
    middleware.append(
        Middleware(
            DNSRebindingProtectionMiddleware,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
    )
    app = Starlette(
        routes=[Route("/", _echo_app)],
        middleware=middleware,
    )
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_headers_are_set(self):
        app = Starlette(
            routes=[Route("/", _echo_app)],
            middleware=[Middleware(SecurityHeadersMiddleware)],
        )
        client = TestClient(app)
        resp = client.get("/")

        assert resp.status_code == 200
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["cache-control"] == "no-store"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
        assert "permissions-policy" in resp.headers


# ---------------------------------------------------------------------------
# DNSRebindingProtectionMiddleware — Host validation
# ---------------------------------------------------------------------------


class TestHostValidation:
    def test_allowed_host_passes(self):
        client = _make_client(allowed_hosts=["localhost:8000"])
        resp = client.get("/", headers={"host": "localhost:8000"})
        assert resp.status_code == 200

    def test_disallowed_host_returns_421(self):
        client = _make_client(allowed_hosts=["localhost:8000"])
        resp = client.get("/", headers={"host": "evil.com:8000"})
        assert resp.status_code == 421

    def test_wildcard_port_match(self):
        client = _make_client(allowed_hosts=["localhost:*"])
        resp = client.get("/", headers={"host": "localhost:9999"})
        assert resp.status_code == 200

    def test_wildcard_port_no_match_different_host(self):
        client = _make_client(allowed_hosts=["localhost:*"])
        resp = client.get("/", headers={"host": "evil.com:9999"})
        assert resp.status_code == 421

    def test_multiple_allowed_hosts(self):
        client = _make_client(allowed_hosts=["127.0.0.1:8000", "localhost:8000"])
        assert client.get("/", headers={"host": "127.0.0.1:8000"}).status_code == 200
        assert client.get("/", headers={"host": "localhost:8000"}).status_code == 200
        assert client.get("/", headers={"host": "0.0.0.0:8000"}).status_code == 421


# ---------------------------------------------------------------------------
# DNSRebindingProtectionMiddleware — Origin validation
# ---------------------------------------------------------------------------


class TestOriginValidation:
    def test_no_origin_header_passes(self):
        """Same-origin requests have no Origin header — should be allowed."""
        client = _make_client(
            allowed_hosts=["testserver"],
            allowed_origins=["http://localhost:8000"],
        )
        resp = client.get("/")
        assert resp.status_code == 200

    def test_allowed_origin_passes(self):
        client = _make_client(
            allowed_hosts=["testserver"],
            allowed_origins=["http://localhost:3000"],
        )
        resp = client.get("/", headers={"origin": "http://localhost:3000"})
        assert resp.status_code == 200

    def test_disallowed_origin_returns_403(self):
        client = _make_client(
            allowed_hosts=["testserver"],
            allowed_origins=["http://localhost:3000"],
        )
        resp = client.get("/", headers={"origin": "http://evil.com"})
        assert resp.status_code == 403

    def test_wildcard_port_origin(self):
        client = _make_client(
            allowed_hosts=["testserver"],
            allowed_origins=["http://localhost:*"],
        )
        resp = client.get("/", headers={"origin": "http://localhost:9999"})
        assert resp.status_code == 200

    def test_wildcard_origin_port_rejects_different_host(self):
        client = _make_client(
            allowed_hosts=["testserver"],
            allowed_origins=["http://localhost:*"],
        )
        resp = client.get("/", headers={"origin": "http://evil.com:9999"})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Combined middleware stack
# ---------------------------------------------------------------------------


class TestCombinedStack:
    def test_security_headers_with_dns_protection(self):
        client = _make_client(
            allowed_hosts=["testserver"],
            allowed_origins=["http://testserver"],
            include_security_headers=True,
        )
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_rejected_request_still_gets_json_error(self):
        client = _make_client(allowed_hosts=["localhost:8000"])
        resp = client.get("/", headers={"host": "evil.com"})
        assert resp.status_code == 421
        assert "invalid Host" in resp.text


# ---------------------------------------------------------------------------
# build_transport_security_middleware factory
# ---------------------------------------------------------------------------


class TestBuildMiddleware:
    def test_default_includes_both_middlewares(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_HOSTS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_ORIGINS", raising=False)

        mw = build_transport_security_middleware(host="127.0.0.1", port=8000)
        classes = [m.cls.__name__ for m in mw]
        assert "SecurityHeadersMiddleware" in classes
        assert "DNSRebindingProtectionMiddleware" in classes

    @staticmethod
    def _find_dns_mw(mw_list):
        """Find the DNSRebindingProtectionMiddleware entry in the middleware list."""
        for m in mw_list:
            if m.cls.__name__ == "DNSRebindingProtectionMiddleware":
                return m
        return None

    def test_loopback_includes_aliases(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_HOSTS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_ORIGINS", raising=False)

        mw = build_transport_security_middleware(host="127.0.0.1", port=8000)
        dns_mw = self._find_dns_mw(mw)
        assert dns_mw is not None
        allowed_hosts = dns_mw.kwargs["allowed_hosts"]
        assert "127.0.0.1:8000" in allowed_hosts
        assert "localhost:8000" in allowed_hosts
        assert "[::1]:8000" in allowed_hosts

    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", "false")
        mw = build_transport_security_middleware(host="127.0.0.1", port=8000)
        classes = [m.cls.__name__ for m in mw]
        assert "SecurityHeadersMiddleware" in classes
        assert "DNSRebindingProtectionMiddleware" not in classes

    def test_extra_allowed_hosts(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", raising=False)
        monkeypatch.setenv("AUTOMOX_MCP_ALLOWED_HOSTS", "proxy.internal:443,cdn.example.com:443")
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_ORIGINS", raising=False)

        mw = build_transport_security_middleware(host="0.0.0.0", port=8000)
        dns_mw = self._find_dns_mw(mw)
        assert dns_mw is not None
        allowed_hosts = dns_mw.kwargs["allowed_hosts"]
        assert "proxy.internal:443" in allowed_hosts
        assert "cdn.example.com:443" in allowed_hosts

    def test_extra_allowed_origins(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_HOSTS", raising=False)
        monkeypatch.setenv("AUTOMOX_MCP_ALLOWED_ORIGINS", "https://app.example.com")

        mw = build_transport_security_middleware(host="0.0.0.0", port=8000)
        dns_mw = self._find_dns_mw(mw)
        assert dns_mw is not None
        allowed_origins = dns_mw.kwargs["allowed_origins"]
        assert "https://app.example.com" in allowed_origins


# ---------------------------------------------------------------------------
# _env_flag helper
# ---------------------------------------------------------------------------


class TestEnvFlag:
    def test_truthy_values(self, monkeypatch):
        for val in ("1", "true", "yes", "on", "TRUE", "Yes"):
            monkeypatch.setenv("TEST_FLAG", val)
            assert _env_flag("TEST_FLAG", default=False) is True

    def test_falsy_values(self, monkeypatch):
        for val in ("0", "false", "no", "off", "FALSE", "No"):
            monkeypatch.setenv("TEST_FLAG", val)
            assert _env_flag("TEST_FLAG", default=True) is False

    def test_empty_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_FLAG", "")
        assert _env_flag("TEST_FLAG", default=True) is True
        assert _env_flag("TEST_FLAG", default=False) is False

    def test_unrecognized_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_FLAG", "maybe")
        assert _env_flag("TEST_FLAG", default=True) is True
        assert _env_flag("TEST_FLAG", default=False) is False


# ---------------------------------------------------------------------------
# DNSRebindingProtectionMiddleware — missing Host header
# ---------------------------------------------------------------------------


class TestMissingHostHeader:
    def test_missing_host_returns_400(self):
        client = _make_client(allowed_hosts=["localhost:8000"])
        resp = client.get("/", headers={"host": ""})
        assert resp.status_code == 400
        assert "missing Host" in resp.text


# ---------------------------------------------------------------------------
# DNSRebindingProtectionMiddleware — IPv6 host parsing
# ---------------------------------------------------------------------------


class TestIPv6HostParsing:
    def test_bracketed_ipv6_host_match(self):
        client = _make_client(allowed_hosts=["[::1]:8000"])
        resp = client.get("/", headers={"host": "[::1]:8000"})
        assert resp.status_code == 200

    def test_bare_ipv6_host_match(self):
        """Bare IPv6 (no brackets) should match when added to allowed_hosts."""
        client = _make_client(allowed_hosts=["::1"])
        resp = client.get("/", headers={"host": "::1"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# AuthRateLimitMiddleware
# ---------------------------------------------------------------------------


def _make_rate_limit_client(
    max_failures: int = 3,
    window_seconds: float = 60.0,
    block_seconds: float = 300.0,
    status_code: int = 401,
) -> TestClient:
    """Build a test client with AuthRateLimitMiddleware in front of a configurable app."""

    def _status_app(request: Request) -> Response:
        code = int(request.query_params.get("status", str(status_code)))
        return PlainTextResponse("response", status_code=code)

    app = Starlette(
        routes=[Route("/", _status_app)],
        middleware=[
            Middleware(
                AuthRateLimitMiddleware,
                max_failures=max_failures,
                window_seconds=window_seconds,
                block_seconds=block_seconds,
            )
        ],
    )
    return TestClient(app, raise_server_exceptions=False)


class TestAuthRateLimitMiddleware:
    def test_successful_requests_not_blocked(self):
        client = _make_rate_limit_client(max_failures=3, status_code=200)
        for _ in range(10):
            resp = client.get("/?status=200")
            assert resp.status_code == 200

    def test_auth_failures_tracked_and_blocked(self):
        client = _make_rate_limit_client(max_failures=3, block_seconds=300.0)
        # First 3 failures should pass through
        for _ in range(3):
            resp = client.get("/?status=401")
            assert resp.status_code == 401
        # 4th request should be blocked with 429
        resp = client.get("/?status=401")
        assert resp.status_code == 429
        assert "Too many" in resp.text

    def test_403_also_counted_as_failure(self):
        client = _make_rate_limit_client(max_failures=2, block_seconds=300.0)
        client.get("/?status=403")
        client.get("/?status=403")
        resp = client.get("/?status=403")
        assert resp.status_code == 429

    def test_block_expires(self, monkeypatch):
        mw = AuthRateLimitMiddleware.__new__(AuthRateLimitMiddleware)
        mw.app = None
        mw.max_failures = 2
        mw.window_seconds = 60.0
        mw.block_seconds = 10.0
        mw._failures = {}
        now = time.monotonic()
        mw._blocked_until = {"1.2.3.4": now - 1}  # already expired
        mw._last_cleanup = now - mw.window_seconds - 1  # ensure cleanup runs

        # After block expires, _blocked_until entry should get cleaned up
        mw._cleanup_stale_entries(now)
        assert "1.2.3.4" not in mw._blocked_until

    def test_cleanup_evicts_stale_failures(self):
        from collections import defaultdict, deque

        mw = AuthRateLimitMiddleware.__new__(AuthRateLimitMiddleware)
        mw.app = None
        mw.max_failures = 5
        mw.window_seconds = 60.0
        mw.block_seconds = 300.0
        mw._failures = defaultdict(deque)
        mw._blocked_until = {}

        now = time.monotonic()
        mw._last_cleanup = now - mw.window_seconds - 1  # ensure cleanup runs
        # Add failures that are outside the window
        mw._failures["old-ip"] = deque([now - 120, now - 100])
        mw._cleanup_stale_entries(now)
        # Old entries should be evicted
        assert "old-ip" not in mw._failures

    def test_cleanup_hard_cap(self):
        from collections import defaultdict, deque

        mw = AuthRateLimitMiddleware.__new__(AuthRateLimitMiddleware)
        mw.app = None
        mw.max_failures = 5
        mw.window_seconds = 60.0
        mw.block_seconds = 300.0

        now = time.monotonic()
        mw._last_cleanup = now - mw.window_seconds - 1  # ensure cleanup runs
        # Fill beyond the hard cap with blocked entries
        mw._blocked_until = {f"ip-{i}": now + i for i in range(mw._MAX_TRACKED_IPS + 50)}
        mw._failures = defaultdict(deque)
        mw._cleanup_stale_entries(now)
        total = len(mw._failures) + len(mw._blocked_until)
        assert total <= mw._MAX_TRACKED_IPS

    def test_cleanup_hard_cap_failure_overflow(self):
        from collections import defaultdict, deque

        mw = AuthRateLimitMiddleware.__new__(AuthRateLimitMiddleware)
        mw.app = None
        mw.max_failures = 5
        mw.window_seconds = 60.0
        mw.block_seconds = 300.0

        now = time.monotonic()
        mw._last_cleanup = now - mw.window_seconds - 1  # ensure cleanup runs
        mw._blocked_until = {}
        # Fill failures beyond the hard cap
        mw._failures = defaultdict(deque)
        for i in range(mw._MAX_TRACKED_IPS + 50):
            mw._failures[f"ip-{i}"] = deque([now - 1])
        mw._cleanup_stale_entries(now)
        total = len(mw._failures) + len(mw._blocked_until)
        assert total <= mw._MAX_TRACKED_IPS

    def test_get_client_ip_with_no_client(self):
        mw = AuthRateLimitMiddleware.__new__(AuthRateLimitMiddleware)
        assert mw._get_client_ip({}) == "unknown"

    def test_get_client_ip_with_client(self):
        mw = AuthRateLimitMiddleware.__new__(AuthRateLimitMiddleware)
        assert mw._get_client_ip({"client": ("10.0.0.1", 12345)}) == "10.0.0.1"

    def test_mixed_success_and_failure(self):
        client = _make_rate_limit_client(max_failures=3, block_seconds=300.0)
        # Successful requests don't count toward the limit
        client.get("/?status=200")
        client.get("/?status=401")
        client.get("/?status=200")
        client.get("/?status=401")
        client.get("/?status=401")
        # 3 failures reached — next request should be blocked
        resp = client.get("/?status=200")
        assert resp.status_code == 429
