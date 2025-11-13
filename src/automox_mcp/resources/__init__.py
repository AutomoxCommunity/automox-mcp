"""Resources module for exposing Automox reference data and schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_resources(server: FastMCP) -> None:
    """Register all MCP resources with the server."""
    from .policy_resources import register_policy_resources
    from .servergroup_resources import register as register_servergroup_resources

    register_policy_resources(server)
    register_servergroup_resources(server)


__all__ = ["register_resources"]
