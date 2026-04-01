"""Resources module for exposing Automox reference data and schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..client import AutomoxClient


def register_resources(server: FastMCP, *, client: AutomoxClient) -> None:
    """Register all MCP resources with the server."""
    from .platform_resources import register as register_platform_resources
    from .policy_resources import register_policy_resources
    from .servergroup_resources import register as register_servergroup_resources
    from .webhook_resources import register as register_webhook_resources

    register_policy_resources(server)
    register_servergroup_resources(server, client=client)
    register_webhook_resources(server)
    register_platform_resources(server)


__all__ = ["register_resources"]
