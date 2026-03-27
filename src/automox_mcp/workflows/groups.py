"""Server group workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient


def _summarize_group(group: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a server group record."""
    return {
        "id": group.get("id"),
        "name": group.get("name") or "(unnamed)",
        "organization_id": group.get("organization_id"),
        "parent_server_group_id": group.get("parent_server_group_id"),
        "server_count": group.get("server_count", 0),
        "policy_count": len(group.get("policies", [])),
        "policies": group.get("policies"),
        "ui_color": group.get("ui_color"),
        "notes": group.get("notes"),
        "refresh_interval": group.get("refresh_interval"),
    }


async def list_server_groups(
    client: AutomoxClient,
    *,
    org_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List all server groups in the organization."""
    params: dict[str, Any] = {"o": org_id}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    groups = await client.get("/servergroups", params=params)

    if not isinstance(groups, list):
        groups = []

    summary = [_summarize_group(g) for g in groups if isinstance(g, Mapping)]

    return {
        "data": {
            "total_groups": len(summary),
            "groups": summary,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def get_server_group(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int,
) -> dict[str, Any]:
    """Retrieve details for a specific server group."""
    params: dict[str, Any] = {"o": org_id}
    group = await client.get(f"/servergroups/{group_id}", params=params)

    data: dict[str, Any]
    if isinstance(group, Mapping):
        data = _summarize_group(group)
    else:
        data = {"group_id": group_id, "raw": group}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def create_server_group(
    client: AutomoxClient,
    *,
    org_id: int,
    name: str,
    refresh_interval: int,
    parent_server_group_id: int | None = None,
    ui_color: str | None = None,
    notes: str | None = None,
    policies: list | None = None,
) -> dict[str, Any]:
    """Create a new server group."""
    body: dict[str, Any] = {
        "name": name,
        "refresh_interval": refresh_interval,
    }
    if parent_server_group_id is not None:
        body["parent_server_group_id"] = parent_server_group_id
    if ui_color is not None:
        body["ui_color"] = ui_color
    if notes is not None:
        body["notes"] = notes
    if policies is not None:
        body["policies"] = policies

    params: dict[str, Any] = {"o": org_id}
    result = await client.post("/servergroups", json_data=body, params=params)

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = _summarize_group(result)
        data["created"] = True
    else:
        data = {"name": name, "created": True, "raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def update_server_group(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int,
    name: str,
    refresh_interval: int,
    parent_server_group_id: int | None = None,
    ui_color: str | None = None,
    notes: str | None = None,
    policies: list | None = None,
) -> dict[str, Any]:
    """Update an existing server group."""
    body: dict[str, Any] = {
        "name": name,
        "refresh_interval": refresh_interval,
    }
    if parent_server_group_id is not None:
        body["parent_server_group_id"] = parent_server_group_id
    if ui_color is not None:
        body["ui_color"] = ui_color
    if notes is not None:
        body["notes"] = notes
    if policies is not None:
        body["policies"] = policies

    params: dict[str, Any] = {"o": org_id}
    result = await client.put(f"/servergroups/{group_id}", json_data=body, params=params)

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = _summarize_group(result)
        data["updated"] = True
    else:
        data = {"group_id": group_id, "updated": True, "raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def delete_server_group(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int,
) -> dict[str, Any]:
    """Delete a server group."""
    params: dict[str, Any] = {"o": org_id}
    await client.delete(f"/servergroups/{group_id}", params=params)

    return {
        "data": {
            "group_id": group_id,
            "deleted": True,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }
