"""Additional edge-case tests for Phase 3 modules to increase coverage."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.audit_v2 import (
    _summarize_ocsf_event,
    audit_events_ocsf,
)
from automox_mcp.workflows.data_extracts import (
    create_data_extract,
    get_data_extract,
)
from automox_mcp.workflows.device_search import (
    advanced_device_search,
    device_search_typeahead,
    get_device_metadata_fields,
)
from automox_mcp.workflows.policy_history import (
    _extract_list,
    _summarize_policy,
    _summarize_run,
    get_policy_history_detail,
    get_policy_run_detail_v2,
    list_policy_runs_v2,
    policy_run_count,
    policy_runs_by_policy,
)
from automox_mcp.workflows.vuln_sync import (
    _summarize_action_set,
    get_action_set_detail,
    upload_action_set,
)

_ORG_UUID = "11111111-2222-3333-4444-555555555555"
_ACCT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


# ---------------------------------------------------------------------------
# _extract_list helper edge cases
# ---------------------------------------------------------------------------


def test_extract_list_with_non_sequence() -> None:
    assert _extract_list("unexpected") == []


def test_extract_list_with_mapping_no_data() -> None:
    result = _extract_list({"key": "value"})
    assert len(result) == 1  # returns [response] for single mapping


def test_extract_list_with_mapping_data_key() -> None:
    result = _extract_list({"data": [{"id": 1}, {"id": 2}]})
    assert len(result) == 2


def test_extract_list_filters_non_mappings() -> None:
    result = _extract_list([{"id": 1}, "bad", None, {"id": 2}])
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _summarize helpers
# ---------------------------------------------------------------------------


def test_summarize_run_skips_none_fields() -> None:
    run = {"policy_uuid": "abc", "extra_field": "ignored"}
    result = _summarize_run(run)
    assert result["policy_uuid"] == "abc"
    assert "extra_field" not in result


def test_summarize_policy_skips_none_fields() -> None:
    policy = {"uuid": "abc", "name": "Test"}
    result = _summarize_policy(policy)
    assert result == {"uuid": "abc", "name": "Test"}


def test_summarize_action_set_extracts_key_fields() -> None:
    item = {"id": 1, "name": "Test", "status": "active", "unknown": "x"}
    result = _summarize_action_set(item)
    assert result == {"id": 1, "name": "Test", "status": "active"}


# ---------------------------------------------------------------------------
# Policy History edge cases
# ---------------------------------------------------------------------------


def _make_ph_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


@pytest.mark.asyncio
async def test_policy_runs_v2_all_filters() -> None:
    """Test all filter parameters are passed."""
    client = _make_ph_client(get_responses={"/policy-history/policy-runs": [[]]})
    await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        start_time="2026-01-01",
        end_time="2026-03-01",
        policy_name="Test",
        policy_uuid="pol-001",
        policy_type="patch",
        result_status="failure",
        sort="desc",
        page=0,
        limit=25,
    )
    params = client.calls[0][2]
    assert params["start_time"] == "2026-01-01"
    assert params["end_time"] == "2026-03-01"
    assert params["policy_name"] == "Test"
    assert params["policy_uuid"] == "pol-001"


@pytest.mark.asyncio
async def test_run_count_non_mapping_response() -> None:
    """Test run_count handles non-mapping response."""
    client = _make_ph_client(get_responses={"/policy-history/policy-run-count": [42]})
    result = await policy_run_count(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["count"] == 42


@pytest.mark.asyncio
async def test_runs_by_policy_empty() -> None:
    client = _make_ph_client(get_responses={"/policy-history/policy-runs/grouped-by/policy": [[]]})
    result = await policy_runs_by_policy(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_policies"] == 0


@pytest.mark.asyncio
async def test_history_detail_non_mapping() -> None:
    client = _make_ph_client(get_responses={"/policy-history/policies/pol-x": ["bad"]})
    result = await get_policy_history_detail(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-x",
    )
    assert result["data"] == {}


@pytest.mark.asyncio
async def test_run_detail_v2_all_filters() -> None:
    client = _make_ph_client(get_responses={"/policy-history/policies/pol-001/exec-001": [[]]})
    await get_policy_run_detail_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
        exec_token="exec-001",
        sort="asc",
        result_status="success",
        device_name="host-1",
        page=0,
        limit=10,
    )
    params = client.calls[0][2]
    assert params["sort"] == "asc"
    assert params["device_name"] == "host-1"
    assert "org" not in params  # org comes from JWT, not query params


# ---------------------------------------------------------------------------
# Vuln Sync edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_action_set_detail_non_mapping() -> None:
    client = StubClient(get_responses={"/orgs/42/remediations/action-sets/99": ["bad"]})
    result = await get_action_set_detail(cast(AutomoxClient, client), org_id=42, action_set_id=99)
    assert result["data"] == {}


@pytest.mark.asyncio
async def test_upload_action_set_non_mapping_response() -> None:
    client = StubClient(post_responses={"/orgs/42/remediations/action-sets/upload": ["bad"]})
    result = await upload_action_set(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_data={"format": "qualys"},
    )
    assert result["data"]["status"] == "pending"


# ---------------------------------------------------------------------------
# Device Search edge cases
# ---------------------------------------------------------------------------


def _make_ds_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


@pytest.mark.asyncio
async def test_advanced_search_no_query() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search"
    client = _make_ds_client(post_responses={path: [{"data": []}]})
    result = await advanced_device_search(cast(AutomoxClient, client))
    assert result["data"]["total_devices"] == 0


@pytest.mark.asyncio
async def test_advanced_search_list_response() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search"
    client = _make_ds_client(post_responses={path: [[{"id": 1}]]})
    result = await advanced_device_search(cast(AutomoxClient, client))
    assert result["data"]["total_devices"] == 1


@pytest.mark.asyncio
async def test_typeahead_empty() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/search/typeahead"
    client = _make_ds_client(post_responses={path: [{}]})
    result = await device_search_typeahead(
        cast(AutomoxClient, client),
        field="os",
        prefix="Win",
    )
    assert result["data"]["total_suggestions"] == 0


@pytest.mark.asyncio
async def test_metadata_fields_empty() -> None:
    path = "/server-groups-api/device/metadata/device-fields"
    client = _make_ds_client(get_responses={path: [[]]})
    result = await get_device_metadata_fields(cast(AutomoxClient, client))
    assert result["data"]["total_fields"] == 0


# ---------------------------------------------------------------------------
# Audit v2 edge cases
# ---------------------------------------------------------------------------


def test_summarize_ocsf_event_minimal() -> None:
    event = {"uid": "123", "activity": "Login"}
    result = _summarize_ocsf_event(event)
    assert result["uid"] == "123"
    assert result["activity"] == "Login"
    assert "actor" not in result


def test_summarize_ocsf_event_with_device() -> None:
    event = {
        "uid": "456",
        "device": {"uid": "dev-1", "name": "host-1", "type": "server", "extra": "ignored"},
    }
    result = _summarize_ocsf_event(event)
    assert result["device"]["uid"] == "dev-1"
    assert "extra" not in result["device"]


@pytest.mark.asyncio
async def test_audit_v2_no_next_cursor_from_events() -> None:
    """Test cursor extraction from last event metadata."""
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    events = [
        {"uid": "evt-1", "category_name": "auth", "metadata": {"uid": "cursor-123"}},
    ]
    client = StubClient(get_responses={path: [events]})
    client.org_uuid = _ORG_UUID
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )
    assert result["metadata"]["next_cursor"] == "cursor-123"


@pytest.mark.asyncio
async def test_audit_v2_non_sequence_response() -> None:
    """Test handling of unexpected response type."""
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = StubClient(get_responses={path: ["unexpected"]})
    client.org_uuid = _ORG_UUID
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )
    assert result["data"]["total_events"] == 0


# ---------------------------------------------------------------------------
# Data Extracts edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_extract_get_passes_org() -> None:
    client = StubClient(get_responses={"/data-extracts/ext-1": [{"id": "ext-1", "status": "done"}]})
    await get_data_extract(cast(AutomoxClient, client), org_id=99, extract_id="ext-1")
    params = client.calls[0][2]
    assert params["o"] == 99


@pytest.mark.asyncio
async def test_create_data_extract_passes_body() -> None:
    response = {"id": "ext-new"}
    client = StubClient(post_responses={"/data-extracts": [response]})
    await create_data_extract(
        cast(AutomoxClient, client),
        org_id=42,
        extract_data={"type": "patches", "filters": {"severity": "critical"}},
    )
    _, _, json_data = client.calls[0]
    assert json_data["type"] == "patches"
