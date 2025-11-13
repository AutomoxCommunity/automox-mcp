"""Public package interface for the Automox FastMCP server."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from fastmcp import FastMCP

from .server import create_server


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
    parser.set_defaults(show_banner=_env_flag("AUTOMOX_MCP_SHOW_BANNER"))

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Initialize and run the MCP server using the configured transport."""
    args = _parse_args(argv)

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
        if host is None and port is None:
            # Provide sensible defaults that mirror the FastMCP CLI.
            transport_kwargs.setdefault("host", "127.0.0.1")
            transport_kwargs.setdefault("port", 8000)

    mcp.run(transport=transport, show_banner=args.show_banner, **transport_kwargs)


__all__ = ["create_server", "mcp", "main"]
