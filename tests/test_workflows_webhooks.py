"""Tests for webhook workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.webhooks import (
    create_webhook,
    delete_webhook,
    get_webhook,
    list_webhook_deliveries,
    list_webhook_event_types,
    list_webhooks,
    rotate_webhook_secret,
    update_webhook,
)
from automox_mcp.workflows.webhooks import (
    test_webhook as send_test_webhook,
)

_ORG_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

_WEBHOOK_A: dict[str, Any] = {
    "id": "wh-001",
    "name": "Deploy Hook",
    "url": "https://example.com/hook",
    "enabled": True,
    "eventTypes": ["device.compliant", "policy.action"],
    "createdAt": "2026-01-01T00:00:00Z",
    "updatedAt": "2026-01-02T00:00:00Z",
}

_WEBHOOK_B: dict[str, Any] = {
    "id": "wh-002",
    "name": "Alert Hook",
    "url": "https://example.com/alert",
    "enabled": False,
    "eventTypes": ["device.noncompliant"],
    "createdAt": "2026-02-01T00:00:00Z",
    "updatedAt": None,
}


# ---------------------------------------------------------------------------
# list_webhook_event_types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_event_types_returns_mapping() -> None:
    client = StubClient(
        get_responses={
            "/webhooks/event-types": [{"categories": {"device": ["compliant", "noncompliant"]}}],
        }
    )
    result = await list_webhook_event_types(cast(AutomoxClient, client))
    assert "categories" in result["data"]


@pytest.mark.asyncio
async def test_list_event_types_wraps_list_response() -> None:
    client = StubClient(
        get_responses={
            "/webhooks/event-types": [["device.compliant", "device.noncompliant"]],
        }
    )
    result = await list_webhook_event_types(cast(AutomoxClient, client))
    assert result["data"]["event_types"] == ["device.compliant", "device.noncompliant"]


# ---------------------------------------------------------------------------
# list_webhooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_returns_summaries() -> None:
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [{"data": [_WEBHOOK_A, _WEBHOOK_B]}],
        }
    )
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID)

    assert result["data"]["webhooks_returned"] == 2
    # No upstream total in this payload, so no grand-total field is emitted.
    assert "total_webhooks" not in result["data"]
    names = [w["name"] for w in result["data"]["webhooks"]]
    assert "Deploy Hook" in names
    assert "Alert Hook" in names


@pytest.mark.asyncio
async def test_list_webhooks_passes_cursor() -> None:
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [
                {"data": [_WEBHOOK_A], "nextCursor": "abc123"},
            ],
        }
    )
    result = await list_webhooks(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        cursor="prev",
        limit=1,
    )

    assert result["data"]["next_cursor"] == "abc123"
    assert client.calls[0][2] == {"cursor": "prev", "limit": 1}


@pytest.mark.asyncio
async def test_list_webhooks_handles_flat_list() -> None:
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [[_WEBHOOK_A]],
        }
    )
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID)
    assert result["data"]["webhooks_returned"] == 1


# ---------------------------------------------------------------------------
# get_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_webhook_returns_detail() -> None:
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001": [_WEBHOOK_A],
        }
    )
    result = await get_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
    )

    assert result["data"]["name"] == "Deploy Hook"
    assert result["data"]["enabled"] is True


@pytest.mark.asyncio
async def test_get_webhook_unwraps_data_envelope() -> None:
    """A single-object get response wrapped in a `data` envelope surfaces fields."""
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001": [{"data": _WEBHOOK_A}],
        }
    )
    result = await get_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
    )

    assert result["data"]["name"] == "Deploy Hook"
    assert result["data"]["id"] == "wh-001"
    assert result["data"]["enabled"] is True


# ---------------------------------------------------------------------------
# list_webhook_deliveries
# ---------------------------------------------------------------------------

_DELIVERY_A: dict[str, Any] = {
    "id": "c9bf9e57-1685-4c89-bafb-ff5af830be8a",
    "eventType": "policy.evaluated",
    "success": True,
    "statusCode": 200,
    "error": None,
    "durationMs": 150,
    "timestamp": "2026-01-15T10:30:00Z",
}

_DELIVERY_B: dict[str, Any] = {
    "id": "d1e2f3a4-1685-4c89-bafb-ff5af830be8a",
    "eventType": "device.noncompliant",
    "success": False,
    "statusCode": 504,
    "error": "Connection timeout",
    "durationMs": 5000,
    "timestamp": "2026-01-14T09:00:00Z",
}


@pytest.mark.asyncio
async def test_list_deliveries_returns_summaries_and_total() -> None:
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/deliveries": [
                {"data": [_DELIVERY_A, _DELIVERY_B], "meta": {"total": 2, "cursor": None}},
            ],
        }
    )
    result = await list_webhook_deliveries(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
    )

    assert result["data"]["total_deliveries"] == 2
    assert result["data"]["webhook_id"] == "wh-001"
    statuses = [d["statusCode"] for d in result["data"]["deliveries"]]
    assert statuses == [200, 504]
    assert result["metadata"]["pagination"]["has_more"] is False


@pytest.mark.asyncio
async def test_list_deliveries_surfaces_cursor() -> None:
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/deliveries": [
                {"data": [_DELIVERY_A], "meta": {"total": 1, "cursor": "next-page-token"}},
            ],
        }
    )
    result = await list_webhook_deliveries(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
        limit=1,
        cursor="prev",
        start_date="2026-01-01T00:00:00Z",
        end_date="2026-01-31T00:00:00Z",
    )

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    assert pagination["next_cursor"] == "next-page-token"
    assert client.calls[0][2] == {
        "limit": 1,
        "cursor": "prev",
        "startDate": "2026-01-01T00:00:00Z",
        "endDate": "2026-01-31T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_list_deliveries_handles_flat_list() -> None:
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/deliveries": [[_DELIVERY_A]],
        }
    )
    result = await list_webhook_deliveries(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
    )
    assert result["data"]["total_deliveries"] == 1
    assert result["metadata"]["pagination"]["has_more"] is False


# ---------------------------------------------------------------------------
# create_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_webhook_returns_secret() -> None:
    created = {**_WEBHOOK_A, "secret": "s3cr3t-key"}
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [created],
        }
    )
    result = await create_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        name="Deploy Hook",
        url="https://example.com/hook",
        event_types=["device.compliant"],
    )

    assert result["data"]["secret"] == "s3cr3t-key"
    assert "SAVE THE SECRET" in result["data"]["_important"]


@pytest.mark.asyncio
async def test_create_webhook_unwraps_data_envelope() -> None:
    """A single-object create response wrapped in a top-level `data` envelope
    still surfaces the real fields — including the one-time signing secret."""
    enveloped = {"data": {**_WEBHOOK_A, "secret": "whsec_live_abc123"}}
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [enveloped],
        }
    )
    result = await create_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        name="Deploy Hook",
        url="https://example.com/hook",
        event_types=["device.compliant"],
    )

    assert result["data"]["secret"] == "whsec_live_abc123"
    assert result["data"]["id"] == "wh-001"
    assert result["data"]["name"] == "Deploy Hook"


@pytest.mark.asyncio
async def test_create_webhook_flat_response_still_works() -> None:
    """A flat (un-enveloped) create response is unchanged — no regression."""
    created = {**_WEBHOOK_A, "secret": "s3cr3t-key"}
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [created],
        }
    )
    result = await create_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        name="Deploy Hook",
        url="https://example.com/hook",
        event_types=["device.compliant"],
    )

    assert result["data"]["secret"] == "s3cr3t-key"
    assert result["data"]["id"] == "wh-001"


@pytest.mark.asyncio
async def test_create_webhook_sends_correct_body() -> None:
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [_WEBHOOK_A],
        }
    )
    await create_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        name="Deploy Hook",
        url="https://example.com/hook",
        event_types=["device.compliant", "policy.action"],
    )

    body = client.calls[0][2]
    assert body["name"] == "Deploy Hook"
    assert body["url"] == "https://example.com/hook"
    assert body["eventTypes"] == ["device.compliant", "policy.action"]


# ---------------------------------------------------------------------------
# update_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_webhook_partial_update() -> None:
    updated = {**_WEBHOOK_A, "enabled": False}
    client = StubClient(
        patch_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001": [updated],
        }
    )
    result = await update_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
        enabled=False,
    )

    assert result["data"]["updated"] is True
    assert result["data"]["enabled"] is False
    body = client.calls[0][2]
    assert body == {"enabled": False}


@pytest.mark.asyncio
async def test_update_webhook_unwraps_data_envelope() -> None:
    """A single-object update response wrapped in a `data` envelope surfaces fields."""
    client = StubClient(
        patch_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001": [
                {"data": {**_WEBHOOK_A, "enabled": False}},
            ],
        }
    )
    result = await update_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
        enabled=False,
    )

    assert result["data"]["updated"] is True
    assert result["data"]["name"] == "Deploy Hook"
    assert result["data"]["enabled"] is False


@pytest.mark.asyncio
async def test_update_webhook_omits_none_fields() -> None:
    client = StubClient(
        patch_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001": [_WEBHOOK_A],
        }
    )
    await update_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
        name="Renamed",
    )

    body = client.calls[0][2]
    assert body == {"name": "Renamed"}
    assert "url" not in body
    assert "enabled" not in body


# ---------------------------------------------------------------------------
# delete_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_webhook_returns_confirmation() -> None:
    client = StubClient()
    result = await delete_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
    )

    assert result["data"]["deleted"] is True
    assert result["data"]["webhook_id"] == "wh-001"
    assert client.calls[0] == ("DELETE", f"/organizations/{_ORG_UUID}/webhooks/wh-001", None)


# ---------------------------------------------------------------------------
# test_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_webhook_returns_status() -> None:
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/test": [
                {"success": True, "statusCode": 200, "responseTime": 42},
            ],
        }
    )
    result = await send_test_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
    )

    assert result["data"]["success"] is True
    assert result["data"]["statusCode"] == 200
    assert result["data"]["tested"] is True


# ---------------------------------------------------------------------------
# rotate_webhook_secret
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_secret_returns_new_secret() -> None:
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/secret/rotate": [
                {"secret": "new-s3cr3t"},
            ],
        }
    )
    result = await rotate_webhook_secret(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
    )

    assert result["data"]["secret"] == "new-s3cr3t"
    assert result["data"]["rotated"] is True
    assert "SAVE THE NEW SECRET" in result["data"]["_important"]
