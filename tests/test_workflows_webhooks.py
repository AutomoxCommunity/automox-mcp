"""Tests for webhook workflows."""

import copy
from typing import Any, cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.webhooks import (
    create_webhook,
    delete_webhook,
    get_webhook,
    list_webhook_event_types,
    list_webhooks,
    rotate_webhook_secret,
    update_webhook,
)
from automox_mcp.workflows.webhooks import (
    test_webhook as send_test_webhook,
)

# ---------------------------------------------------------------------------
# Stub client
# ---------------------------------------------------------------------------


class StubClient:
    """Minimal client stub that records calls and returns canned responses."""

    def __init__(
        self,
        *,
        get_responses: dict[str, list[Any]] | None = None,
        post_responses: dict[str, list[Any]] | None = None,
        put_responses: dict[str, list[Any]] | None = None,
        delete_responses: dict[str, list[Any]] | None = None,
    ) -> None:
        self._get = {k: list(v) for k, v in (get_responses or {}).items()}
        self._post = {k: list(v) for k, v in (post_responses or {}).items()}
        self._put = {k: list(v) for k, v in (put_responses or {}).items()}
        self._delete = {k: list(v) for k, v in (delete_responses or {}).items()}
        self.calls: list[tuple[str, str, Any]] = []

    async def get(self, path, *, params=None, headers=None):
        self.calls.append(("GET", path, params))
        responses = self._get.get(path)
        return copy.deepcopy(responses.pop(0)) if responses else {}

    async def post(self, path, *, json_data=None, params=None, headers=None):
        self.calls.append(("POST", path, json_data))
        responses = self._post.get(path)
        return copy.deepcopy(responses.pop(0)) if responses else {}

    async def put(self, path, *, json_data=None, params=None, headers=None):
        self.calls.append(("PUT", path, json_data))
        responses = self._put.get(path)
        return copy.deepcopy(responses.pop(0)) if responses else {}

    async def delete(self, path, *, params=None, headers=None):
        self.calls.append(("DELETE", path, params))
        responses = self._delete.get(path)
        return copy.deepcopy(responses.pop(0)) if responses else None


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
    client = StubClient(get_responses={
        "/webhooks/event-types": [{"categories": {"device": ["compliant", "noncompliant"]}}],
    })
    result = await list_webhook_event_types(cast(AutomoxClient, client))
    assert "categories" in result["data"]


@pytest.mark.asyncio
async def test_list_event_types_wraps_list_response() -> None:
    client = StubClient(get_responses={
        "/webhooks/event-types": [["device.compliant", "device.noncompliant"]],
    })
    result = await list_webhook_event_types(cast(AutomoxClient, client))
    assert result["data"]["event_types"] == ["device.compliant", "device.noncompliant"]


# ---------------------------------------------------------------------------
# list_webhooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_returns_summaries() -> None:
    client = StubClient(get_responses={
        f"/organizations/{_ORG_UUID}/webhooks": [{"data": [_WEBHOOK_A, _WEBHOOK_B]}],
    })
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID)

    assert result["data"]["total_webhooks"] == 2
    names = [w["name"] for w in result["data"]["webhooks"]]
    assert "Deploy Hook" in names
    assert "Alert Hook" in names


@pytest.mark.asyncio
async def test_list_webhooks_passes_cursor() -> None:
    client = StubClient(get_responses={
        f"/organizations/{_ORG_UUID}/webhooks": [
            {"data": [_WEBHOOK_A], "nextCursor": "abc123"},
        ],
    })
    result = await list_webhooks(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, cursor="prev", limit=1,
    )

    assert result["data"]["next_cursor"] == "abc123"
    assert client.calls[0][2] == {"cursor": "prev", "limit": 1}


@pytest.mark.asyncio
async def test_list_webhooks_handles_flat_list() -> None:
    client = StubClient(get_responses={
        f"/organizations/{_ORG_UUID}/webhooks": [[_WEBHOOK_A]],
    })
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID)
    assert result["data"]["total_webhooks"] == 1


# ---------------------------------------------------------------------------
# get_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_webhook_returns_detail() -> None:
    client = StubClient(get_responses={
        f"/organizations/{_ORG_UUID}/webhooks/wh-001": [_WEBHOOK_A],
    })
    result = await get_webhook(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-001",
    )

    assert result["data"]["name"] == "Deploy Hook"
    assert result["data"]["enabled"] is True


# ---------------------------------------------------------------------------
# create_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_webhook_returns_secret() -> None:
    created = {**_WEBHOOK_A, "secret": "s3cr3t-key"}
    client = StubClient(post_responses={
        f"/organizations/{_ORG_UUID}/webhooks": [created],
    })
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
async def test_create_webhook_sends_correct_body() -> None:
    client = StubClient(post_responses={
        f"/organizations/{_ORG_UUID}/webhooks": [_WEBHOOK_A],
    })
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
    client = StubClient(put_responses={
        f"/organizations/{_ORG_UUID}/webhooks/wh-001": [updated],
    })
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
async def test_update_webhook_omits_none_fields() -> None:
    client = StubClient(put_responses={
        f"/organizations/{_ORG_UUID}/webhooks/wh-001": [_WEBHOOK_A],
    })
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
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-001",
    )

    assert result["data"]["deleted"] is True
    assert result["data"]["webhook_id"] == "wh-001"
    assert client.calls[0] == ("DELETE", f"/organizations/{_ORG_UUID}/webhooks/wh-001", None)


# ---------------------------------------------------------------------------
# test_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_webhook_returns_status() -> None:
    client = StubClient(post_responses={
        f"/organizations/{_ORG_UUID}/webhooks/wh-001/test": [
            {"success": True, "statusCode": 200, "responseTime": 42},
        ],
    })
    result = await send_test_webhook(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-001",
    )

    assert result["data"]["success"] is True
    assert result["data"]["statusCode"] == 200
    assert result["data"]["tested"] is True


# ---------------------------------------------------------------------------
# rotate_webhook_secret
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_secret_returns_new_secret() -> None:
    client = StubClient(post_responses={
        f"/organizations/{_ORG_UUID}/webhooks/wh-001/secret/rotate": [
            {"secret": "new-s3cr3t"},
        ],
    })
    result = await rotate_webhook_secret(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-001",
    )

    assert result["data"]["secret"] == "new-s3cr3t"
    assert result["data"]["rotated"] is True
    assert "SAVE THE NEW SECRET" in result["data"]["_important"]
