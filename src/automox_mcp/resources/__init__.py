"""Resources module for exposing Automox reference data and schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..client import AutomoxClient


def register_resources(server: FastMCP, *, client: AutomoxClient) -> None:
    """Register all MCP resources with the server."""
    from .patch_approval_app import register as register_patch_approval_app
    from .platform_resources import register as register_platform_resources
    from .policy_blast_radius_app import register as register_policy_blast_radius_app
    from .policy_resources import register_policy_resources
    from .remediation_apply_app import register as register_remediation_apply_app
    from .servergroup_resources import register as register_servergroup_resources
    from .triage_app import register as register_triage_app
    from .webhook_resources import register as register_webhook_resources

    register_policy_resources(server)
    register_servergroup_resources(server, client=client)
    register_webhook_resources(server)
    register_platform_resources(server)
    register_triage_app(server)
    register_patch_approval_app(server)
    register_policy_blast_radius_app(server)
    register_remediation_apply_app(server)


__all__ = ["register_resources"]
