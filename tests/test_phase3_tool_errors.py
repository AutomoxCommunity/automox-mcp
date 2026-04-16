"""Tests for Phase 3 tool error handling and edge cases."""

from __future__ import annotations

import pytest
from conftest import FakeClient, StubServer
from fastmcp.exceptions import ToolError

from automox_mcp.client import AutomoxAPIError
from automox_mcp.tools import (
    account_tools,
    audit_v2_tools,
    data_extract_tools,
    device_search_tools,
    policy_history_tools,
    vuln_sync_tools,
    worklet_tools,
)

# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------


def _register(module, client: FakeClient, read_only: bool = False) -> StubServer:
    server = StubServer()
    module.register(server, read_only=read_only, client=client)
    return server


# ---------------------------------------------------------------------------
# Worklet tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worklet_search_success() -> None:
    client = FakeClient()
    client._get_response = [{"id": "w-1", "name": "Test", "category": "Security"}]
    server = _register(worklet_tools, client)
    result = await server.tools["search_worklet_catalog"]()
    assert result["data"]["total_worklets"] == 1


@pytest.mark.asyncio
async def test_worklet_search_api_error() -> None:
    client = FakeClient()

    async def _err(*a, **kw):
        raise AutomoxAPIError("fail", status_code=500)

    client.get = _err
    server = _register(worklet_tools, client)
    with pytest.raises(ToolError, match="fail"):
        await server.tools["search_worklet_catalog"]()


@pytest.mark.asyncio
async def test_worklet_detail_success() -> None:
    client = FakeClient()
    client._get_response = {"id": "w-1", "name": "Test"}
    server = _register(worklet_tools, client)
    result = await server.tools["get_worklet_detail"](item_id="w-1")
    assert result["data"]["id"] == "w-1"


# ---------------------------------------------------------------------------
# Data extract tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_extract_list_success() -> None:
    client = FakeClient()
    client._get_response = [{"id": "e-1", "name": "Extract", "status": "done"}]
    server = _register(data_extract_tools, client)
    result = await server.tools["list_data_extracts"]()
    assert result["data"]["total_extracts"] == 1


@pytest.mark.asyncio
async def test_data_extract_create_success() -> None:
    client = FakeClient()
    client._post_response = {"id": "e-new", "status": "pending"}
    server = _register(data_extract_tools, client, read_only=False)
    result = await server.tools["create_data_extract"](extract_data={"type": "devices"})
    assert result["data"]["id"] == "e-new"


@pytest.mark.asyncio
async def test_data_extract_create_idempotent() -> None:
    client = FakeClient()
    client._post_response = {"id": "e-new"}
    server = _register(data_extract_tools, client, read_only=False)
    r1 = await server.tools["create_data_extract"](extract_data={}, request_id="dup-1")
    r2 = await server.tools["create_data_extract"](extract_data={}, request_id="dup-1")
    assert r1 == r2


# ---------------------------------------------------------------------------
# Policy History tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ph_runs_v2_success() -> None:
    client = FakeClient()
    client._get_response = [{"uuid": "r-1", "status": "completed"}]
    server = _register(policy_history_tools, client)
    result = await server.tools["policy_runs_v2"]()
    assert result["data"]["total_runs"] == 1


@pytest.mark.asyncio
async def test_ph_runs_v2_no_org_id() -> None:
    client = FakeClient(org_id=None)
    server = _register(policy_history_tools, client)
    with pytest.raises(ToolError, match="org_id required"):
        await server.tools["policy_runs_v2"]()


@pytest.mark.asyncio
async def test_ph_run_count_success() -> None:
    client = FakeClient()
    client._get_response = {"count": 50}
    server = _register(policy_history_tools, client)
    result = await server.tools["policy_run_count"](days=7)
    assert result["data"]["count"] == 50


@pytest.mark.asyncio
async def test_ph_runs_by_policy_success() -> None:
    client = FakeClient()
    client._get_response = []
    server = _register(policy_history_tools, client)
    result = await server.tools["policy_runs_by_policy"]()
    assert result["data"]["total_policies"] == 0


_FAKE_POLICY_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_FAKE_EXEC_TOKEN = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_ph_history_detail_success() -> None:
    client = FakeClient()
    client._get_response = {"uuid": _FAKE_POLICY_UUID, "name": "Test"}
    server = _register(policy_history_tools, client)
    result = await server.tools["policy_history_detail"](policy_uuid=_FAKE_POLICY_UUID)
    assert result["data"]["uuid"] == _FAKE_POLICY_UUID


@pytest.mark.asyncio
async def test_ph_runs_for_policy_success() -> None:
    client = FakeClient()
    client._get_response = []
    server = _register(policy_history_tools, client)
    result = await server.tools["policy_runs_for_policy"](policy_uuid=_FAKE_POLICY_UUID)
    assert result["data"]["total_runs"] == 0


@pytest.mark.asyncio
async def test_ph_run_detail_v2_success() -> None:
    client = FakeClient()
    client._get_response = []
    server = _register(policy_history_tools, client)
    result = await server.tools["policy_run_detail_v2"](
        policy_uuid=_FAKE_POLICY_UUID,
        exec_token=_FAKE_EXEC_TOKEN,
    )
    assert result["data"]["total_results"] == 0


@pytest.mark.asyncio
async def test_ph_api_error() -> None:
    client = FakeClient()

    async def _err(*a, **kw):
        raise AutomoxAPIError("error", status_code=500)

    client.get = _err
    server = _register(policy_history_tools, client)
    with pytest.raises(ToolError, match="error"):
        await server.tools["policy_runs_v2"]()


# ---------------------------------------------------------------------------
# Audit v2 tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_v2_success() -> None:
    client = FakeClient()
    client._get_response = [{"uid": "ev-1", "activity": "Login"}]
    server = _register(audit_v2_tools, client)
    result = await server.tools["audit_events_ocsf"](date="2026-03-25")
    assert result["data"]["total_events"] == 1


@pytest.mark.asyncio
async def test_audit_v2_no_org_id() -> None:
    client = FakeClient(org_id=None)
    server = _register(audit_v2_tools, client)
    with pytest.raises(ToolError, match="org_id required"):
        await server.tools["audit_events_ocsf"](date="2026-03-25")


# ---------------------------------------------------------------------------
# Device Search tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ds_saved_searches_success() -> None:
    client = FakeClient()
    client._get_response = [{"id": "ss-1", "name": "Test"}]
    server = _register(device_search_tools, client)
    result = await server.tools["list_saved_searches"]()
    assert result["data"]["total_searches"] == 1


@pytest.mark.asyncio
async def test_ds_advanced_search_success() -> None:
    client = FakeClient()
    client._post_response = {"data": [{"id": 1}]}
    server = _register(device_search_tools, client)
    result = await server.tools["advanced_device_search"]()
    assert result["data"]["total_devices"] == 1


@pytest.mark.asyncio
async def test_ds_typeahead_success() -> None:
    client = FakeClient()
    client._post_response = ["val1", "val2"]
    server = _register(device_search_tools, client)
    result = await server.tools["device_search_typeahead"](field="os", prefix="Win")
    assert result["data"]["total_suggestions"] == 2


@pytest.mark.asyncio
async def test_ds_metadata_fields_success() -> None:
    client = FakeClient()
    client._get_response = [{"name": "hostname"}]
    server = _register(device_search_tools, client)
    result = await server.tools["get_device_metadata_fields"]()
    assert result["data"]["total_fields"] == 1


@pytest.mark.asyncio
async def test_ds_assignments_success() -> None:
    client = FakeClient()
    client._get_response = [{"device": "d-1"}]
    server = _register(device_search_tools, client)
    result = await server.tools["get_device_assignments"]()
    assert result["data"]["total_assignments"] == 1


_FAKE_DEVICE_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.mark.asyncio
async def test_ds_device_by_uuid_success() -> None:
    client = FakeClient()
    client._get_response = {"uuid": _FAKE_DEVICE_UUID, "hostname": "host-1"}
    server = _register(device_search_tools, client)
    result = await server.tools["get_device_by_uuid"](device_uuid=_FAKE_DEVICE_UUID)
    assert result["data"]["uuid"] == _FAKE_DEVICE_UUID


@pytest.mark.asyncio
async def test_ds_api_error() -> None:
    client = FakeClient()

    async def _err(*a, **kw):
        raise AutomoxAPIError("timeout", status_code=504)

    client.get = _err
    server = _register(device_search_tools, client)
    with pytest.raises(ToolError, match="timeout"):
        await server.tools["list_saved_searches"]()


# ---------------------------------------------------------------------------
# Vuln Sync tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vs_list_success() -> None:
    client = FakeClient()
    client._get_response = [{"id": 1, "name": "Set 1"}]
    server = _register(vuln_sync_tools, client)
    result = await server.tools["list_remediation_action_sets"]()
    assert result["data"]["total_action_sets"] == 1


@pytest.mark.asyncio
async def test_vs_detail_success() -> None:
    client = FakeClient()
    client._get_response = {"id": 1, "name": "Detail"}
    server = _register(vuln_sync_tools, client)
    result = await server.tools["get_action_set_detail"](action_set_id=1)
    assert result["data"]["id"] == 1


@pytest.mark.asyncio
async def test_vs_actions_success() -> None:
    client = FakeClient()
    client._get_response = [{"id": 101}]
    server = _register(vuln_sync_tools, client)
    result = await server.tools["get_action_set_actions"](action_set_id=1)
    assert result["data"]["total_actions"] == 1


@pytest.mark.asyncio
async def test_vs_issues_success() -> None:
    client = FakeClient()
    client._get_response = [{"cve_id": "CVE-1"}]
    server = _register(vuln_sync_tools, client)
    result = await server.tools["get_action_set_issues"](action_set_id=1)
    assert result["data"]["total_issues"] == 1


@pytest.mark.asyncio
async def test_vs_solutions_success() -> None:
    client = FakeClient()
    client._get_response = [{"title": "Fix"}]
    server = _register(vuln_sync_tools, client)
    result = await server.tools["get_action_set_solutions"](action_set_id=1)
    assert result["data"]["total_solutions"] == 1


@pytest.mark.asyncio
async def test_vs_formats_success() -> None:
    client = FakeClient()
    client._get_response = [{"name": "qualys"}]
    server = _register(vuln_sync_tools, client)
    result = await server.tools["get_upload_formats"]()
    assert result["data"]["total_formats"] == 1


@pytest.mark.asyncio
async def test_vs_upload_success() -> None:
    client = FakeClient()
    client._post_response = {"id": 3, "status": "pending"}
    server = _register(vuln_sync_tools, client, read_only=False)
    result = await server.tools["upload_action_set"](action_set_data={"format": "qualys"})
    assert result["data"]["id"] == 3


@pytest.mark.asyncio
async def test_vs_upload_idempotent() -> None:
    client = FakeClient()
    client._post_response = {"id": 3}
    server = _register(vuln_sync_tools, client, read_only=False)
    r1 = await server.tools["upload_action_set"](action_set_data={}, request_id="dup-1")
    r2 = await server.tools["upload_action_set"](action_set_data={}, request_id="dup-1")
    assert r1 == r2


@pytest.mark.asyncio
async def test_vs_api_error() -> None:
    client = FakeClient()

    async def _err(*a, **kw):
        raise AutomoxAPIError("forbidden", status_code=403)

    client.get = _err
    server = _register(vuln_sync_tools, client)
    with pytest.raises(ToolError, match="forbidden"):
        await server.tools["list_remediation_action_sets"]()


# ---------------------------------------------------------------------------
# Account tools - list_org_api_keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_api_keys_success() -> None:
    client = FakeClient()
    client._get_response = [{"id": 1, "name": "Key 1"}]
    server = _register(account_tools, client, read_only=False)
    result = await server.tools["list_org_api_keys"]()
    assert result["data"]["total_keys"] == 1


@pytest.mark.asyncio
async def test_account_api_keys_no_org_id() -> None:
    client = FakeClient(org_id=None)
    server = _register(account_tools, client, read_only=False)
    with pytest.raises(ToolError, match="org_id required"):
        await server.tools["list_org_api_keys"]()
