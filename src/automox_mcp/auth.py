"""MCP endpoint API key authentication for HTTP/SSE remote deployments.

When ``AUTOMOX_MCP_API_KEYS`` (comma-separated) or ``AUTOMOX_MCP_API_KEY_FILE``
(one key per line) is configured, the server requires a valid Bearer token on
every HTTP/SSE request.  This is *transport-level* authentication — it controls
who may connect to the MCP endpoint itself, independent of the Automox API key
used to call upstream APIs.

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
# Key parsing helpers
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
        raise RuntimeError(
            f"AUTOMOX_MCP_API_KEY_FILE points to a non-existent file: {path_str}"
        )

    # Warn if the key file is readable by group or others
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            logger.warning(
                "AUTOMOX_MCP_API_KEY_FILE (%s) has permissions %o — "
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


def create_auth_provider() -> Any | None:
    """Create a FastMCP auth provider if MCP endpoint API keys are configured.

    Returns ``None`` when no keys are set (authentication disabled).
    """
    tokens = load_api_keys()
    if not tokens:
        return None

    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    provider = StaticTokenVerifier(tokens=tokens)
    logger.info(
        "MCP endpoint authentication enabled with %d API key(s)",
        len(tokens),
    )
    return provider


def is_auth_configured() -> bool:
    """Return *True* if any MCP endpoint API keys are configured."""
    return bool(load_api_keys())


def generate_api_key(prefix: str = "amx") -> str:
    """Generate a cryptographically secure MCP endpoint API key.

    Format: ``{prefix}_mcp_{32 random hex chars}``
    """
    return f"{prefix}_mcp_{secrets.token_hex(16)}"


__all__ = [
    "create_auth_provider",
    "generate_api_key",
    "is_auth_configured",
    "load_api_keys",
]
