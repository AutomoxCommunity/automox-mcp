"""Regression tests for the list_devices_for_policies blast-radius count (bug #13).

The endpoint returns a ``{"servers": [...]}`` envelope. ``extract_list`` does not
recognize that key, so it wrapped the whole envelope as a single record and
``total_devices`` was always 1 regardless of the real blast radius — a dangerously
misleading pre-flight count before a policy execution/change. These tests assert the
envelope is unwrapped to the real device list, with a fallback for the bare-list /
``{"data": [...]}`` shapes.
"""

from typing import Any, cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy_crud import list_devices_for_policies


class StubClient:
    """Minimal Automox client stub: returns a canned post response."""

    def __init__(self, *, post_responses: dict[str, list[Any]] | None = None) -> None:
        self._post_responses = {key: list(value) for key, value in (post_responses or {}).items()}
        self.org_id: int | None = 555
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

    async def post(
        self,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(("POST", path, params, json_data))
        return self._post_responses[path].pop(0)


_PATH = "/server-groups-api/policies/servers"
_POLS = ["11111111-1111-1111-1111-111111111111"]


@pytest.mark.asyncio
async def test_servers_envelope_counts_real_devices_not_envelope() -> None:
    """{"servers": [d1, d2, d3]} -> total_devices == 3 and devices is the real list."""
    servers = [
        {"id": 1, "name": "host-a"},
        {"id": 2, "name": "host-b"},
        {"id": 3, "name": "host-c"},
    ]
    client = StubClient(post_responses={_PATH: [{"servers": servers}]})

    result = await list_devices_for_policies(cast(AutomoxClient, client), policies=_POLS)

    assert result["data"]["total_devices"] == 3
    # The real device dicts, not the {"servers": ...} envelope wrapped as one record.
    assert result["data"]["devices"] == servers
    assert [d["id"] for d in result["data"]["devices"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_servers_envelope_empty_blast_radius() -> None:
    """An empty blast radius reports 0, not 1."""
    client = StubClient(post_responses={_PATH: [{"servers": []}]})

    result = await list_devices_for_policies(cast(AutomoxClient, client), policies=_POLS)

    assert result["data"]["total_devices"] == 0
    assert result["data"]["devices"] == []


@pytest.mark.asyncio
async def test_bare_list_fallback_still_counts() -> None:
    """Fallback path: a bare list of device dicts is counted directly."""
    devices = [{"id": 1}, {"id": 2}]
    client = StubClient(post_responses={_PATH: [devices]})

    result = await list_devices_for_policies(cast(AutomoxClient, client), policies=_POLS)

    assert result["data"]["total_devices"] == 2
    assert result["data"]["devices"] == devices


@pytest.mark.asyncio
async def test_data_envelope_fallback_still_counts() -> None:
    """Fallback path: a {"data": [...]} envelope is unwrapped by extract_list."""
    devices = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    client = StubClient(post_responses={_PATH: [{"data": devices}]})

    result = await list_devices_for_policies(cast(AutomoxClient, client), policies=_POLS)

    assert result["data"]["total_devices"] == 4
    assert result["data"]["devices"] == devices
