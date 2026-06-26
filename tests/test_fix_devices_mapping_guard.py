"""Regression tests for the ``/servers`` page Mapping guard.

Three ``/servers`` consumers in ``workflows.devices`` iterate page elements
calling ``item.get(...)``. A page containing a non-Mapping element (a bare list
with a scalar row) used to raise ``AttributeError`` and fail the whole tool.
Each consumer must now skip the scalar and still process the valid Mapping rows.

The sibling ``list_devices_needing_attention`` already filters its list to
Mappings; these tests pin the same behaviour for the three former outliers.
"""

from typing import Any

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.devices import (
    list_device_inventory,
    search_devices,
    summarize_device_health,
)

# A page that mixes one scalar (non-Mapping) row with two real device dicts.
# `managed: True` so the default include_unmanaged=False filtering keeps them.
_MIXED_SERVERS_PAGE: list[Any] = [
    "not-a-device",  # scalar element that would break a bare item.get(...)
    {"id": 1, "name": "host-1", "managed": True, "compliant": True},
    {"id": 2, "name": "host-2", "managed": True, "compliant": False},
]


def _stub_servers(page: list[Any]) -> StubClient:
    """StubClient whose `/servers` page is returned once (subsequent pages empty)."""
    return StubClient(get_responses={"/servers": [page, []]})


@pytest.mark.asyncio
async def test_list_device_inventory_skips_non_mapping_rows() -> None:
    client = _stub_servers(_MIXED_SERVERS_PAGE)

    result = await list_device_inventory(cast_client(client))

    devices = result["data"]["devices"]
    assert result["data"]["total_devices_returned"] == 2
    assert {d["device_id"] for d in devices} == {1, 2}


@pytest.mark.asyncio
async def test_search_devices_skips_non_mapping_rows() -> None:
    client = _stub_servers(_MIXED_SERVERS_PAGE)

    result = await search_devices(cast_client(client))

    devices = result["data"]["devices"]
    assert result["data"]["matches"] == 2
    assert {d["device_id"] for d in devices} == {1, 2}


@pytest.mark.asyncio
async def test_summarize_device_health_skips_non_mapping_rows() -> None:
    client = _stub_servers(_MIXED_SERVERS_PAGE)

    result = await summarize_device_health(cast_client(client))

    data = result["data"]
    # Two valid managed devices counted (the scalar row contributes nothing).
    assert data["total_devices"] == 2
    assert data["compliance_breakdown"] == {"compliant": 1, "non_compliant": 1}


def cast_client(client: StubClient) -> AutomoxClient:
    """Satisfy the AutomoxClient-typed parameter without a real client."""
    return client  # type: ignore[return-value]
