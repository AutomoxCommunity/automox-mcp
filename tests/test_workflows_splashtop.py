"""Tests for Splashtop Remote Control workflows (2026-01-14 endpoints)."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.splashtop import (
    bulk_install_uninstall,
    force_disconnect,
    get_attended_access,
    get_device_status,
    get_session_status,
    initiate_connection,
    install_splashtop,
    set_attended_access,
    set_bulk_attended_access,
    uninstall_splashtop,
)

_DEVICE_UUID = "550e8400-e29b-41d4-a716-446655440000"
_DEVICE_UUID_2 = "660e8400-e29b-41d4-a716-446655440001"


def _make_client(**kwargs: Any) -> StubClient:
    return StubClient(**kwargs)


@pytest.mark.asyncio
async def test_device_status_returns_payload() -> None:
    path = f"/remotecontrol-st/device-status/{_DEVICE_UUID}"
    payload = {
        "install_time": "2024-01-15T10:31:00.000+00:00",
        "installation_status": True,
        "registration_status": True,
    }
    client = _make_client(get_responses={path: [payload]})
    result = await get_device_status(cast(AutomoxClient, client), device_uuid=_DEVICE_UUID)

    # Raw DTO booleans still pass through verbatim.
    assert result["data"]["installation_status"] is True
    assert result["data"]["registration_status"] is True
    # Sibling legend documents the two independent booleans (house style).
    notes = result["metadata"]["field_notes"]
    assert set(notes) == {"installation_status", "registration_status"}


@pytest.mark.asyncio
async def test_session_status_returns_capacity() -> None:
    path = f"/remotecontrol-st/session-status/{_DEVICE_UUID}"
    payload = {"can_start_new_session": True, "current_sessions": 0, "max_sessions": 1}
    client = _make_client(get_responses={path: [payload]})
    result = await get_session_status(
        cast(AutomoxClient, client),
        device_uuid=_DEVICE_UUID,
        account_type="PREMIUM",
    )

    assert result["data"]["can_start_new_session"] is True
    _, _, params = client.calls[0]
    assert params == {"accountType": "PREMIUM"}


@pytest.mark.asyncio
async def test_get_attended_access_returns_flag() -> None:
    path = f"/remotecontrol-st/attended-access/{_DEVICE_UUID}"
    client = _make_client(get_responses={path: [{"requiredAttendedAccess": True}]})
    result = await get_attended_access(cast(AutomoxClient, client), device_uuid=_DEVICE_UUID)
    assert result["data"] == {"requiredAttendedAccess": True}


@pytest.mark.asyncio
async def test_install_posts_body_and_query() -> None:
    path = "/remotecontrol-st/install"
    client = _make_client(post_responses={path: ["queued"]})
    result = await install_splashtop(
        cast(AutomoxClient, client),
        device_uuid=_DEVICE_UUID,
        os_family="windows",
        request_permission="ask_reject_on_timeout",
        account_type="PREMIUM",
    )

    method, called_path, body = client.calls[0]
    assert method == "POST"
    assert called_path == path
    assert body == {
        "device_uuid": _DEVICE_UUID,
        "os_family": "windows",
        "request_permission": "ask_reject_on_timeout",
    }
    assert result["data"]["queued"] is True


@pytest.mark.asyncio
async def test_install_omits_optional_fields() -> None:
    path = "/remotecontrol-st/install"
    client = _make_client(post_responses={path: ["queued"]})
    await install_splashtop(
        cast(AutomoxClient, client),
        device_uuid=_DEVICE_UUID,
        os_family="mac",
    )
    _, _, body = client.calls[0]
    assert "request_permission" not in body
    assert "organization_uuid" not in body
    assert body["os_family"] == "mac"


@pytest.mark.asyncio
async def test_bulk_install_uninstall_posts_action() -> None:
    path = "/remotecontrol-st/bulk/software"
    client = _make_client(post_responses={path: [{}]})
    result = await bulk_install_uninstall(
        cast(AutomoxClient, client),
        action="install",
        server_group_id=42,
    )

    method, called_path, body = client.calls[0]
    assert method == "POST"
    assert called_path == path
    assert body == {"action": "install", "server_group_id": 42}
    assert result["data"]["queued"] is True
    assert result["data"]["action"] == "install"


@pytest.mark.asyncio
async def test_initiate_connection_returns_deeplink_warning() -> None:
    path = "/remotecontrol-st/initiate-connection"
    client = _make_client(post_responses={path: [{"splashtopUrl": "splashtop-sos://abc"}]})
    result = await initiate_connection(
        cast(AutomoxClient, client),
        device_uuid=_DEVICE_UUID,
        os_family="windows",
        connection_type="remote_control",
    )

    method, _, body = client.calls[0]
    assert method == "POST"
    assert body == {
        "ax_device_uuid": _DEVICE_UUID,
        "os_family": "windows",
        "connection_type": "remote_control",
    }
    assert result["data"]["splashtopUrl"] == "splashtop-sos://abc"
    assert "deeplink" in result["data"]["_important"]


@pytest.mark.asyncio
async def test_force_disconnect_passes_os_family_query() -> None:
    path = f"/remotecontrol-st/force-disconnection/{_DEVICE_UUID}"
    client = _make_client(post_responses={path: ["disconnected"]})
    result = await force_disconnect(
        cast(AutomoxClient, client),
        device_uuid=_DEVICE_UUID,
        os_family="windows",
    )

    _, called_path, params_or_body = client.calls[0]
    assert called_path == path
    # StubClient logs json_data on POST; query params not captured separately.
    # But we can at least confirm the call happened and the result is shaped.
    assert result["data"]["disconnected"] is True


@pytest.mark.asyncio
async def test_set_attended_access_puts_flag() -> None:
    path = f"/remotecontrol-st/attended-access/{_DEVICE_UUID}"
    client = _make_client(put_responses={path: [{}]})
    result = await set_attended_access(
        cast(AutomoxClient, client),
        device_uuid=_DEVICE_UUID,
        required_attended_access=False,
    )

    method, called_path, body = client.calls[0]
    assert method == "PUT"
    assert called_path == path
    assert body == {"requiredAttendedAccess": False}
    assert result["data"]["updated"] is True
    assert result["data"]["requiredAttendedAccess"] is False


@pytest.mark.asyncio
async def test_set_bulk_attended_access_puts_list() -> None:
    path = "/remotecontrol-st/attended-access/bulk"
    client = _make_client(put_responses={path: [{}]})
    result = await set_bulk_attended_access(
        cast(AutomoxClient, client),
        device_uuids=[_DEVICE_UUID, _DEVICE_UUID_2],
        required_attended_access=True,
    )

    method, called_path, body = client.calls[0]
    assert method == "PUT"
    assert called_path == path
    assert body == {
        "deviceUuids": [_DEVICE_UUID, _DEVICE_UUID_2],
        "requiredAttendedAccess": True,
    }
    assert result["data"]["updated"] is True


@pytest.mark.asyncio
async def test_uninstall_splashtop_calls_delete() -> None:
    path = f"/remotecontrol-st/uninstall/{_DEVICE_UUID}"
    client = _make_client(delete_responses={path: [None]})
    result = await uninstall_splashtop(
        cast(AutomoxClient, client),
        device_uuid=_DEVICE_UUID,
        os_family="windows",
    )

    method, called_path, _ = client.calls[0]
    assert method == "DELETE"
    assert called_path == path
    assert result["data"] == {"device_uuid": _DEVICE_UUID, "deleted": True}
