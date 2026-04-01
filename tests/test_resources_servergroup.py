"""Tests for servergroup_resources — verifies the registered resource handler
returns the correct structure and handles edge cases."""

from __future__ import annotations

from typing import Any

import pytest

from automox_mcp.resources import servergroup_resources

# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------


class StubResourceServer:
    """Minimal FastMCP lookalike that captures registered resource functions."""

    def __init__(self) -> None:
        self.resources: dict[str, Any] = {}

    def resource(self, uri: str, **kwargs):
        def decorator(func):
            self.resources[uri] = func
            return func

        return decorator


class FakeClient:
    def __init__(self, *, org_id: int | None = 42) -> None:
        self.org_id = org_id
        self._response: Any = []

    async def get(self, path: str, *, params=None, headers=None) -> Any:
        return self._response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestServerGroupResource:
    @pytest.mark.asyncio
    async def test_returns_server_groups_list(self) -> None:
        client = FakeClient(org_id=42)
        client._response = [
            {
                "id": 1,
                "name": "Production",
                "organization_id": 42,
                "server_count": 10,
                "policies": [101, 102],
            },
            {
                "id": 2,
                "name": "Staging",
                "organization_id": 42,
                "server_count": 3,
                "policies": [],
            },
        ]

        server = StubResourceServer()
        servergroup_resources.register(server, client=client)

        handler = server.resources["resource://servergroups/list"]
        result = await handler()

        assert "server_groups" in result
        assert result["total_count"] == 2
        groups = result["server_groups"]
        assert groups[0]["id"] == 1
        assert groups[0]["name"] == "Production"
        assert groups[0]["policy_count"] == 2
        assert groups[0]["server_count"] == 10
        assert groups[1]["name"] == "Staging"
        assert groups[1]["policy_count"] == 0

    @pytest.mark.asyncio
    async def test_no_org_id_returns_error(self) -> None:
        client = FakeClient(org_id=None)

        server = StubResourceServer()
        servergroup_resources.register(server, client=client)

        handler = server.resources["resource://servergroups/list"]
        result = await handler()

        assert "error" in result

    @pytest.mark.asyncio
    async def test_non_list_api_response_treated_as_empty(self) -> None:
        client = FakeClient(org_id=42)
        client._response = {"unexpected": "dict"}

        server = StubResourceServer()
        servergroup_resources.register(server, client=client)

        handler = server.resources["resource://servergroups/list"]
        result = await handler()

        assert result["total_count"] == 0
        assert result["server_groups"] == []

    @pytest.mark.asyncio
    async def test_group_without_name_uses_unnamed_placeholder(self) -> None:
        client = FakeClient(org_id=42)
        client._response = [
            {
                "id": 99,
                "name": None,
                "organization_id": 42,
                "server_count": 0,
                "policies": [],
            }
        ]

        server = StubResourceServer()
        servergroup_resources.register(server, client=client)

        handler = server.resources["resource://servergroups/list"]
        result = await handler()

        assert result["server_groups"][0]["name"] == "(unnamed)"

    @pytest.mark.asyncio
    async def test_non_dict_entries_in_list_are_skipped(self) -> None:
        client = FakeClient(org_id=42)
        client._response = [
            "not-a-dict",
            None,
            {
                "id": 5,
                "name": "Valid",
                "organization_id": 42,
                "server_count": 1,
                "policies": [],
            },
        ]

        server = StubResourceServer()
        servergroup_resources.register(server, client=client)

        handler = server.resources["resource://servergroups/list"]
        result = await handler()

        assert result["total_count"] == 1
        assert result["server_groups"][0]["id"] == 5

    @pytest.mark.asyncio
    async def test_result_contains_note_field(self) -> None:
        client = FakeClient(org_id=42)
        client._response = []

        server = StubResourceServer()
        servergroup_resources.register(server, client=client)

        handler = server.resources["resource://servergroups/list"]
        result = await handler()

        assert "note" in result
