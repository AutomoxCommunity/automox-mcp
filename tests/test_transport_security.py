"""Tests for transport security middleware (DNS rebinding protection & security headers)."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from automox_mcp.transport_security import (
    DNSRebindingProtectionMiddleware,
    SecurityHeadersMiddleware,
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
        assert "::1:8000" in allowed_hosts

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
