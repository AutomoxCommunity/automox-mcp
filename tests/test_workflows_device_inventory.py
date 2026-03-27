"""Tests for automox_mcp.workflows.device_inventory."""

from __future__ import annotations

from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.device_inventory import (
    get_device_inventory,
    get_device_inventory_categories,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

ORG_UUID = "aaaa-bbbb-cccc-dddd"
DEVICE_UUID = "1111-2222-3333-4444"


def _orgs_payload():
    return [{"id": 42, "org_uuid": ORG_UUID}]


def _device_payload():
    return {"id": 100, "uuid": DEVICE_UUID}


def _inventory_payload():
    return {
        "categories": {
            "Hardware": {
                "sub_categories": {
                    "CPU": {
                        "data": [
                            {
                                "name": "cpu_model",
                                "friendly_name": "CPU Model",
                                "value": "Intel Core i9",
                                "type": "string",
                                "collected_at": "2026-03-01T00:00:00Z",
                            }
                        ]
                    }
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# get_device_inventory tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_inventory_basic():
    client = StubClient(
        get_responses={
            "/orgs": [_orgs_payload()],
            "/servers/": [_device_payload()],
            "/device-details/": [_inventory_payload()],
        }
    )
    result = await get_device_inventory(
        cast(AutomoxClient, client),
        org_id=42,
        device_id=100,
    )

    data = result["data"]
    assert data["device_id"] == 100
    assert data["device_uuid"] == DEVICE_UUID
    assert data["total_categories"] == 1
    assert data["total_items"] == 1

    hw = data["categories"]["Hardware"]
    assert hw["name"] == "Hardware"
    cpu_sub = hw["sub_categories"]["CPU"]
    assert cpu_sub["item_count"] == 1
    item = cpu_sub["items"][0]
    assert item["name"] == "cpu_model"
    assert item["value"] == "Intel Core i9"

    meta = result["metadata"]
    assert meta["org_id"] == 42
    assert meta["org_uuid"] == ORG_UUID
    assert meta["device_uuid"] == DEVICE_UUID
    assert meta["deprecated_endpoint"] is False


@pytest.mark.asyncio
async def test_get_device_inventory_empty_categories():
    inventory = {"categories": {}}
    client = StubClient(
        get_responses={
            "/orgs": [_orgs_payload()],
            "/servers/": [_device_payload()],
            "/device-details/": [inventory],
        }
    )
    result = await get_device_inventory(
        cast(AutomoxClient, client),
        org_id=42,
        device_id=100,
    )

    assert result["data"]["total_categories"] == 0
    assert result["data"]["total_items"] == 0
    assert result["data"]["categories"] == {}


@pytest.mark.asyncio
async def test_get_device_inventory_missing_org_id_raises():
    client = StubClient()
    client.org_id = None
    with pytest.raises(ValueError, match="org_id required"):
        await get_device_inventory(
            cast(AutomoxClient, client),
            device_id=100,
        )


@pytest.mark.asyncio
async def test_get_device_inventory_missing_device_uuid_raises():
    # Device response has no uuid field → should raise ValueError
    client = StubClient(
        get_responses={
            "/orgs": [_orgs_payload()],
            "/servers/": [{"id": 100}],  # no uuid
        }
    )
    with pytest.raises(ValueError, match="Could not resolve UUID"):
        await get_device_inventory(
            cast(AutomoxClient, client),
            org_id=42,
            device_id=100,
        )


# ---------------------------------------------------------------------------
# get_device_inventory_categories tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_inventory_categories_basic():
    categories_payload = [
        {"name": "Hardware", "friendly_name": "Hardware"},
        {"name": "Network", "friendly_name": "Network"},
    ]
    client = StubClient(
        get_responses={
            "/orgs": [_orgs_payload()],
            "/servers/": [_device_payload()],
            "/device-details/": [categories_payload],
        }
    )
    result = await get_device_inventory_categories(
        cast(AutomoxClient, client),
        org_id=42,
        device_id=100,
    )

    data = result["data"]
    assert data["device_id"] == 100
    assert data["device_uuid"] == DEVICE_UUID
    assert len(data["categories"]) == 2
    assert data["categories"][0]["name"] == "Hardware"
    assert data["categories"][1]["name"] == "Network"

    meta = result["metadata"]
    assert meta["org_id"] == 42
    assert meta["org_uuid"] == ORG_UUID
    assert meta["deprecated_endpoint"] is False


@pytest.mark.asyncio
async def test_get_device_inventory_categories_empty():
    client = StubClient(
        get_responses={
            "/orgs": [_orgs_payload()],
            "/servers/": [_device_payload()],
            "/device-details/": [[]],
        }
    )
    result = await get_device_inventory_categories(
        cast(AutomoxClient, client),
        org_id=42,
        device_id=100,
    )

    assert result["data"]["categories"] == []


@pytest.mark.asyncio
async def test_get_device_inventory_categories_missing_org_id_raises():
    client = StubClient()
    client.org_id = None
    with pytest.raises(ValueError, match="org_id required"):
        await get_device_inventory_categories(
            cast(AutomoxClient, client),
            device_id=100,
        )
