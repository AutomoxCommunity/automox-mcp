"""Tests for automox_mcp.workflows.events."""

from __future__ import annotations

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.workflows.events import list_events


@pytest.mark.asyncio
async def test_list_events_basic():
    events_payload = [
        {
            "id": 1,
            "name": "patch.success",
            "server_id": 10,
            "server_name": "web-01",
            "policy_id": 5,
            "policy_name": "Weekly Patches",
            "policy_type_name": "patch",
            "user_id": 99,
            "data": {"packages": 3},
            "create_time": "2026-03-01T00:00:00Z",
        },
        {
            "id": 2,
            "name": "scan.complete",
            "server_id": 11,
            "server_name": "db-01",
            "policy_id": None,
            "policy_name": None,
            "policy_type_name": None,
            "user_id": None,
            "data": None,
            "create_time": "2026-03-02T00:00:00Z",
        },
    ]
    client = StubClient(get_responses={"/events": [events_payload]})
    result = await list_events(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["events_returned"] == 2
    assert "total_events" not in result["data"]
    assert len(result["data"]["events"]) == 2
    first = result["data"]["events"][0]
    assert first["id"] == 1
    assert first["name"] == "patch.success"
    assert first["server_name"] == "web-01"
    assert first["policy_name"] == "Weekly Patches"
    assert result["metadata"]["deprecated_endpoint"] is False


@pytest.mark.asyncio
async def test_list_events_empty_response():
    client = StubClient(get_responses={"/events": [[]]})
    result = await list_events(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["events_returned"] == 0
    assert result["data"]["events"] == []


@pytest.mark.asyncio
async def test_list_events_filters_passed_through():
    """Verify optional filter params are accepted without error."""
    client = StubClient(
        get_responses={
            "/events": [
                [
                    {
                        "id": 7,
                        "name": "patch.success",
                        "server_id": 10,
                        "server_name": "host-a",
                        "policy_id": 3,
                        "policy_name": "My Policy",
                        "policy_type_name": "patch",
                        "user_id": 1,
                        "data": None,
                        "create_time": "2026-03-10T12:00:00Z",
                    }
                ]
            ]
        }
    )
    result = await list_events(
        cast(AutomoxClient, client),
        org_id=42,
        page=0,
        limit=25,
        policy_id=3,
        server_id=10,
        user_id=1,
        event_name="patch.success",
        start_date="2026-03-01",
        end_date="2026-03-31",
    )

    assert result["data"]["events_returned"] == 1
    assert result["data"]["events"][0]["id"] == 7


@pytest.mark.asyncio
async def test_list_events_count_only():
    """count_only sends camelCase `countOnly=1` and parses {size, results:[]}.

    Fixture is the real count-mode payload captured from the live API
    (tests/probe_events_count.py): the integer total under `size`, an empty
    `results` list, no event bodies. Asserts BOTH the outgoing request param
    (snake_case `count_only=true` was silently ignored upstream — the v1 bug)
    and the parsed result.
    """
    count_payload = {"size": 1382, "results": []}
    client = StubClient(get_responses={"/events": [count_payload]})
    result = await list_events(
        cast(AutomoxClient, client),
        org_id=42,
        count_only=True,
        event_name="system.patch.applied",
    )

    # Request: camelCase integer countOnly=1, never snake_case count_only.
    _, path, params = client.calls[-1]
    assert path == "/events"
    assert params["countOnly"] == 1
    assert "count_only" not in params

    # Response: total from `size`, no event bodies.
    assert result["data"]["total_events"] == 1382
    assert result["data"]["events"] == []


@pytest.mark.asyncio
async def test_list_events_count_only_false_omits_param():
    """count_only=False must not send countOnly (that's just a normal page)."""
    client = StubClient(get_responses={"/events": [[]]})
    await list_events(cast(AutomoxClient, client), org_id=42, count_only=False)
    _, _, params = client.calls[-1]
    assert "countOnly" not in params


@pytest.mark.asyncio
async def test_list_events_unexpected_dict_shape():
    """Defensive: a dict lacking size/results falls back to an empty list.

    The live API only ever returns a bare list (normal) or {size, results}
    (count mode); any other Mapping is unexpected and yields no events with a
    length-based total of 0.
    """
    client = StubClient(get_responses={"/events": [{"unexpected": "value"}]})
    result = await list_events(cast(AutomoxClient, client), org_id=1)
    assert result["data"]["events_returned"] == 0
    assert result["data"]["events"] == []


@pytest.mark.asyncio
async def test_list_events_non_list_non_dict_response():
    """Unexpected scalar response is wrapped into a single-element list."""
    client = StubClient(get_responses={"/events": ["unexpected"]})
    result = await list_events(cast(AutomoxClient, client), org_id=1)
    # "unexpected" is not a Mapping, so it is skipped; events_returned counts
    # only the events actually returned (0), not the raw page length.
    assert result["data"]["events_returned"] == 0
    assert result["data"]["events"] == []


@pytest.mark.asyncio
async def test_list_events_skips_non_mapping_items():
    """Non-Mapping items in the events list are skipped."""
    events = [
        {
            "id": 1,
            "name": "ok",
            "server_id": 1,
            "server_name": "h",
            "policy_id": None,
            "policy_name": None,
            "policy_type_name": None,
            "user_id": None,
            "data": None,
            "create_time": "2026-01-01T00:00:00Z",
        },
        "not-a-dict",
        42,
    ]
    client = StubClient(get_responses={"/events": [events]})
    result = await list_events(cast(AutomoxClient, client), org_id=1)
    assert result["data"]["events_returned"] == 1
    assert len(result["data"]["events"]) == 1


@pytest.mark.asyncio
async def test_list_events_none_response():
    """None response returns empty events."""
    client = StubClient(get_responses={"/events": [None]})
    result = await list_events(cast(AutomoxClient, client), org_id=1)
    assert result["data"]["events_returned"] == 0
    assert result["data"]["events"] == []


# ---------------------------------------------------------------------------
# Error path tests — API errors propagate through the workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_events_api_error_propagates():
    """AutomoxAPIError from the client must not be swallowed."""
    client = StubClient()

    async def _raise(*a: Any, **kw: Any) -> Any:
        raise AutomoxAPIError("server error", status_code=500)

    client.get = _raise  # type: ignore[assignment]
    with pytest.raises(AutomoxAPIError, match="server error"):
        await list_events(cast(AutomoxClient, client), org_id=1)
