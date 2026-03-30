"""Tests for OAuth 2.1 / JWT authentication provider."""

from __future__ import annotations

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
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_SERVER_URL", "https://mcp.example.com")

        provider = _create_jwt_auth()
        routes = provider.get_routes(mcp_path="/mcp")
        assert len(routes) >= 1
        paths = [r.path for r in routes]
        assert any(".well-known/oauth-protected-resource" in p for p in paths)

    def test_auto_derives_jwks_uri_from_issuer(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        # No JWKS_URI and no PUBLIC_KEY — should auto-derive

        provider = _create_jwt_auth()
        assert provider is not None
        # The provider should have been created with the derived JWKS URI
        assert type(provider).__name__ == "JWTVerifier"

    def test_custom_algorithm(self, monkeypatch):
        self._clear_oauth_env(monkeypatch)
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
        monkeypatch.setenv(
            "AUTOMOX_MCP_OAUTH_JWKS_URI",
            "https://auth.example.com/.well-known/jwks.json",
        )
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ALGORITHM", "ES256")

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
