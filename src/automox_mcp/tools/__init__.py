"""Tool registration modules for Automox MCP."""

from __future__ import annotations

from fastmcp import FastMCP

from . import account_tools, audit_tools, device_tools, policy_tools


def register_tools(server: FastMCP) -> None:
    """Register all Automox tool modules with the FastMCP server."""

    audit_tools.register(server)
    device_tools.register(server)
    policy_tools.register(server)
    account_tools.register(server)


__all__ = ["register_tools"]
