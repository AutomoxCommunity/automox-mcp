"""Regression tests for _create_jwt_auth config-handling fixes.

Covers three v2.2.2-audit bugs in ``automox_mcp.auth._create_jwt_auth``:

* case-variant OAuth algorithm (e.g. ``rs256``) must be normalized to the
  canonical uppercase form instead of crashing boot in JWTVerifier.
* setting BOTH ``AUTOMOX_MCP_OAUTH_JWKS_URI`` and
  ``AUTOMOX_MCP_OAUTH_PUBLIC_KEY`` must raise the module's friendly
  ``RuntimeError`` rather than JWTVerifier's opaque ``ValueError``.
* ``EdDSA`` is no longer enumerated as supported; it is rejected with the
  clear "not a recognized JWT algorithm" guard (it is unsupported downstream).
"""

from __future__ import annotations

import pytest

from automox_mcp.auth import _create_jwt_auth

_OAUTH_ENV_VARS = [
    "AUTOMOX_MCP_OAUTH_ISSUER",
    "AUTOMOX_MCP_OAUTH_JWKS_URI",
    "AUTOMOX_MCP_OAUTH_PUBLIC_KEY",
    "AUTOMOX_MCP_OAUTH_AUDIENCE",
    "AUTOMOX_MCP_OAUTH_ALGORITHM",
    "AUTOMOX_MCP_OAUTH_SCOPES",
    "AUTOMOX_MCP_OAUTH_SERVER_URL",
    "AUTOMOX_MCP_API_KEYS",
    "AUTOMOX_MCP_API_KEY_FILE",
]

# A structurally-marked PEM public key; JWTVerifier accepts it as a public_key
# without parsing (mirrors the existing test_public_key_inline fixture).
_FAKE_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...\n-----END PUBLIC KEY-----"
)


@pytest.fixture
def _clean_oauth_env(monkeypatch):
    """Strip all auth-related env so each case starts from a known state."""
    for var in _OAUTH_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _set_base_oauth(monkeypatch, *, public_key: bool = True) -> None:
    """Configure the minimum valid OAuth env for a public-key verifier."""
    monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ISSUER", "https://auth.example.com")
    monkeypatch.setenv("AUTOMOX_MCP_OAUTH_AUDIENCE", "https://mcp.example.com")
    if public_key:
        monkeypatch.setenv("AUTOMOX_MCP_OAUTH_PUBLIC_KEY", _FAKE_PUBLIC_KEY)


# ---------------------------------------------------------------------------
# case-variant algorithm normalized, not crashed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw_algorithm", ["rs256", "Rs256", "RS256"])
def test_lowercase_algorithm_is_normalized(_clean_oauth_env, raw_algorithm):
    monkeypatch = _clean_oauth_env
    _set_base_oauth(monkeypatch)
    monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ALGORITHM", raw_algorithm)

    # Builder must succeed (no uncaught ValueError from JWTVerifier) ...
    provider = _create_jwt_auth()

    # ... and the forwarded algorithm is the canonical uppercase form.
    assert provider is not None
    assert provider.algorithm == "RS256"


# ---------------------------------------------------------------------------
# both jwks_uri and public_key set raises a friendly RuntimeError
# ---------------------------------------------------------------------------


def test_both_jwks_and_public_key_raise_runtimeerror(_clean_oauth_env):
    monkeypatch = _clean_oauth_env
    _set_base_oauth(monkeypatch)  # sets public_key
    monkeypatch.setenv(
        "AUTOMOX_MCP_OAUTH_JWKS_URI",
        "https://auth.example.com/.well-known/jwks.json",
    )

    with pytest.raises(RuntimeError, match="exactly one"):
        _create_jwt_auth()


# ---------------------------------------------------------------------------
# EdDSA is no longer enumerated-but-rejected; it is a clear error
# ---------------------------------------------------------------------------


def test_eddsa_is_rejected_with_clear_error(_clean_oauth_env):
    monkeypatch = _clean_oauth_env
    _set_base_oauth(monkeypatch)
    monkeypatch.setenv("AUTOMOX_MCP_OAUTH_ALGORITHM", "EdDSA")

    # No longer the self-contradictory "enumerated but rejected" state: EdDSA is
    # simply not in the supported set, surfaced via the recognized-algorithm
    # guard's message.
    with pytest.raises(RuntimeError, match="not a recognized JWT algorithm"):
        _create_jwt_auth()
