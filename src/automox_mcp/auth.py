"""MCP endpoint authentication for HTTP/SSE remote deployments.

Supports two authentication strategies (first match wins):

1. **Static API keys** — simple bearer tokens for trusted clients.
   Configure via ``AUTOMOX_MCP_API_KEYS`` (comma-separated) or
   ``AUTOMOX_MCP_API_KEY_FILE`` (one key per line).

2. **OAuth 2.1 / JWT** — validate JWTs issued by an external IdP
   (Keycloak, Auth0, Azure AD, Okta, etc.) with full audience binding
   and RFC 9728 Protected Resource Metadata.
   Configure via ``AUTOMOX_MCP_OAUTH_ISSUER`` plus either
   ``AUTOMOX_MCP_OAUTH_JWKS_URI`` or ``AUTOMOX_MCP_OAUTH_PUBLIC_KEY``.

Both strategies are *transport-level* authentication — they control who
may connect to the MCP endpoint itself, independent of the Automox API
key used to call upstream APIs.

Key format (both env var and file)::

    bare token        →  amx_mcp_abc123
    labelled token    →  my-client:amx_mcp_abc123

Lines starting with ``#`` and blank lines in the key file are ignored.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_str(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def env_list(name: str) -> list[str]:
    """Parse a comma-separated environment variable into a list of strings."""
    raw = _env_str(name)
    if not raw:
        return []
    return [v.strip() for v in raw.split(",") if v.strip()]


# ---------------------------------------------------------------------------
# Static API key parsing
# ---------------------------------------------------------------------------


def _parse_key_entry(entry: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a single key entry into ``(token, metadata)`` or *None*.

    Accepted formats::

        amx_mcp_abc123              # bare key
        my-client:amx_mcp_abc123    # labelled key
    """
    entry = entry.strip()
    if not entry or entry.startswith("#"):
        return None

    if ":" in entry:
        client_id, _, token = entry.partition(":")
        client_id = client_id.strip()
        token = token.strip()
    else:
        token = entry
        # Derive a stable, short client-id from the key itself.
        client_id = f"client-{hashlib.sha256(token.encode()).hexdigest()[:8]}"

    if not token:
        return None

    return token, {
        "client_id": client_id,
        "scopes": [],  # scopes unused — authorization is all-or-nothing
    }


def _load_keys_from_env() -> dict[str, dict[str, Any]]:
    """Load API keys from ``AUTOMOX_MCP_API_KEYS`` (comma-separated)."""
    raw = os.environ.get("AUTOMOX_MCP_API_KEYS", "").strip()
    if not raw:
        return {}

    tokens: dict[str, dict[str, Any]] = {}
    for part in raw.split(","):
        result = _parse_key_entry(part)
        if result:
            tokens[result[0]] = result[1]
    return tokens


def _load_keys_from_file() -> dict[str, dict[str, Any]]:
    """Load API keys from ``AUTOMOX_MCP_API_KEY_FILE`` (one key per line)."""
    path_str = os.environ.get("AUTOMOX_MCP_API_KEY_FILE", "").strip()
    if not path_str:
        return {}

    path = Path(path_str).resolve()
    if not path.is_file():
        raise RuntimeError(f"AUTOMOX_MCP_API_KEY_FILE points to a non-existent file: {path_str}")

    # V-127: Refuse world-readable key files; warn on group-readable
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o007:
            raise RuntimeError(
                f"AUTOMOX_MCP_API_KEY_FILE ({path}) has world-readable permissions "
                f"({oct(mode)}) — refusing to load. Run: chmod 600 {path}"
            )
        if mode & 0o070:
            logger.warning(
                "AUTOMOX_MCP_API_KEY_FILE (%s) has group-readable permissions %o — "
                "recommend chmod 600 to restrict access to owner only.",
                path,
                mode,
            )
    except OSError:
        pass  # stat failure is non-fatal; proceed to read

    tokens: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        result = _parse_key_entry(line)
        if result:
            tokens[result[0]] = result[1]
    return tokens


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_api_keys() -> dict[str, dict[str, Any]]:
    """Load MCP endpoint API keys from all configured sources.

    Returns a dict mapping bearer-token strings to metadata dicts,
    suitable for passing to FastMCP's ``StaticTokenVerifier``.

    Sources (later sources win on collision):
      1. ``AUTOMOX_MCP_API_KEY_FILE`` — file with one key per line
      2. ``AUTOMOX_MCP_API_KEYS`` — comma-separated env var
    """
    tokens: dict[str, dict[str, Any]] = {}
    tokens.update(_load_keys_from_file())
    tokens.update(_load_keys_from_env())  # env takes precedence
    return tokens


def _create_static_auth() -> Any | None:
    """Create a StaticTokenVerifier if API keys are configured."""
    tokens = load_api_keys()
    if not tokens:
        return None

    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    provider = StaticTokenVerifier(tokens=tokens)
    logger.info(
        "MCP endpoint authentication enabled — mode=static_keys, keys=%d",
        len(tokens),
    )
    return provider


def _create_jwt_auth() -> Any | None:
    """Create a JWT-based auth provider if OAuth env vars are configured.

    Required:
        AUTOMOX_MCP_OAUTH_ISSUER    — OIDC issuer URL (e.g. https://auth.example.com/realms/main)

    Plus one of:
        AUTOMOX_MCP_OAUTH_JWKS_URI  — JWKS endpoint for key rotation
        AUTOMOX_MCP_OAUTH_PUBLIC_KEY — PEM-encoded public key (inline or file path)

    Optional:
        AUTOMOX_MCP_OAUTH_AUDIENCE  — expected audience claim (default: server URL)
        AUTOMOX_MCP_OAUTH_ALGORITHM — JWT signing algorithm (default: RS256)
        AUTOMOX_MCP_OAUTH_SCOPES    — comma-separated required scopes
        AUTOMOX_MCP_OAUTH_SERVER_URL — canonical server URL for RFC 9728 metadata
    """
    issuer = _env_str("AUTOMOX_MCP_OAUTH_ISSUER")
    if not issuer:
        return None

    # V-125: Warn if issuer URL does not use HTTPS (MITM risk for JWKS discovery)
    if not issuer.startswith("https://"):
        logger.warning(
            "AUTOMOX_MCP_OAUTH_ISSUER (%s) does not use HTTPS — "
            "JWKS key discovery over cleartext HTTP is vulnerable to MITM attacks. "
            "Use an https:// issuer URL in production.",
            issuer,
        )

    jwks_uri = _env_str("AUTOMOX_MCP_OAUTH_JWKS_URI")
    public_key = _env_str("AUTOMOX_MCP_OAUTH_PUBLIC_KEY")

    # If public_key looks like a file path, read it
    if public_key and not public_key.startswith("-----"):
        key_path = Path(public_key).expanduser()
        if key_path.is_file():
            public_key = key_path.read_text().strip()

    # Auto-derive JWKS URI from issuer if not explicitly set
    if not jwks_uri and not public_key:
        # Standard OIDC: {issuer}/.well-known/openid-configuration -> jwks_uri
        # Common convention: {issuer}/protocol/openid-connect/certs (Keycloak)
        # Safest: just append the well-known JWKS path
        candidate = issuer.rstrip("/") + "/.well-known/jwks.json"
        logger.info(
            "AUTOMOX_MCP_OAUTH_JWKS_URI not set — will attempt OIDC discovery "
            "from issuer %s (fallback: %s)",
            issuer,
            candidate,
        )
        jwks_uri = candidate

    audience = _env_str("AUTOMOX_MCP_OAUTH_AUDIENCE")
    algorithm = _env_str("AUTOMOX_MCP_OAUTH_ALGORITHM") or "RS256"
    required_scopes = env_list("AUTOMOX_MCP_OAUTH_SCOPES") or None
    server_url = _env_str("AUTOMOX_MCP_OAUTH_SERVER_URL")

    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier_kwargs: dict[str, Any] = {
        "issuer": issuer,
        "algorithm": algorithm,
    }
    if jwks_uri:
        verifier_kwargs["jwks_uri"] = jwks_uri
    if public_key:
        verifier_kwargs["public_key"] = public_key
    if audience:
        verifier_kwargs["audience"] = audience
    if required_scopes:
        verifier_kwargs["required_scopes"] = required_scopes

    jwt_verifier = JWTVerifier(**verifier_kwargs)

    # Wrap with RemoteAuthProvider to serve RFC 9728 Protected Resource Metadata
    # and proper WWW-Authenticate headers with resource_metadata URL.
    if server_url:
        from fastmcp.server.auth.auth import RemoteAuthProvider
        from pydantic import AnyHttpUrl

        provider = RemoteAuthProvider(
            token_verifier=jwt_verifier,
            authorization_servers=[AnyHttpUrl(issuer)],
            base_url=AnyHttpUrl(server_url),
            resource_name="Automox MCP Server",
        )
        logger.info(
            "MCP endpoint authentication enabled — mode=oauth_jwt, "
            "issuer=%s, audience=%s, server_url=%s",
            issuer,
            audience or "(from token)",
            server_url,
        )
        return provider

    logger.info(
        "MCP endpoint authentication enabled — mode=jwt, issuer=%s, audience=%s",
        issuer,
        audience or "(from token)",
    )
    return jwt_verifier


def create_auth_provider() -> Any | None:
    """Create the appropriate FastMCP auth provider.

    Priority:
      1. Static API keys (``AUTOMOX_MCP_API_KEYS`` / ``AUTOMOX_MCP_API_KEY_FILE``)
      2. OAuth 2.1 / JWT (``AUTOMOX_MCP_OAUTH_ISSUER``)
      3. None (no authentication)
    """
    # 1. Static keys take priority — simple, no external dependencies
    provider = _create_static_auth()
    if provider is not None:
        return provider

    # 2. JWT / OAuth 2.1
    provider = _create_jwt_auth()
    if provider is not None:
        return provider

    # 3. No auth
    return None


def is_auth_configured() -> bool:
    """Return *True* if any MCP endpoint authentication is configured."""
    return bool(load_api_keys()) or bool(_env_str("AUTOMOX_MCP_OAUTH_ISSUER"))


def generate_api_key(prefix: str = "amx") -> str:
    """Generate a cryptographically secure MCP endpoint API key.

    Format: ``{prefix}_mcp_{32 random hex chars}``
    """
    return f"{prefix}_mcp_{secrets.token_hex(16)}"


__all__ = [
    "create_auth_provider",
    "env_list",
    "generate_api_key",
    "is_auth_configured",
    "load_api_keys",
]
