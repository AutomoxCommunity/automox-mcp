"""Splashtop Remote Control workflows for Automox MCP.

Wraps the ten endpoints under the ``/remotecontrol-st/...`` surface that
Automox shipped on 2026-01-14 (see CHANGELOG and the openapi-defs bundle
in https://github.com/AutomoxCommunity/openapi-defs). All endpoints are
authenticated with the standard Automox API key (no separate Splashtop
scope), but tenants without an active Remote Control (Core / Resolve)
subscription will get 4XX errors from the upstream — surfaced as
``AutomoxApiError`` by the shared client.

Notable semantics from the OpenAPI:
- ``POST /remotecontrol-st/initiate-connection`` returns a
  ``splashtop-sos://...`` deeplink, NOT an active session. The session
  only starts when the operator's local Splashtop RMM App handles that
  URL, and end-user consent still applies if attended access is enabled.
- ``request_permission`` on the install endpoint is the *install-time*
  consent flag, distinct from per-device attended access for sessions.
- ``accountType`` is a BASIC/PREMIUM/NONE query parameter mapping to the
  Remote Control Core vs Resolve entitlement tier.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient


def _summary_or_raw(response: Any) -> dict[str, Any]:
    return dict(response) if isinstance(response, Mapping) else {"raw": response}


async def get_device_status(
    client: AutomoxClient,
    *,
    device_uuid: str,
) -> dict[str, Any]:
    """List installation + registration status for a Splashtop-managed device."""
    response = await client.get(f"/remotecontrol-st/device-status/{device_uuid}")

    return {
        "data": _summary_or_raw(response),
        "metadata": {"deprecated_endpoint": False},
    }


async def get_session_status(
    client: AutomoxClient,
    *,
    device_uuid: str,
    account_type: str | None = None,
) -> dict[str, Any]:
    """Return active-session count and capacity for a device."""
    params: dict[str, Any] = {}
    if account_type is not None:
        params["accountType"] = account_type

    response = await client.get(
        f"/remotecontrol-st/session-status/{device_uuid}",
        params=params or None,
    )

    return {
        "data": _summary_or_raw(response),
        "metadata": {"deprecated_endpoint": False},
    }


async def get_attended_access(
    client: AutomoxClient,
    *,
    device_uuid: str,
) -> dict[str, Any]:
    """Return the current attended-access requirement for a device.

    ``requiredAttendedAccess: true`` means the end user must approve a
    Splashtop session before it starts.
    """
    response = await client.get(f"/remotecontrol-st/attended-access/{device_uuid}")

    return {
        "data": _summary_or_raw(response),
        "metadata": {"deprecated_endpoint": False},
    }


async def install_splashtop(
    client: AutomoxClient,
    *,
    device_uuid: str,
    os_family: str,
    request_permission: str | None = None,
    organization_uuid: str | None = None,
    account_type: str | None = None,
) -> dict[str, Any]:
    """Install the Splashtop RMM client on a device."""
    body: dict[str, Any] = {"device_uuid": device_uuid, "os_family": os_family}
    if request_permission is not None:
        body["request_permission"] = request_permission
    if organization_uuid is not None:
        body["organization_uuid"] = organization_uuid

    params: dict[str, Any] = {}
    if account_type is not None:
        params["accountType"] = account_type

    response = await client.post(
        "/remotecontrol-st/install",
        json_data=body,
        params=params or None,
    )

    return {
        "data": {
            "device_uuid": device_uuid,
            "queued": True,
            "raw": response,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def bulk_install_uninstall(
    client: AutomoxClient,
    *,
    action: str,
    server_group_id: int | None = None,
) -> dict[str, Any]:
    """Queue an asynchronous bulk install/uninstall of the Splashtop client."""
    body: dict[str, Any] = {"action": action}
    if server_group_id is not None:
        body["server_group_id"] = server_group_id

    response = await client.post("/remotecontrol-st/bulk/software", json_data=body)

    data = _summary_or_raw(response)
    data.setdefault("action", action)
    data["queued"] = True

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def initiate_connection(
    client: AutomoxClient,
    *,
    device_uuid: str,
    os_family: str,
    connection_type: str,
    account_type: str | None = None,
) -> dict[str, Any]:
    """Generate a Splashtop deeplink URL to start a remote-control session.

    The API does NOT open a session; it returns a ``splashtop-sos://...``
    URL that the operator's local Splashtop RMM App handles. End-user
    consent still applies if attended access is enabled on the device.
    """
    body: dict[str, Any] = {
        "ax_device_uuid": device_uuid,
        "os_family": os_family,
        "connection_type": connection_type,
    }

    params: dict[str, Any] = {}
    if account_type is not None:
        params["accountType"] = account_type

    response = await client.post(
        "/remotecontrol-st/initiate-connection",
        json_data=body,
        params=params or None,
    )

    data = _summary_or_raw(response)
    data["device_uuid"] = device_uuid
    data["connection_type"] = connection_type
    data["_important"] = (
        "The returned splashtopUrl is a deeplink for the operator's local "
        "Splashtop RMM App. The session does not start until the operator "
        "opens that URL. If attended access is enabled on the device, the "
        "end user must still approve the session."
    )

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def force_disconnect(
    client: AutomoxClient,
    *,
    device_uuid: str,
    os_family: str,
) -> dict[str, Any]:
    """Force-disconnect all active Splashtop sessions on a device."""
    response = await client.post(
        f"/remotecontrol-st/force-disconnection/{device_uuid}",
        params={"os_family": os_family},
    )

    return {
        "data": {
            "device_uuid": device_uuid,
            "disconnected": True,
            "raw": response,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def set_attended_access(
    client: AutomoxClient,
    *,
    device_uuid: str,
    required_attended_access: bool,
) -> dict[str, Any]:
    """Enable or disable the end-user consent requirement for a device.

    Setting this to ``false`` allows operators to start Splashtop sessions
    on the device without end-user approval. The Automox product default
    is ``true`` (Required/attended).
    """
    response = await client.put(
        f"/remotecontrol-st/attended-access/{device_uuid}",
        json_data={"requiredAttendedAccess": required_attended_access},
    )

    return {
        "data": {
            "device_uuid": device_uuid,
            "requiredAttendedAccess": required_attended_access,
            "updated": True,
            "raw": response if not isinstance(response, Mapping) else dict(response),
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def set_bulk_attended_access(
    client: AutomoxClient,
    *,
    device_uuids: list[str],
    required_attended_access: bool,
) -> dict[str, Any]:
    """Bulk-set the attended-access requirement across many devices."""
    body: dict[str, Any] = {
        "deviceUuids": device_uuids,
        "requiredAttendedAccess": required_attended_access,
    }
    response = await client.put(
        "/remotecontrol-st/attended-access/bulk",
        json_data=body,
    )

    return {
        "data": {
            "device_uuids": device_uuids,
            "requiredAttendedAccess": required_attended_access,
            "updated": True,
            "raw": response if not isinstance(response, Mapping) else dict(response),
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def uninstall_splashtop(
    client: AutomoxClient,
    *,
    device_uuid: str,
    os_family: str,
) -> dict[str, Any]:
    """Uninstall the Splashtop client and delete the device's registration."""
    await client.delete(
        f"/remotecontrol-st/uninstall/{device_uuid}",
        params={"os_family": os_family},
    )

    return {
        "data": {
            "device_uuid": device_uuid,
            "deleted": True,
        },
        "metadata": {"deprecated_endpoint": False},
    }
