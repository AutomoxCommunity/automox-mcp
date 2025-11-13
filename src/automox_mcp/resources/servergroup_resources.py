"""Server group resources for Automox MCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient


def register(server: FastMCP) -> None:
    """Register server group resources."""

    @server.resource(
        "resource://servergroups/list",
        name="Server Groups Mapping",
        description="List of all Automox server groups with ID to name mappings",
        mime_type="application/json",
    )
    async def list_servergroups() -> dict[str, Any]:
        """List all Automox server groups with ID to name mappings.

        Returns server groups containing:
        - id: numeric server group ID
        - name: human-readable group name
        - organization_id: parent org ID
        - server_count: number of devices in this group
        - policy_count: number of policies assigned to this group

        Use this resource to map server_group_id values from device data
        to human-readable group names.
        """
        client = AutomoxClient(default_api="console")
        async with client as session:
            org_id = client.org_id
            if not org_id:
                return {"error": "org_id required - set AUTOMOX_ORG_ID environment variable"}

            params = {"o": org_id}
            groups = await session.get("/servergroups", params=params, api="console")

            if not isinstance(groups, list):
                groups = []

            # Create a compact mapping
            group_list = []
            for group in groups:
                if isinstance(group, dict):
                    group_list.append(
                        {
                            "id": group.get("id"),
                            "name": group.get("name") or "(unnamed)",
                            "organization_id": group.get("organization_id"),
                            "server_count": group.get("server_count", 0),
                            "policy_count": len(group.get("policies", [])),
                        }
                    )

            return {
                "server_groups": group_list,
                "total_count": len(group_list),
                "note": "Use this to map server_group_id from device data to group names",
            }


__all__ = ["register"]
