"""Regression tests for the auth/transport hardening fixes.

Covers two bugs in ``automox_mcp.transport_security`` (audited at v2.2.2, file
unchanged since):

- transport-security rejections (invalid Origin / DNS-rebinding 403) must
  NOT be counted as auth failures by ``AuthRateLimitMiddleware`` — otherwise a
  misconfigured client gets IP-blocked and an attacker has a cheap DoS lever.
  Genuine auth 401/403s must STILL count (DoS protection preserved).
- the auto-derived origin allowlist must include an ``https://{host}``
  (default-port) entry so a same-host HTTPS browser Origin matches.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from automox_mcp.transport_security import build_transport_security_middleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Loopback bind: factory auto-allowlists "localhost:8000" host and origins, so a
# request with a valid Host survives DNS-rebinding validation and reaches the
# inner app, while a bad Origin is rejected by the DNS middleware.
_HOST = "127.0.0.1"
_PORT = 8000
_VALID_HOST = "localhost:8000"


def _build_stack_client(
    monkeypatch,
    *,
    max_failures: int,
    inner_status: int = 200,
) -> TestClient:
    """Assemble the real factory middleware stack in front of a configurable app.

    The inner app echoes ``?status=`` so a test can simulate a genuine auth
    failure originating *inside* the stack (past DNS validation), which is what
    must still reach the rate limiter.
    """
    monkeypatch.delenv("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_ORIGINS", raising=False)

    middleware = build_transport_security_middleware(host=_HOST, port=_PORT)
    # Tighten the limiter's threshold for the test without touching the order the
    # factory produced (DNS outermost, rate limiter innermost).
    for m in middleware:
        if m.cls.__name__ == "AuthRateLimitMiddleware":
            m.kwargs["max_failures"] = max_failures
            m.kwargs["block_seconds"] = 300.0

    def _status_app(request: Request) -> Response:
        code = int(request.query_params.get("status", str(inner_status)))
        return PlainTextResponse("response", status_code=code)

    app = Starlette(routes=[Route("/", _status_app)], middleware=middleware)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# transport rejections are not counted; genuine auth failures still are
# ---------------------------------------------------------------------------


class TestTransportRejectionsNotRateLimited:
    def test_invalid_origin_403s_do_not_block_client(self, monkeypatch):
        """Repeated invalid-Origin 403s (a transport error) must not IP-block."""
        client = _build_stack_client(monkeypatch, max_failures=3)

        # Fire well past the limiter threshold; every one is a DNS-layer 403.
        for _ in range(10):
            resp = client.get(
                "/",
                headers={"host": _VALID_HOST, "origin": "http://evil.example.com"},
            )
            assert resp.status_code == 403

        # A clean same-host request must still succeed — the client is NOT blocked
        # (a 429 here would prove the transport 403s were miscounted as auth fails).
        resp = client.get("/", headers={"host": _VALID_HOST})
        assert resp.status_code == 200

    def test_genuine_auth_failures_still_block_client(self, monkeypatch):
        """403s that pass transport validation (from the app) must still count."""
        client = _build_stack_client(monkeypatch, max_failures=3)

        # These have a valid Host and no Origin, so they clear the DNS middleware
        # and reach the inner app, which returns a genuine auth 403.
        for _ in range(3):
            resp = client.get("/?status=403", headers={"host": _VALID_HOST})
            assert resp.status_code == 403

        # Threshold reached — the next request is rate-limited (429).
        resp = client.get("/?status=200", headers={"host": _VALID_HOST})
        assert resp.status_code == 429
        assert "Too many" in resp.text

    def test_genuine_auth_401s_still_block_client(self, monkeypatch):
        """401s from the app (real auth failures) must also count toward the limit."""
        client = _build_stack_client(monkeypatch, max_failures=2)

        for _ in range(2):
            resp = client.get("/?status=401", headers={"host": _VALID_HOST})
            assert resp.status_code == 401

        resp = client.get("/?status=200", headers={"host": _VALID_HOST})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# auto-allowlist includes an https://{host} (default-port) origin
# ---------------------------------------------------------------------------


class TestHttpsDefaultPortOriginVariant:
    @staticmethod
    def _origins_for(host: str, port: int, monkeypatch) -> set[str]:
        monkeypatch.delenv("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_HOSTS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_ORIGINS", raising=False)
        mw = build_transport_security_middleware(host=host, port=port)
        for m in mw:
            if m.cls.__name__ == "DNSRebindingProtectionMiddleware":
                return set(m.kwargs["allowed_origins"])
        raise AssertionError("DNSRebindingProtectionMiddleware not built")

    def test_https_default_port_origin_present(self, monkeypatch):
        """A same-host HTTPS client sends ``https://host`` (443 omitted)."""
        origins = self._origins_for("127.0.0.1", 443, monkeypatch)
        # Default-port HTTPS form for the bound host and its loopback aliases.
        assert "https://127.0.0.1" in origins
        assert "https://localhost" in origins

    def test_http_explicit_port_origin_still_present(self, monkeypatch):
        """The existing http://host:port form must be preserved."""
        origins = self._origins_for("127.0.0.1", 8000, monkeypatch)
        assert "http://127.0.0.1:8000" in origins

    def test_https_origin_matches_same_host_browser(self, monkeypatch):
        """End-to-end: a same-host HTTPS Origin clears DNS-rebinding validation."""
        monkeypatch.delenv("AUTOMOX_MCP_DNS_REBINDING_PROTECTION", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_HOSTS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_ALLOWED_ORIGINS", raising=False)
        mw = build_transport_security_middleware(host="127.0.0.1", port=443)
        app = Starlette(
            routes=[Route("/", lambda r: PlainTextResponse("ok"))],
            middleware=mw,
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/",
            headers={"host": "localhost:443", "origin": "https://localhost"},
        )
        assert resp.status_code == 200
