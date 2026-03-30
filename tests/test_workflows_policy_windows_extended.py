"""Extended edge-case tests for policy windows workflows."""

from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy_windows import (
    check_group_exclusion_status,
    check_window_active,
    create_policy_window,
    get_device_scheduled_windows,
    get_group_scheduled_windows,
    get_policy_window,
    search_policy_windows,
    update_policy_window,
)

_ORG_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_WINDOW_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_GROUP_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_DEVICE_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


# ---------------------------------------------------------------------------
# search_policy_windows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_windows_empty_mapping_returns_zero() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/search": [{"content": []}],
        }
    )
    result = await search_policy_windows(cast(AutomoxClient, client), org_uuid=_ORG_UUID)
    assert result["data"]["total_windows"] == 0
    assert result["data"]["windows"] == []


@pytest.mark.asyncio
async def test_search_windows_empty_body_sent() -> None:
    """When no filters are provided, body should be empty."""
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/search": [{"content": []}],
        }
    )
    await search_policy_windows(cast(AutomoxClient, client), org_uuid=_ORG_UUID)
    body = client.calls[0][2]
    assert body == {}


# ---------------------------------------------------------------------------
# get_policy_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_window_non_mapping_returns_raw() -> None:
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}": ["not-a-dict"],
        }
    )
    result = await get_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_uuid=_WINDOW_UUID,
    )
    assert result["data"]["raw"] == "not-a-dict"
    assert result["data"]["window_uuid"] == _WINDOW_UUID


# ---------------------------------------------------------------------------
# create_policy_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_window_non_mapping_returns_raw() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}": ["created-ok"],
        }
    )
    result = await create_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_type="exclude",
        window_name="X",
        window_description="X",
        rrule="FREQ=DAILY",
        duration_minutes=60,
        use_local_tz=False,
        recurrence="once",
        group_uuids=[_GROUP_UUID],
        dtstart="2026-01-01T00:00:00Z",
        status="active",
    )
    assert result["data"]["created"] is True
    assert result["data"]["raw"] == "created-ok"


# ---------------------------------------------------------------------------
# update_policy_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_window_non_mapping_returns_raw() -> None:
    client = StubClient(
        put_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}": ["updated-ok"],
        }
    )
    result = await update_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_uuid=_WINDOW_UUID,
        dtstart="2026-01-01T00:00:00Z",
    )
    assert result["data"]["updated"] is True
    assert result["data"]["raw"] == "updated-ok"


# ---------------------------------------------------------------------------
# check_group_exclusion_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exclusion_status_mapping_wrapper() -> None:
    """Handle case where API wraps the status list in a Mapping."""
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/groups/exclusion-status": [
                {"data": [{"group_uuid": _GROUP_UUID, "in_exclusion_window": False}]},
            ],
        }
    )
    result = await check_group_exclusion_status(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        group_uuids=[_GROUP_UUID],
    )
    assert len(result["data"]["group_statuses"]) == 1
    assert result["data"]["group_statuses"][0]["in_exclusion_window"] is False


# ---------------------------------------------------------------------------
# check_window_active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_active_non_mapping_returns_raw() -> None:
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}/is-active": ["something"],
        }
    )
    result = await check_window_active(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_uuid=_WINDOW_UUID,
    )
    assert result["data"]["raw"] == "something"
    assert result["data"]["window_uuid"] == _WINDOW_UUID


# ---------------------------------------------------------------------------
# get_group_scheduled_windows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_scheduled_windows_empty() -> None:
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/group/{_GROUP_UUID}/scheduled-windows": [[]],
        }
    )
    result = await get_group_scheduled_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        group_uuid=_GROUP_UUID,
    )
    assert result["data"]["periods"] == []


@pytest.mark.asyncio
async def test_group_scheduled_windows_mapping_wrapper() -> None:
    """Handle case where API wraps the periods list in a Mapping."""
    periods = [
        {"start": "2026-03-30T02:00:00Z", "end": "2026-03-30T04:00:00Z", "window_type": "exclude"},
    ]
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/group/{_GROUP_UUID}/scheduled-windows": [
                {"data": periods},
            ],
        }
    )
    result = await get_group_scheduled_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        group_uuid=_GROUP_UUID,
    )
    assert len(result["data"]["periods"]) == 1


# ---------------------------------------------------------------------------
# get_device_scheduled_windows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_scheduled_windows_mapping_wrapper() -> None:
    periods = [
        {"start": "2026-03-30T02:00:00Z", "end": "2026-03-30T04:00:00Z", "window_type": "exclude"},
    ]
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/device/{_DEVICE_UUID}/scheduled-windows": [
                {"periods": periods},
            ],
        }
    )
    result = await get_device_scheduled_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        device_uuid=_DEVICE_UUID,
    )
    assert len(result["data"]["periods"]) == 1


@pytest.mark.asyncio
async def test_device_scheduled_windows_no_date_param() -> None:
    """When date is omitted, no query params should be sent."""
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/device/{_DEVICE_UUID}/scheduled-windows": [[]],
        }
    )
    await get_device_scheduled_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        device_uuid=_DEVICE_UUID,
    )
    assert client.calls[0][2] is None
