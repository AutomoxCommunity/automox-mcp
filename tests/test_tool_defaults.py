from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastmcp.exceptions import ToolError

from automox_mcp.tools import account_tools, device_tools, policy_tools


class StubServer:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(self, name: str, description: str, **kwargs):
        def decorator(func):
            self.tools[name] = func
            return func

        return decorator


def success_result():
    return {"data": {}, "metadata": {"deprecated_endpoint": False}}


@pytest.mark.asyncio
async def test_policy_tool_prefers_policyreport(monkeypatch):
    async def fake_workflow(client, **kwargs):
        return success_result()

    monkeypatch.setattr(policy_tools.workflows, "summarize_policy_activity", fake_workflow)

    recorded = []

    class RecordingClient:
        def __init__(self, *, default_api=None, **kwargs):
            recorded.append(default_api)
            self.org_id = 42
            self.org_uuid = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, path, *, params=None, headers=None, api=None):
            raise AssertionError("resolve_org_uuid should not call get when org_uuid provided.")

    monkeypatch.setattr(policy_tools, "AutomoxClient", RecordingClient)

    server = StubServer()
    policy_tools.register(server)
    tool_fn = server.tools["policy_health_overview"]

    await tool_fn(org_uuid=str(UUID("56c0ba07-69f2-4f7c-b0a1-2bb0ed68578e")))
    assert recorded[-1] == "policyreport"


@pytest.mark.asyncio
async def test_policy_tool_resolves_org_uuid(monkeypatch):
    resolved_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    recorded = {"default_api": None, "calls": []}

    async def fake_workflow(client, **kwargs):
        recorded["calls"].append(kwargs)
        assert kwargs["org_uuid"] == resolved_uuid
        return success_result()

    monkeypatch.setattr(policy_tools.workflows, "summarize_policy_activity", fake_workflow)

    class RecordingClient:
        def __init__(self, *, default_api=None, **kwargs):
            recorded["default_api"] = default_api
            self.org_id = 123
            self.org_uuid = None
            self.account_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, path, *, params=None, headers=None, api=None):
            assert path == "/orgs"
            return [
                {"id": 999, "org_uuid": "ffffffff-ffff-ffff-ffff-ffffffffffff"},
                {"id": 123, "org_uuid": str(resolved_uuid)},
            ]

    monkeypatch.setattr(policy_tools, "AutomoxClient", RecordingClient)

    server = StubServer()
    policy_tools.register(server)
    tool_fn = server.tools["policy_health_overview"]

    await tool_fn()

    assert recorded["default_api"] == "policyreport"
    assert recorded["calls"], "workflow should have been invoked"


@pytest.mark.asyncio
async def test_policy_catalog_allows_limit_one(monkeypatch):
    recorded = {}

    async def fake_workflow(client, **kwargs):
        recorded["kwargs"] = kwargs
        return success_result()

    monkeypatch.setattr(policy_tools.workflows, "summarize_policies", fake_workflow)

    class RecordingClient:
        def __init__(self, *, default_api=None, **kwargs):
            self.org_id = 7

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(policy_tools, "AutomoxClient", RecordingClient)

    server = StubServer()
    policy_tools.register(server)
    tool_fn = server.tools["policy_catalog"]

    await tool_fn(limit=1)
    assert recorded["kwargs"]["limit"] == 1


@pytest.mark.asyncio
async def test_policy_detail_allows_zero_recent_runs(monkeypatch):
    recorded = {}

    async def fake_workflow(client, **kwargs):
        recorded["kwargs"] = kwargs
        return success_result()

    monkeypatch.setattr(policy_tools.workflows, "describe_policy", fake_workflow)

    class RecordingClient:
        def __init__(self, *, default_api=None, **kwargs):
            self.org_id = 10

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(policy_tools, "AutomoxClient", RecordingClient)

    server = StubServer()
    policy_tools.register(server)
    tool_fn = server.tools["policy_detail"]

    await tool_fn(policy_id=12345, include_recent_runs=0)
    assert recorded["kwargs"]["include_recent_runs"] == 0


@pytest.mark.asyncio
async def test_device_tool_prefers_console(monkeypatch):
    async def fake_workflow(client, **kwargs):
        return success_result()

    monkeypatch.setattr(device_tools.workflows, "list_device_inventory", fake_workflow)

    recorded = []

    class RecordingClient:
        def __init__(self, *, default_api=None, **kwargs):
            recorded.append(default_api)
            self.org_id = 42

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(device_tools, "AutomoxClient", RecordingClient)

    server = StubServer()
    device_tools.register(server)
    tool_fn = server.tools["list_devices"]

    await tool_fn()
    assert recorded[-1] == "console"


@pytest.mark.asyncio
async def test_account_tools_use_env_fallback(monkeypatch):
    account_uuid = "56c0ba07-69f2-4f7c-b0a1-2bb0ed68578e"

    async def fake_invite(client, **kwargs):
        assert str(kwargs["account_id"]) == account_uuid
        return success_result()

    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", account_uuid)
    monkeypatch.setattr(account_tools.workflows, "invite_user_to_account", fake_invite)

    captured = {}

    class RecordingClient:
        def __init__(self, *, default_api=None, **kwargs):
            captured["default_api"] = default_api

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(account_tools, "AutomoxClient", RecordingClient)

    server = StubServer()
    account_tools.register(server)
    tool_fn = server.tools["invite_user_to_account"]

    await tool_fn(email="user@example.com", account_rbac_role="global-admin")
    assert captured["default_api"] == "console"


@pytest.mark.asyncio
async def test_account_tools_error_when_env_missing(monkeypatch):
    monkeypatch.delenv("AUTOMOX_ACCOUNT_UUID", raising=False)

    server = StubServer()
    account_tools.register(server)
    tool_fn = server.tools["remove_user_from_account"]

    with pytest.raises(ToolError):
        await tool_fn(user_id="1234")
