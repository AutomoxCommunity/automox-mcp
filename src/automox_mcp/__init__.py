"""Public package interface for the Automox FastMCP server."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence

from fastmcp import FastMCP

from .server import create_server

logger = logging.getLogger(__name__)


class _LazyServer:
    """Lazy wrapper that defers FastMCP server creation until first use."""

    __slots__ = ("_instance",)

    def __init__(self) -> None:
        self._instance: FastMCP | None = None

    def _get(self) -> FastMCP:
        if self._instance is None:
            self._instance = create_server()
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._get(), name)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        if self._instance is None:
            return "<LazyAutomoxMCP (uninitialized)>"
        return repr(self._instance)


mcp = _LazyServer()


def _env_str(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_flag(name: str, default: bool = False) -> bool:
    value = _env_str(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Automox FastMCP server with the desired transport."
    )

    parser.add_argument(
        "--transport",
        choices=("stdio", "http", "sse"),
        help="FastMCP transport to use (default: stdio).",
    )
    parser.add_argument(
        "--host",
        help="Host to bind for HTTP/SSE transports (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Port to bind for HTTP/SSE transports (default: 8000).",
    )
    parser.add_argument(
        "--path",
        help="Custom path for HTTP/SSE transports (defaults to FastMCP's standard path).",
    )
    parser.add_argument(
        "--show-banner",
        action="store_true",
        default=_env_flag("AUTOMOX_MCP_SHOW_BANNER"),
        help="Display the FastMCP startup banner.",
    )
    parser.add_argument(
        "--no-banner",
        action="store_false",
        dest="show_banner",
        help="Suppress the FastMCP startup banner.",
    )
    parser.add_argument(
        "--allow-remote-bind",
        action="store_true",
        default=_env_flag("AUTOMOX_MCP_ALLOW_REMOTE_BIND"),
        help=(
            "Allow binding HTTP/SSE transports to non-loopback addresses. "
            "Required when --host is not 127.0.0.1/::1/localhost. "
            "Set AUTOMOX_MCP_API_KEYS or AUTOMOX_MCP_API_KEY_FILE to enable "
            "built-in Bearer-token authentication, or use a reverse proxy."
        ),
    )
    parser.add_argument(
        "--generate-key",
        action="store_true",
        help="Generate a cryptographically secure MCP endpoint API key and exit.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Initialize and run the MCP server using the configured transport."""
    args = _parse_args(argv)

    # --generate-key: print a new API key and exit (no server startup needed).
    if args.generate_key:
        from .auth import generate_api_key

        # Write directly to stdout — this is the intended output of --generate-key,
        # not a logging leak of sensitive data.
        sys.stdout.write(generate_api_key() + "\n")
        return

    transport_env = _env_str("AUTOMOX_MCP_TRANSPORT")
    transport = args.transport or (transport_env or "stdio")
    transport = transport.lower()
    if transport not in {"stdio", "http", "sse"}:
        raise SystemExit(f"Unsupported transport '{transport}'. Expected stdio, http, or sse.")

    host = args.host or _env_str("AUTOMOX_MCP_HOST")
    port = args.port
    if port is None:
        port_env = _env_str("AUTOMOX_MCP_PORT")
        if port_env is not None:
            try:
                port = int(port_env)
            except ValueError as exc:  # pragma: no cover - invalid user input
                raise SystemExit(
                    f"AUTOMOX_MCP_PORT must be an integer (received {port_env!r})."
                ) from exc
    path = args.path or _env_str("AUTOMOX_MCP_PATH")

    transport_kwargs: dict[str, object] = {}
    if transport != "stdio":
        if host is not None:
            transport_kwargs["host"] = host
        if port is not None:
            transport_kwargs["port"] = port
        if path is not None:
            transport_kwargs["path"] = path
        if host is None:
            transport_kwargs.setdefault("host", "127.0.0.1")
        if port is None:
            transport_kwargs.setdefault("port", 8000)

        # Transport security: DNS rebinding protection + security headers
        from .transport_security import build_transport_security_middleware

        resolved_host_for_sec = str(transport_kwargs.get("host", "127.0.0.1"))
        resolved_port_for_sec = int(str(transport_kwargs.get("port", 8000)))
        transport_kwargs["middleware"] = build_transport_security_middleware(
            host=resolved_host_for_sec,
            port=resolved_port_for_sec,
        )

        resolved_host = str(transport_kwargs.get("host", "127.0.0.1"))
        _LOOPBACK = {"127.0.0.1", "::1", "localhost"}
        if resolved_host not in _LOOPBACK:
            from .auth import is_auth_configured

            auth_active = is_auth_configured()

            if not args.allow_remote_bind:
                auth_hint = (
                    "Set AUTOMOX_MCP_API_KEYS or AUTOMOX_MCP_API_KEY_FILE to enable "
                    "built-in Bearer-token authentication, or use a reverse proxy."
                )
                raise SystemExit(
                    f"Refusing to bind {transport} transport to non-loopback address "
                    f"{resolved_host}.\n"
                    f"Pass --allow-remote-bind (or set AUTOMOX_MCP_ALLOW_REMOTE_BIND=true) "
                    f"to override.\n{auth_hint}"
                )

            if auth_active:
                logger.info(
                    "Binding %s transport to non-loopback address %s with "
                    "MCP endpoint authentication enabled.",
                    transport,
                    resolved_host,
                )
            else:
                logger.warning(
                    "Binding %s transport to non-loopback address %s WITHOUT "
                    "MCP endpoint authentication. Set AUTOMOX_MCP_API_KEYS or "
                    "AUTOMOX_MCP_API_KEY_FILE to require Bearer tokens, or use "
                    "an authenticating reverse proxy.",
                    transport,
                    resolved_host,
                )

    mcp.run(transport=transport, show_banner=args.show_banner, **transport_kwargs)


__all__ = ["create_server", "mcp", "main"]
