"""Regression test for null-`policies` defect in the servergroups list resource.

When a server group's ``policies`` key is explicitly ``null`` (not absent), the
``.get("policies", [])`` default does not apply — ``.get`` returns ``None`` and
``len(None)`` raised a ``TypeError`` that crashed the entire resource read,
breaking server_group_id -> name resolution for the whole session.
"""

from __future__ import annotations

from typing import Any

import pytest

from automox_mcp.resources import servergroup_resources


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


class TestServerGroupNullPolicies:
    @pytest.mark.asyncio
    async def test_null_policies_yields_zero_policy_count(self) -> None:
        client = FakeClient(org_id=42)
        client._response = [
            {
                "id": 7,
                "name": "Null Policies",
                "organization_id": 42,
                "server_count": 4,
                "policies": None,
            }
        ]

        server = StubResourceServer()
        servergroup_resources.register(server, client=client)

        handler = server.resources["resource://servergroups/list"]
        result = await handler()

        assert result["total_count"] == 1
        assert result["server_groups"][0]["policy_count"] == 0
