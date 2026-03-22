"""Extended tests for undertested else-branches in automox_mcp.workflows.webhooks."""

from __future__ import annotations

from typing import Any, cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.webhooks import (
    create_webhook,
    get_webhook,
    list_webhook_event_types,
    list_webhooks,
    rotate_webhook_secret,
    update_webhook,
)
from automox_mcp.workflows.webhooks import (
    test_webhook as send_test_webhook,
)
from conftest import StubClient

_ORG_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

# ---------------------------------------------------------------------------
# list_webhook_event_types — line 36: else branch (non-Mapping, non-list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_event_types_non_mapping_non_list_wrapped_in_raw() -> None:
    """When the API returns a scalar, it is wrapped under 'raw'."""
    client = StubClient(
        get_responses={"/webhooks/event-types": ["plain-string-response"]}
    )
    result = await list_webhook_event_types(cast(AutomoxClient, client))
    assert result["data"] == {"raw": "plain-string-response"}
    assert result["metadata"]["deprecated_endpoint"] is False


# ---------------------------------------------------------------------------
# list_webhooks — no explicit else for non-Mapping/non-list; already covered
# but we test the cursor passed through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_empty_mapping_returns_zero() -> None:
    """An API mapping with no 'data' or 'webhooks' key yields zero webhooks."""
    client = StubClient(
        get_responses={f"/organizations/{_ORG_UUID}/webhooks": [{}]}
    )
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID)
    assert result["data"]["total_webhooks"] == 0
    assert result["data"]["webhooks"] == []


@pytest.mark.asyncio
async def test_list_webhooks_next_cursor_from_next_cursor_key() -> None:
    """next_cursor is read from 'next_cursor' fallback key."""
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [
                {"data": [], "next_cursor": "cursor-xyz"}
            ]
        }
    )
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID)
    assert result["data"]["next_cursor"] == "cursor-xyz"


# ---------------------------------------------------------------------------
# get_webhook — line 106: else branch (non-Mapping response)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_webhook_non_mapping_response_returns_raw() -> None:
    """When the API returns a non-Mapping, raw value is surfaced."""
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-nope": ["unexpected-string"]
        }
    )
    result = await get_webhook(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-nope"
    )
    data = result["data"]
    assert data["webhook_id"] == "wh-nope"
    assert data["raw"] == "unexpected-string"


@pytest.mark.asyncio
async def test_get_webhook_integer_response_returns_raw() -> None:
    client = StubClient(
        get_responses={f"/organizations/{_ORG_UUID}/webhooks/wh-int": [42]}
    )
    result = await get_webhook(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-int"
    )
    assert result["data"]["raw"] == 42


# ---------------------------------------------------------------------------
# create_webhook — line 154: else branch (non-Mapping response)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_webhook_non_mapping_response() -> None:
    """When the API returns a non-Mapping on create, created=True with raw value."""
    client = StubClient(
        post_responses={f"/organizations/{_ORG_UUID}/webhooks": ["created-ok"]}
    )
    result = await create_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        name="My Hook",
        url="https://example.com/hook",
        event_types=["device.compliant"],
    )
    data = result["data"]
    assert data["created"] is True
    assert data["raw"] == "created-ok"
    # _important message should NOT be present in this branch
    assert "_important" not in data


@pytest.mark.asyncio
async def test_create_webhook_none_response() -> None:
    """None response is also non-Mapping."""
    client = StubClient(
        post_responses={f"/organizations/{_ORG_UUID}/webhooks": [None]}
    )
    result = await create_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        name="Hook",
        url="https://example.com/hook",
        event_types=[],
    )
    assert result["data"]["created"] is True
    assert result["data"]["raw"] is None


# ---------------------------------------------------------------------------
# update_webhook — line 195: else branch (non-Mapping response)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_webhook_non_mapping_response() -> None:
    """When the API returns a non-Mapping on update, returns updated=True with raw."""
    client = StubClient(
        put_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001": ["ok-string"]
        }
    )
    result = await update_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-001",
        name="Renamed",
    )
    data = result["data"]
    assert data["webhook_id"] == "wh-001"
    assert data["updated"] is True
    assert data["raw"] == "ok-string"


@pytest.mark.asyncio
async def test_update_webhook_integer_response() -> None:
    client = StubClient(
        put_responses={f"/organizations/{_ORG_UUID}/webhooks/wh-002": [204]}
    )
    result = await update_webhook(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        webhook_id="wh-002",
        enabled=True,
    )
    assert result["data"]["updated"] is True
    assert result["data"]["raw"] == 204


# ---------------------------------------------------------------------------
# test_webhook — line 246: else branch (non-Mapping response)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_webhook_non_mapping_response() -> None:
    """When the test endpoint returns a non-Mapping, tested=True with raw value."""
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/test": ["delivery-ok"]
        }
    )
    result = await send_test_webhook(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-001"
    )
    data = result["data"]
    assert data["webhook_id"] == "wh-001"
    assert data["tested"] is True
    assert data["raw"] == "delivery-ok"


@pytest.mark.asyncio
async def test_test_webhook_none_response() -> None:
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/test": [None]
        }
    )
    result = await send_test_webhook(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-001"
    )
    assert result["data"]["tested"] is True
    assert result["data"]["raw"] is None


# ---------------------------------------------------------------------------
# rotate_webhook_secret — line 283: else branch (non-Mapping response)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_secret_non_mapping_response() -> None:
    """When the rotate endpoint returns a non-Mapping, rotated=True with raw value."""
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/secret/rotate": [
                "new-secret-string"
            ]
        }
    )
    result = await rotate_webhook_secret(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-001"
    )
    data = result["data"]
    assert data["webhook_id"] == "wh-001"
    assert data["rotated"] is True
    assert data["raw"] == "new-secret-string"
    # _important should NOT be present in the else branch
    assert "_important" not in data


@pytest.mark.asyncio
async def test_rotate_secret_none_response() -> None:
    client = StubClient(
        post_responses={
            f"/organizations/{_ORG_UUID}/webhooks/wh-001/secret/rotate": [None]
        }
    )
    result = await rotate_webhook_secret(
        cast(AutomoxClient, client), org_uuid=_ORG_UUID, webhook_id="wh-001"
    )
    assert result["data"]["rotated"] is True
    assert result["data"]["raw"] is None


# ---------------------------------------------------------------------------
# Smoke tests: metadata is always present and well-formed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_webhook_functions_include_metadata() -> None:
    """Every webhook workflow must return a metadata dict with deprecated_endpoint."""
    wh_path = f"/organizations/{_ORG_UUID}/webhooks"

    client_get = StubClient(get_responses={f"{wh_path}/wh-x": [None]})
    r = await get_webhook(cast(AutomoxClient, client_get), org_uuid=_ORG_UUID, webhook_id="wh-x")
    assert r["metadata"]["deprecated_endpoint"] is False

    client_create = StubClient(post_responses={wh_path: [None]})
    r = await create_webhook(
        cast(AutomoxClient, client_create),
        org_uuid=_ORG_UUID,
        name="H",
        url="https://x.com",
        event_types=[],
    )
    assert r["metadata"]["deprecated_endpoint"] is False

    client_update = StubClient(put_responses={f"{wh_path}/wh-x": [None]})
    r = await update_webhook(
        cast(AutomoxClient, client_update), org_uuid=_ORG_UUID, webhook_id="wh-x"
    )
    assert r["metadata"]["deprecated_endpoint"] is False

    client_test = StubClient(post_responses={f"{wh_path}/wh-x/test": [None]})
    r = await send_test_webhook(
        cast(AutomoxClient, client_test), org_uuid=_ORG_UUID, webhook_id="wh-x"
    )
    assert r["metadata"]["deprecated_endpoint"] is False

    client_rotate = StubClient(post_responses={f"{wh_path}/wh-x/secret/rotate": [None]})
    r = await rotate_webhook_secret(
        cast(AutomoxClient, client_rotate), org_uuid=_ORG_UUID, webhook_id="wh-x"
    )
    assert r["metadata"]["deprecated_endpoint"] is False
