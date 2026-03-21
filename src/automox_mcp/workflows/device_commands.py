"""Device command workflows for Automox MCP."""

from __future__ import annotations

from typing import Any

from ..client import AutomoxClient


async def issue_device_command(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    device_id: int,
    command_type: str,
    patch_names: str | None = None,
) -> dict[str, Any]:
    """Issue an immediate command to an Automox device.

    Args:
        client: Automox API client
        org_id: Organization ID (optional, uses client default)
        device_id: Device ID to send command to
        command_type: Command type - "scan", "patch_all", "patch_specific",
            "reboot", or "refresh_os"
        patch_names: Comma-separated patch names (required for patch_specific)

    Returns:
        Dictionary with command execution data and metadata
    """
    resolved_org_id = org_id or client.org_id
    if not resolved_org_id:
        raise ValueError(
            "org_id required - pass explicitly or set AUTOMOX_ORG_ID"
        )

    command_normalized = (
        command_type.lower().replace("-", "_").replace(" ", "_")
    )
    command_map = {
        "scan": "GetOS",
        "get_os": "GetOS",
        "getos": "GetOS",
        "refresh": "GetOS",
        "refresh_os": "GetOS",
        "patch": "InstallAllUpdates",
        "patch_all": "InstallAllUpdates",
        "install_all": "InstallAllUpdates",
        "installallupdates": "InstallAllUpdates",
        "patch_specific": "InstallUpdate",
        "install_update": "InstallUpdate",
        "installupdate": "InstallUpdate",
        "reboot": "Reboot",
        "restart": "Reboot",
    }
    command_value = command_map.get(command_normalized, command_type)

    valid_commands = {"GetOS", "InstallUpdate", "InstallAllUpdates", "Reboot"}
    if command_value not in valid_commands:
        raise ValueError(
            f"Invalid command '{command_type}'. "
            f"Use: 'scan', 'patch_all', 'patch_specific', or 'reboot'"
        )

    if command_value == "InstallUpdate" and not patch_names:
        raise ValueError(
            "patch_names is required when command_type is 'patch_specific'"
        )

    body: dict[str, Any] = {"command_type_name": command_value}
    if patch_names:
        body["args"] = patch_names

    params = {"o": resolved_org_id}
    response_data = await client.post(
        f"/servers/{device_id}/queues",
        json_data=body,
        params=params,
    )

    data = {
        "device_id": device_id,
        "command_type": command_value,
        "patch_names": patch_names,
        "command_queued": True,
        "response": response_data,
    }

    metadata = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "device_id": device_id,
    }

    return {
        "data": data,
        "metadata": metadata,
    }


__all__ = ["issue_device_command"]
