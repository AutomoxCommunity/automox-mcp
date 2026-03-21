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


class FakeClient:
    """Minimal client stub for tool registration tests."""

    def __init__(self, *, org_id=42, org_uuid=None, account_uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"):
        self.org_id = org_id
        self.org_uuid = org_uuid
        self.account_uuid = account_uuid

    async def get(self, path, *, params=None, headers=None):
        if path == "/orgs":
            return [{"id": self.org_id, "org_uuid": "cccccccc-cccc-cccc-cccc-cccccccccccc"}]
        return {}


def success_result():
    return {"data": {}, "metadata": {"deprecated_endpoint": False}}


@pytest.mark.asyncio
async def test_policy_tool_creates_client(monkeypatch):
    async def fake_workflow(client, **kwargs):
        return success_result()

    monkeypatch.setattr(policy_tools.workflows, "summarize_policy_activity", fake_workflow)

    fake_client = FakeClient(org_uuid=str(UUID("56c0ba07-69f2-4f7c-b0a1-2bb0ed68578e")))

    server = StubServer()
    policy_tools.register(server, client=fake_client)
    tool_fn = server.tools["policy_health_overview"]

    await tool_fn(org_uuid=str(UUID("56c0ba07-69f2-4f7c-b0a1-2bb0ed68578e")))


@pytest.mark.asyncio
async def test_policy_tool_resolves_org_uuid(monkeypatch):
    resolved_uuid = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

    recorded = {"calls": []}

    async def fake_workflow(client, **kwargs):
        recorded["calls"].append(kwargs)
        return success_result()

    monkeypatch.setattr(policy_tools.workflows, "summarize_policy_activity", fake_workflow)

    fake_client = FakeClient(org_id=123)

    server = StubServer()
    policy_tools.register(server, client=fake_client)
    tool_fn = server.tools["policy_health_overview"]

    await tool_fn()

    assert recorded["calls"], "workflow should have been invoked"


@pytest.mark.asyncio
async def test_policy_catalog_allows_limit_one(monkeypatch):
    recorded = {}

    async def fake_workflow(client, **kwargs):
        recorded["kwargs"] = kwargs
        return success_result()

    monkeypatch.setattr(policy_tools.workflows, "summarize_policies", fake_workflow)

    server = StubServer()
    policy_tools.register(server, client=FakeClient(org_id=7))
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

    server = StubServer()
    policy_tools.register(server, client=FakeClient(org_id=10))
    tool_fn = server.tools["policy_detail"]

    await tool_fn(policy_id=12345, include_recent_runs=0)
    assert recorded["kwargs"]["include_recent_runs"] == 0


@pytest.mark.asyncio
async def test_device_tool_creates_client(monkeypatch):
    async def fake_workflow(client, **kwargs):
        return success_result()

    monkeypatch.setattr(device_tools.workflows, "list_device_inventory", fake_workflow)

    server = StubServer()
    device_tools.register(server, client=FakeClient())
    tool_fn = server.tools["list_devices"]

    await tool_fn()


@pytest.mark.asyncio
async def test_account_tools_use_env_fallback(monkeypatch):
    account_uuid = "56c0ba07-69f2-4f7c-b0a1-2bb0ed68578e"

    async def fake_invite(client, **kwargs):
        assert str(kwargs["account_id"]) == account_uuid
        return success_result()

    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", account_uuid)
    monkeypatch.setattr(account_tools.workflows, "invite_user_to_account", fake_invite)

    server = StubServer()
    account_tools.register(server, client=FakeClient())
    tool_fn = server.tools["invite_user_to_account"]

    await tool_fn(email="user@example.com", account_rbac_role="global-admin")


@pytest.mark.asyncio
async def test_account_tools_error_when_env_missing(monkeypatch):
    monkeypatch.delenv("AUTOMOX_ACCOUNT_UUID", raising=False)

    server = StubServer()
    account_tools.register(server, client=FakeClient())
    tool_fn = server.tools["remove_user_from_account"]

    with pytest.raises(ToolError):
        await tool_fn(user_id="1234")
