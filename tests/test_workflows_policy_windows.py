"""Tests for policy windows (maintenance/exclusion windows) workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy_windows import (
    check_group_exclusion_status,
    check_window_active,
    create_policy_window,
    delete_policy_window,
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

_WINDOW_A: dict[str, Any] = {
    "window_uuid": _WINDOW_UUID,
    "window_type": "exclude",
    "window_name": "Nightly Maintenance",
    "window_description": "No patching during nightly backups",
    "org_uuid": _ORG_UUID,
    "rrule": "FREQ=YEARLY;BYMONTH=1,2,3,4,5,6,7,8,9,10,11,12;BYDAY=+1MO",
    "duration_minutes": 120,
    "dtstart": "2026-01-01T02:00:00Z",
    "use_local_tz": False,
    "status": "active",
    "recurrence": "recurring",
    "group_uuids": [_GROUP_UUID],
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
}

_WINDOW_B: dict[str, Any] = {
    "window_uuid": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    "window_type": "exclude",
    "window_name": "Weekend Freeze",
    "window_description": "No changes on weekends",
    "org_uuid": _ORG_UUID,
    "rrule": "FREQ=YEARLY;BYDAY=SA,SU",
    "duration_minutes": 1440,
    "dtstart": "2026-01-04T00:00:00Z",
    "use_local_tz": False,
    "status": "active",
    "recurrence": "recurring",
    "group_uuids": [_GROUP_UUID],
    "created_at": "2026-01-03T00:00:00Z",
    "updated_at": None,
}


# ---------------------------------------------------------------------------
# search_policy_windows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_windows_returns_summaries() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/search": [
                {"content": [_WINDOW_A, _WINDOW_B], "total_elements": 2, "total_pages": 1},
            ],
        }
    )
    result = await search_policy_windows(cast(AutomoxClient, client), org_uuid=_ORG_UUID)

    assert result["data"]["total_windows"] == 2
    names = [w["window_name"] for w in result["data"]["windows"]]
    assert "Nightly Maintenance" in names
    assert "Weekend Freeze" in names
    assert result["data"]["total_elements"] == 2


@pytest.mark.asyncio
async def test_search_windows_passes_filters() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/search": [{"content": [_WINDOW_A]}],
        }
    )
    await search_policy_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        statuses=["active"],
        recurrences=["recurring"],
        page=0,
        size=10,
    )

    body = client.calls[0][2]
    assert body["statuses"] == ["active"]
    assert body["recurrences"] == ["recurring"]
    assert body["page"] == 0
    assert body["size"] == 10


@pytest.mark.asyncio
async def test_search_windows_handles_flat_list() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/search": [[_WINDOW_A]],
        }
    )
    result = await search_policy_windows(cast(AutomoxClient, client), org_uuid=_ORG_UUID)
    assert result["data"]["total_windows"] == 1


# ---------------------------------------------------------------------------
# get_policy_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_window_returns_detail() -> None:
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}": [_WINDOW_A],
        }
    )
    result = await get_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_uuid=_WINDOW_UUID,
    )

    assert result["data"]["window_name"] == "Nightly Maintenance"
    assert result["data"]["duration_minutes"] == 120
    assert result["data"]["status"] == "active"


# ---------------------------------------------------------------------------
# create_policy_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_window_returns_created() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}": [_WINDOW_A],
        }
    )
    result = await create_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_type="exclude",
        window_name="Nightly Maintenance",
        window_description="No patching during nightly backups",
        rrule="FREQ=YEARLY;BYMONTH=1,2,3,4,5,6,7,8,9,10,11,12;BYDAY=+1MO",
        duration_minutes=120,
        use_local_tz=False,
        recurrence="recurring",
        group_uuids=[_GROUP_UUID],
        dtstart="2026-01-01T02:00:00Z",
        status="active",
    )

    assert result["data"]["created"] is True
    assert result["data"]["window_uuid"] == _WINDOW_UUID


@pytest.mark.asyncio
async def test_create_window_sends_correct_body() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}": [_WINDOW_A],
        }
    )
    await create_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_type="exclude",
        window_name="Test",
        window_description="Desc",
        rrule="FREQ=DAILY;UNTIL=20260917T100000Z",
        duration_minutes=60,
        use_local_tz=False,
        recurrence="once",
        group_uuids=[_GROUP_UUID],
        dtstart="2026-09-15T02:00:00Z",
        status="active",
    )

    body = client.calls[0][2]
    assert body["window_type"] == "exclude"
    assert body["window_name"] == "Test"
    assert body["duration_minutes"] == 60
    assert body["recurrence"] == "once"
    assert body["group_uuids"] == [_GROUP_UUID]


# ---------------------------------------------------------------------------
# update_policy_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_window_partial_update() -> None:
    updated = {**_WINDOW_A, "window_name": "Renamed"}
    client = StubClient(
        put_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}": [updated],
        }
    )
    result = await update_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_uuid=_WINDOW_UUID,
        dtstart="2026-01-01T02:00:00Z",
        window_name="Renamed",
    )

    assert result["data"]["updated"] is True
    assert result["data"]["window_name"] == "Renamed"


@pytest.mark.asyncio
async def test_update_window_omits_none_fields() -> None:
    client = StubClient(
        put_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}": [_WINDOW_A],
        }
    )
    await update_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_uuid=_WINDOW_UUID,
        dtstart="2026-01-01T02:00:00Z",
    )

    body = client.calls[0][2]
    assert body == {"dtstart": "2026-01-01T02:00:00Z"}
    assert "window_name" not in body
    assert "rrule" not in body


# ---------------------------------------------------------------------------
# delete_policy_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_window_returns_confirmation() -> None:
    client = StubClient()
    result = await delete_policy_window(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_uuid=_WINDOW_UUID,
    )

    assert result["data"]["deleted"] is True
    assert result["data"]["window_uuid"] == _WINDOW_UUID
    assert client.calls[0] == (
        "DELETE",
        f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}",
        None,
    )


# ---------------------------------------------------------------------------
# check_group_exclusion_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_group_exclusion_status() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/groups/exclusion-status": [
                [
                    {"group_uuid": _GROUP_UUID, "in_exclusion_window": True},
                    {"group_uuid": "other-group", "in_exclusion_window": False},
                ],
            ],
        }
    )
    result = await check_group_exclusion_status(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        group_uuids=[_GROUP_UUID, "other-group"],
    )

    statuses = result["data"]["group_statuses"]
    assert len(statuses) == 2
    assert statuses[0]["group_uuid"] == _GROUP_UUID
    assert statuses[0]["in_exclusion_window"] is True
    assert statuses[1]["in_exclusion_window"] is False


@pytest.mark.asyncio
async def test_check_group_exclusion_sends_body() -> None:
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/groups/exclusion-status": [[]],
        }
    )
    await check_group_exclusion_status(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        group_uuids=[_GROUP_UUID],
    )

    body = client.calls[0][2]
    assert body == {"group_uuids": [_GROUP_UUID]}


# ---------------------------------------------------------------------------
# check_window_active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_window_active_returns_status() -> None:
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}/is-active": [
                {"window_uuid": _WINDOW_UUID, "in_exclusion_window": True},
            ],
        }
    )
    result = await check_window_active(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        window_uuid=_WINDOW_UUID,
    )

    assert result["data"]["window_uuid"] == _WINDOW_UUID
    assert result["data"]["in_exclusion_window"] is True


# ---------------------------------------------------------------------------
# get_group_scheduled_windows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_group_scheduled_windows() -> None:
    periods = [
        {"start": "2026-03-30T02:00:00Z", "end": "2026-03-30T04:00:00Z", "window_type": "exclude"},
        {"start": "2026-04-06T02:00:00Z", "end": "2026-04-06T04:00:00Z", "window_type": "exclude"},
    ]
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/group/{_GROUP_UUID}/scheduled-windows": [periods],
        }
    )
    result = await get_group_scheduled_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        group_uuid=_GROUP_UUID,
    )

    assert result["data"]["group_uuid"] == _GROUP_UUID
    assert len(result["data"]["periods"]) == 2
    assert result["data"]["periods"][0]["window_type"] == "exclude"


@pytest.mark.asyncio
async def test_get_group_scheduled_windows_with_date() -> None:
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/group/{_GROUP_UUID}/scheduled-windows": [[]],
        }
    )
    await get_group_scheduled_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        group_uuid=_GROUP_UUID,
        date="2026-04-30T00:00:00Z",
    )

    # Date is embedded in the path (not params) to avoid colon URL-encoding
    assert "date=2026-04-30T00:00:00" in client.calls[0][1]
    assert client.calls[0][2] is None


# ---------------------------------------------------------------------------
# get_device_scheduled_windows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_scheduled_windows() -> None:
    periods = [
        {"start": "2026-03-30T02:00:00Z", "end": "2026-03-30T04:00:00Z", "window_type": "exclude"},
    ]
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/device/{_DEVICE_UUID}/scheduled-windows": [periods],
        }
    )
    result = await get_device_scheduled_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        device_uuid=_DEVICE_UUID,
    )

    assert result["data"]["device_uuid"] == _DEVICE_UUID
    assert len(result["data"]["periods"]) == 1


@pytest.mark.asyncio
async def test_get_device_scheduled_windows_with_date() -> None:
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/device/{_DEVICE_UUID}/scheduled-windows": [[]],
        }
    )
    await get_device_scheduled_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        device_uuid=_DEVICE_UUID,
        date="2026-04-30T00:00:00Z",
    )

    # Date is embedded in the path (not params) to avoid colon URL-encoding
    assert "date=2026-04-30T00:00:00" in client.calls[0][1]
    assert client.calls[0][2] is None


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_functions_include_metadata() -> None:
    """Every workflow function must return metadata.deprecated_endpoint."""
    client = StubClient(
        get_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}": [_WINDOW_A],
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}/is-active": [
                {"window_uuid": _WINDOW_UUID, "in_exclusion_window": False},
            ],
            f"/policy-windows/org/{_ORG_UUID}/group/{_GROUP_UUID}/scheduled-windows": [[]],
            f"/policy-windows/org/{_ORG_UUID}/device/{_DEVICE_UUID}/scheduled-windows": [[]],
        },
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/search": [{"content": []}],
            f"/policy-windows/org/{_ORG_UUID}/groups/exclusion-status": [[]],
            f"/policy-windows/org/{_ORG_UUID}": [_WINDOW_A],
        },
        put_responses={
            f"/policy-windows/org/{_ORG_UUID}/window/{_WINDOW_UUID}": [_WINDOW_A],
        },
    )
    c = cast(AutomoxClient, client)

    results = [
        await search_policy_windows(c, org_uuid=_ORG_UUID),
        await get_policy_window(c, org_uuid=_ORG_UUID, window_uuid=_WINDOW_UUID),
        await check_group_exclusion_status(c, org_uuid=_ORG_UUID, group_uuids=[_GROUP_UUID]),
        await check_window_active(c, org_uuid=_ORG_UUID, window_uuid=_WINDOW_UUID),
        await get_group_scheduled_windows(c, org_uuid=_ORG_UUID, group_uuid=_GROUP_UUID),
        await get_device_scheduled_windows(c, org_uuid=_ORG_UUID, device_uuid=_DEVICE_UUID),
        await create_policy_window(
            c,
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
        ),
        await update_policy_window(
            c,
            org_uuid=_ORG_UUID,
            window_uuid=_WINDOW_UUID,
            dtstart="2026-01-01T00:00:00Z",
        ),
        await delete_policy_window(c, org_uuid=_ORG_UUID, window_uuid=_WINDOW_UUID),
    ]

    for r in results:
        assert "metadata" in r, f"Missing metadata in {r}"
        assert r["metadata"]["deprecated_endpoint"] is False
