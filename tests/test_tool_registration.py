"""Tests for new tool registration (compound tools, policy CRUD gaps)."""

import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastmcp.exceptions import ToolError

from automox_mcp.tools import compound_tools, policy_tools


class StubServer:
    """Lightweight FastMCP stub that captures tool registrations."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str, description: str, **kwargs):
        def decorator(func):
            self.tools[name] = func
            return func

        return decorator


class FakeClient:
    """Minimal client stub for registration tests."""

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


# ---------------------------------------------------------------------------
# Compound tool registration tests
# ---------------------------------------------------------------------------


class TestCompoundToolRegistration:
    """Verify compound tools register and route correctly."""

    def test_compound_tools_register_both_tools(self) -> None:
        server = StubServer()
        compound_tools.register(server, client=FakeClient())

        assert "get_patch_tuesday_readiness" in server.tools
        assert "get_compliance_snapshot" in server.tools

    @pytest.mark.asyncio
    async def test_patch_tuesday_readiness_invokes_workflow(self, monkeypatch) -> None:
        recorded = {}

        async def fake_workflow(client, **kwargs):
            recorded["kwargs"] = kwargs
            return success_result()

        monkeypatch.setattr(
            compound_tools.workflows.compound,
            "get_patch_tuesday_readiness",
            fake_workflow,
        )

        fake_client = FakeClient(org_id=42)

        server = StubServer()
        compound_tools.register(server, client=fake_client)
        tool_fn = server.tools["get_patch_tuesday_readiness"]

        await tool_fn(group_id=10)
        assert recorded["kwargs"]["org_id"] == 42
        assert recorded["kwargs"]["group_id"] == 10

    @pytest.mark.asyncio
    async def test_compliance_snapshot_invokes_workflow(self, monkeypatch) -> None:
        recorded = {}

        async def fake_workflow(client, **kwargs):
            recorded["kwargs"] = kwargs
            return success_result()

        monkeypatch.setattr(
            compound_tools.workflows.compound,
            "get_compliance_snapshot",
            fake_workflow,
        )

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))
        tool_fn = server.tools["get_compliance_snapshot"]

        await tool_fn()
        assert recorded["kwargs"]["org_id"] == 42

    @pytest.mark.asyncio
    async def test_compound_tool_errors_without_org_id(self) -> None:
        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=None))
        tool_fn = server.tools["get_compliance_snapshot"]

        with pytest.raises(ToolError, match="org_id required"):
            await tool_fn()


# ---------------------------------------------------------------------------
# Policy CRUD tool registration tests
# ---------------------------------------------------------------------------


class TestPolicyCrudToolRegistration:
    """Verify policy CRUD gap tools register and respect read_only."""

    def test_policy_crud_tools_register_in_write_mode(self) -> None:
        server = StubServer()
        policy_tools.register(server, read_only=False, client=FakeClient())

        assert "delete_policy" in server.tools
        assert "clone_policy" in server.tools
        assert "policy_compliance_stats" in server.tools

    def test_policy_crud_write_tools_hidden_in_read_only(self) -> None:
        server = StubServer()
        policy_tools.register(server, read_only=True, client=FakeClient())

        assert "delete_policy" not in server.tools
        assert "clone_policy" not in server.tools
        # Stats is a read tool — should still be present
        assert "policy_compliance_stats" in server.tools

    @pytest.mark.asyncio
    async def test_delete_policy_tool_invokes_workflow(self, monkeypatch) -> None:
        recorded = {}

        async def fake_workflow(client, **kwargs):
            recorded["kwargs"] = kwargs
            return success_result()

        monkeypatch.setattr(policy_tools.workflows, "delete_policy", fake_workflow)

        server = StubServer()
        policy_tools.register(server, client=FakeClient(org_id=42))
        tool_fn = server.tools["delete_policy"]

        await tool_fn(policy_id=901)
        assert recorded["kwargs"]["policy_id"] == 901

    @pytest.mark.asyncio
    async def test_clone_policy_tool_invokes_workflow(self, monkeypatch) -> None:
        recorded = {}

        async def fake_workflow(client, **kwargs):
            recorded["kwargs"] = kwargs
            return success_result()

        monkeypatch.setattr(policy_tools.workflows, "clone_policy", fake_workflow)

        server = StubServer()
        policy_tools.register(server, client=FakeClient(org_id=42))
        tool_fn = server.tools["clone_policy"]

        await tool_fn(policy_id=901, name="My Clone", server_groups=[20, 30])
        assert recorded["kwargs"]["policy_id"] == 901
        assert recorded["kwargs"]["name"] == "My Clone"
        assert recorded["kwargs"]["server_groups"] == [20, 30]

    @pytest.mark.asyncio
    async def test_policy_compliance_stats_tool_invokes_workflow(self, monkeypatch) -> None:
        recorded = {}

        async def fake_workflow(client, **kwargs):
            recorded["called"] = True
            return success_result()

        monkeypatch.setattr(
            policy_tools.workflows, "get_policy_compliance_stats", fake_workflow
        )

        server = StubServer()
        policy_tools.register(server, client=FakeClient(org_id=42))
        tool_fn = server.tools["policy_compliance_stats"]

        await tool_fn()
        assert recorded["called"] is True
