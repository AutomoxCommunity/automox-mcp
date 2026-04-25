"""Tests for OAuth 2.1 / JWT authentication provider."""

from __future__ import annotations

import time
from unittest.mock import patch

import httpx
import pytest

from automox_mcp.auth import (
    _create_jwt_auth,
    create_auth_provider,
    is_auth_configured,
)

# ---------------------------------------------------------------------------
# _create_jwt_auth
# ---------------------------------------------------------------------------


class TestCreateJwtAuth:
    """Tests for the JWT auth provider factory."""

    def _clear_oauth_env(self, monkeypatch):
        for var in [
            "AUTOMOX_MCP_OAUTH_ISSUER",
            "AUTOMOX_MCP_OAUTH_JWKS_URI",
            "AUTOMOX_MCP_OAUTH_PUBLIC_KEY",
            "AUTOMOX_MCP_OAUTH_AUDIENCE",
            "AUTOMOX_MCP_OAUTH_ALGORITHM",
            "AUTOMOX_MCP_OAUTH_SCOPES",
            "AUTOMOX_MCP_OAUTH_SERVER_URL",
            "AUTOMOX_MCP_API_KEYS",
            "AUTOMOX_MCP_API_KEY_FILE",
        ]:
            monkeypatch.delenv(var, raising=False)

    def test_returns_none_without_issuer(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        assert _create_jwt_auth() is None

    def test_creates_jwt_verifier_with_jwks(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv(
            "AUTOMOX_MCP_OAUTH_JWKS_URI",
            "https://auth.example.com/.well-known/jwks.json",
        )
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")

        provider = _create_jwt_auth()
        assert provider is not None
        # Without AUTOMOX_MCP_OAUTH_SERVER_URL, returns bare JWTVerifier
        assert type(provider).__name__ == "JWTVerifier"

    def test_creates_remote_auth_provider_with_server_url(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv(
            "AUTOMOX_MCP_OAUTH_JWKS_URI",
            "https://auth.example.com/.well-known/jwks.json",
        )
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_SERVER_URL", "https://mcp.example.com")

        provider = _create_jwt_auth()
        assert provider is not None
        assert type(provider).__name__ == "RemoteAuthProvider"

    def test_remote_auth_provider_exposes_rfc9728_routes(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv(
            "AUTOMOX_MCP_OAUTH_JWKS_URI",
            "https://auth.example.com/.well-known/jwks.json",
        )
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_SERVER_URL", "https://mcp.example.com")

        provider = _create_jwt_auth()
        routes = provider.get_routes(mcp_path="/mcp")
        assert len(routes) >= 1
        paths = [r.path for r in routes]
        assert any(".well-known/oauth-protected-resource" in p for p in paths)

    def test_auto_derives_jwks_uri_from_issuer(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")
        # No JWKS_URI and no PUBLIC_KEY — should auto-derive via OIDC discovery

        # Mock the OIDC discovery fetch to return a valid jwks_uri
        mock_response = httpx.Response(
            200,
            json={"jwks_uri": "https://auth.example.com/.well-known/jwks.json"},
            request=httpx.Request(
                "GET", "https://auth.example.com/.well-known/openid-configuration"
            ),
        )
        with patch("httpx.get", return_value=mock_response):
            provider = _create_jwt_auth()
        assert provider is not None
        # The provider should have been created with the discovered JWKS URI
        assert type(provider).__name__ == "JWTVerifier"
        assert provider.jwks_uri == "https://auth.example.com/.well-known/jwks.json"

    def test_custom_algorithm(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv(
            "AUTOMOX_MCP_OAUTH_JWKS_URI",
            "https://auth.example.com/.well-known/jwks.json",
        )
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ALGORITHM", "ES256")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")

        provider = _create_jwt_auth()
        assert provider is not None
        assert provider.algorithm == "ES256"

    def test_required_scopes(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv(
            "AUTOMOX_MCP_OAUTH_JWKS_URI",
            "https://auth.example.com/.well-known/jwks.json",
        )
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_SCOPES", "mcp:tools,mcp:read")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")

        provider = _create_jwt_auth()
        assert provider is not None
        assert provider.required_scopes == ["mcp:tools", "mcp:read"]

    def test_public_key_inline(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        # Provide a PEM-style public key (fake but structurally valid marker)
        pem = (
            "-----BEGIN PUBLIC KEY-----\n"
            "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...\n"
            "-----END PUBLIC KEY-----"
        )
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_PUBLIC_KEY", pem)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ALGORITHM", "ES256")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")

        provider = _create_jwt_auth()
        assert provider is not None
        assert provider.public_key is not None

    def test_public_key_from_file(self, monkeypatch, tmp_path):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")

        key_file = tmp_path / "pubkey.pem"
        key_content = "-----BEGIN PUBLIC KEY-----\nMFkwEwYH...\n-----END PUBLIC KEY-----"
        key_file.write_text(key_content)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_PUBLIC_KEY", str(key_file))
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ALGORITHM", "ES256")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")

        provider = _create_jwt_auth()
        assert provider is not None
        assert provider.public_key.strip() == key_content.strip()


# ---------------------------------------------------------------------------
# create_auth_provider priority
# ---------------------------------------------------------------------------


class TestAuthProviderPriority:
    """Verify that static keys take precedence over JWT."""

    def _clear_all(self, monkeypatch):
        for var in [
            "AUTOMOX_MCP_API_KEYS",
            "AUTOMOX_MCP_API_KEY_FILE",
            "AUTOMOX_MCP_OAUTH_ISSUER",
            "AUTOMOX_MCP_OAUTH_JWKS_URI",
            "AUTOMOX_MCP_OAUTH_PUBLIC_KEY",
            "AUTOMOX_MCP_OAUTH_AUDIENCE",
            "AUTOMOX_MCP_OAUTH_ALGORITHM",
            "AUTOMOX_MCP_OAUTH_SCOPES",
            "AUTOMOX_MCP_OAUTH_SERVER_URL",
        ]:
            monkeypatch.delenv(var, raising=False)

    def test_static_keys_win_over_jwt(self, monkeypatch):
        self._clear_all(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "test-token")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_JWKS_URI", "https://auth.example.com/jwks")

        provider = create_auth_provider()
        assert type(provider).__name__ == "StaticTokenVerifier"

    def test_jwt_used_when_no_static_keys(self, monkeypatch):
        self._clear_all(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_JWKS_URI", "https://auth.example.com/jwks")
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")

        provider = create_auth_provider()
        assert type(provider).__name__ == "JWTVerifier"

    def test_none_when_nothing_configured(self, monkeypatch):
        self._clear_all(monkeypatch)
        assert create_auth_provider() is None


# ---------------------------------------------------------------------------
# is_auth_configured
# ---------------------------------------------------------------------------


class TestIsAuthConfiguredJwt:
    def test_true_with_oauth_issuer(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_API_KEYS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_API_KEY_FILE", raising=False)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        assert is_auth_configured() is True

    def test_false_when_nothing(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_API_KEYS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_API_KEY_FILE", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_OAUTH_ISSUER", raising=False)
        assert is_auth_configured() is False


# ---------------------------------------------------------------------------
# JWT verify_token() integration tests
# ---------------------------------------------------------------------------


def _generate_ec_key_pair() -> tuple[str, str]:
    """Generate an EC P-256 key pair and return (private_pem, public_pem)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _make_jwt(
    private_pem: str,
    *,
    issuer: str = "https://auth.example.com",
    audience: str = "https://mcp.example.com",
    subject: str = "test-client",
    scopes: str = "",
    exp_offset: int = 3600,
) -> str:
    """Sign a minimal JWT with the given private key."""
    import jwt as pyjwt

    now = int(time.time())
    payload: dict = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": now + exp_offset,
    }
    if scopes:
        payload["scope"] = scopes
    return pyjwt.encode(payload, private_pem, algorithm="ES256")


class TestJWTVerifyToken:
    """Integration tests for the actual verify_token() path."""

    @pytest.fixture(autouse=True)
    def _keys(self):
        self.private_pem, self.public_pem = _generate_ec_key_pair()

    def _make_verifier(
        self,
        *,
        audience: str = "https://mcp.example.com",
        issuer: str = "https://auth.example.com",
        required_scopes: list[str] | None = None,
    ):
        from fastmcp.server.auth.providers.jwt import JWTVerifier

        return JWTVerifier(
            public_key=self.public_pem,
            issuer=issuer,
            audience=audience,
            algorithm="ES256",
            required_scopes=required_scopes,
        )

    @pytest.mark.asyncio
    async def test_valid_token_accepted(self):
        verifier = self._make_verifier()
        token = _make_jwt(self.private_pem)
        result = await verifier.verify_token(token)
        assert result is not None
        assert result.client_id == "test-client"

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self):
        verifier = self._make_verifier()
        token = _make_jwt(self.private_pem, exp_offset=-3600)
        result = await verifier.verify_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_audience_rejected(self):
        verifier = self._make_verifier(audience="https://other.example.com")
        token = _make_jwt(self.private_pem, audience="https://mcp.example.com")
        result = await verifier.verify_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_issuer_rejected(self):
        verifier = self._make_verifier(issuer="https://legit.example.com")
        token = _make_jwt(self.private_pem, issuer="https://evil.example.com")
        result = await verifier.verify_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self):
        verifier = self._make_verifier()
        # Sign with a different key
        other_private, _ = _generate_ec_key_pair()
        token = _make_jwt(other_private)
        result = await verifier.verify_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_required_scopes_rejected(self):
        verifier = self._make_verifier(required_scopes=["mcp:admin", "mcp:read"])
        token = _make_jwt(self.private_pem, scopes="mcp:read")
        result = await verifier.verify_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_sufficient_scopes_accepted(self):
        verifier = self._make_verifier(required_scopes=["mcp:read"])
        token = _make_jwt(self.private_pem, scopes="mcp:read mcp:write")
        result = await verifier.verify_token(token)
        assert result is not None
        assert "mcp:read" in result.scopes

    @pytest.mark.asyncio
    async def test_garbage_token_rejected(self):
        verifier = self._make_verifier()
        result = await verifier.verify_token("not.a.jwt")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self):
        verifier = self._make_verifier()
        result = await verifier.verify_token("")
        assert result is None
