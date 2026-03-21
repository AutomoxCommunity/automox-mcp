"""Tests for automox_mcp.workflows.events."""

from __future__ import annotations

from typing import cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.events import list_events


class StubClient:
    def __init__(
        self,
        *,
        get_responses=None,
        post_responses=None,
        delete_responses=None,
        org_id=42,
        org_uuid=None,
        account_uuid="test-account",
    ):
        self.org_id = org_id
        self.org_uuid = org_uuid
        self.account_uuid = account_uuid
        self._get = get_responses or {}
        self._post = post_responses or {}
        self._delete = delete_responses or {}

    async def get(self, path, *, params=None, headers=None):
        for prefix, responses in self._get.items():
            if path.startswith(prefix) and responses:
                return responses.pop(0)
        return {}

    async def post(self, path, *, json_data=None, params=None, headers=None):
        for prefix, responses in self._post.items():
            if path.startswith(prefix) and responses:
                return responses.pop(0)
        return {}

    async def delete(self, path, *, params=None, headers=None):
        for prefix, responses in self._delete.items():
            if path.startswith(prefix) and responses:
                return responses.pop(0)
        return {}


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

    assert result["data"]["total_events"] == 2
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

    assert result["data"]["total_events"] == 0
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

    assert result["data"]["total_events"] == 1
    assert result["data"]["events"][0]["id"] == 7
