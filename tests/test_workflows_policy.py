import copy
from typing import Any, cast
from uuid import UUID

import pytest

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.workflows.policy import (
    _decode_schedule_days_bitmask,
    _normalize_status,
    describe_policy,
    describe_policy_run_result,
    summarize_policies,
    summarize_policy_activity,
    summarize_policy_execution_history,
)
from automox_mcp.workflows.policy_crud import apply_policy_changes


class StubClient:
    """Minimal Automox client stub for testing policy workflows."""

    def __init__(
        self,
        *,
        get_responses: dict[str, list[Any]] | None = None,
        post_responses: dict[str, list[Any]] | None = None,
        put_responses: dict[str, list[Any]] | None = None,
    ) -> None:
        self._get_responses = {key: list(value) for key, value in (get_responses or {}).items()}
        self._post_responses = {key: list(value) for key, value in (post_responses or {}).items()}
        self._put_responses = {key: list(value) for key, value in (put_responses or {}).items()}
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(("GET", path, params, None))
        responses = self._get_responses.get(path)
        if not responses:
            raise AssertionError(f"Unexpected GET request: {path}")
        return copy.deepcopy(responses.pop(0))

    async def post(
        self,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(("POST", path, params, json_data))
        responses = self._post_responses.get(path)
        if responses is None:
            raise AssertionError(f"Unexpected POST request: {path}")
        if not responses:
            raise AssertionError(f"No remaining POST responses for {path}")
        return copy.deepcopy(responses.pop(0))

    async def put(
        self,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(("PUT", path, params, json_data))
        responses = self._put_responses.get(path)
        if responses is None:
            raise AssertionError(f"Unexpected PUT request: {path}")
        if not responses:
            raise AssertionError(f"No remaining PUT responses for {path}")
        return copy.deepcopy(responses.pop(0))


@pytest.mark.asyncio
async def test_apply_policy_changes_preview_create() -> None:
    client = StubClient()
    operations = [
        {
            "action": "create",
            "name": "New Patch Baseline",
            "policy_type": "PATCH",
            "configuration": {
                "patch_rule": "filter",
                "filter_name": "Google Chrome",
                "auto_patch": True,
                "auto_reboot": False,
                "notify_user": False,
                "device_filters": [101, "102"],
            },
            "schedule": {
                "days": ["monday", "wednesday"],
                "time": "3:00",
            },
            "server_groups": [123],
            "notes": "Created via MCP",
        },
    ]

    result = await apply_policy_changes(
        cast(AutomoxClient, client),
        org_id=555,
        operations=operations,
        preview=True,
    )

    assert result["metadata"]["operation_count"] == 1
    op = result["data"]["operations"][0]
    assert op["status"] == "preview"
    assert op["request"]["method"] == "POST"
    assert op["request"]["params"] == {"o": 555}
    payload = op["request"]["body"]
    assert payload["organization_id"] == 555
    assert payload["policy_type_name"] == "patch"
    assert payload["name"] == "New Patch Baseline"
    assert payload["server_groups"] == [123]
    # These are auto-set when schedule_days is provided (Automox requirement)
    assert payload["schedule_weeks_of_month"] == 62  # All 5 weeks
    assert payload["schedule_months"] == 8190  # All 12 months
    assert payload["schedule_days"] == 10  # Monday + Wednesday
    assert payload["schedule_time"] == "03:00"
    assert payload["configuration"]["filters"] == ["*Google Chrome*"]
    assert payload["configuration"]["filter_type"] == "include"
    assert payload["configuration"]["device_filters"] == [
        {"op": "in", "field": "device-id", "value": [101, 102]}
    ]
    assert payload["configuration"]["device_filters_enabled"] is True
    assert ("response" not in op) and ("policy" not in op)
    # Should have warnings about auto-setting schedule weeks/months
    assert "warnings" in op
    assert any("schedule_weeks_of_month" in w for w in op["warnings"])
    assert any("schedule_months" in w for w in op["warnings"])
    # Preview mode should not call POST
    assert all(method != "POST" for method, *_ in client.calls)


@pytest.mark.asyncio
async def test_apply_policy_changes_rejects_boolean_schedule_days() -> None:
    client = StubClient()
    operations = [
        {
            "action": "create",
            "name": "Odd Schedule",
            "policy_type": "patch",
            "configuration": {
                "patch_rule": "filter",
                "filter_name": "Chrome",
                "auto_patch": True,
            },
            "schedule_days": True,
            "schedule_time": "02:00",
            "server_groups": [],
        }
    ]

    with pytest.raises(ValueError, match="schedule_days must be an integer bitmask"):
        await apply_policy_changes(
            cast(AutomoxClient, client),
            org_id=555,
            operations=operations,
            preview=True,
        )


@pytest.mark.asyncio
async def test_apply_policy_changes_rejects_unknown_schedule_day() -> None:
    client = StubClient()
    operations = [
        {
            "action": "create",
            "name": "Friendly Schedule",
            "policy_type": "patch",
            "configuration": {
                "patch_rule": "filter",
                "filter_name": "Chrome",
                "auto_patch": True,
            },
            "schedule": {
                "days": ["funday"],
                "time": "02:00",
            },
            "server_groups": [],
        }
    ]

    with pytest.raises(ValueError, match="Unrecognized day name 'funday'"):
        await apply_policy_changes(
            cast(AutomoxClient, client),
            org_id=555,
            operations=operations,
            preview=True,
        )


@pytest.mark.asyncio
async def test_apply_policy_changes_update_merges_existing() -> None:
    existing_policy: dict[str, Any] = {
        "id": 901,
        "uuid": "11111111-2222-3333-4444-555555555555",
        "name": "Baseline Windows Patch",
        "policy_type_name": "patch",
        "organization_id": 555,
        "configuration": {
            "patch_rule": "all",
            "auto_patch": True,
            "auto_reboot": False,
        },
        "schedule_days": 42,
        "schedule_weeks_of_month": 0,
        "schedule_months": 0,
        "schedule_time": "04:00",
        "use_scheduled_timezone": False,
        "notes": "Original baseline",
        "server_groups": [10, 11],
        "create_time": "2024-01-01T00:00:00Z",
        "status": "active",
    }
    updated_policy: dict[str, Any] = copy.deepcopy(existing_policy)
    existing_config = cast(dict[str, Any], existing_policy["configuration"])
    updated_policy["configuration"] = {
        **existing_config,
        "include_optional": True,
    }

    client = StubClient(
        get_responses={"/policies/901": [existing_policy, updated_policy]},
        put_responses={"/policies/901": [{}]},
    )

    operations = [
        {
            "action": "update",
            "policy_id": 901,
            "merge_existing": True,
            "policy": {
                "configuration": {
                    "include_optional": True,
                },
            },
        }
    ]

    result = await apply_policy_changes(
        cast(AutomoxClient, client),
        org_id=555,
        operations=operations,
        preview=False,
    )

    assert result["metadata"]["operation_count"] == 1
    op = result["data"]["operations"][0]
    assert op["status"] == "updated"
    assert op["policy_id"] == 901
    assert op["previous_policy"]["name"] == "Baseline Windows Patch"
    assert op["policy"]["configuration"]["include_optional"] is True

    method, path, params, body = client.calls[1]  # PUT call is second (after initial GET)
    assert method == "PUT"
    assert path == "/policies/901"
    assert params == {"o": 555}
    assert body is not None
    assert body["organization_id"] == 555
    assert body["id"] == 901
    configuration = cast(dict[str, Any], body.get("configuration"))
    assert configuration["include_optional"] is True
    assert configuration["auto_patch"] is True


@pytest.mark.asyncio
async def test_summarize_policy_activity_uses_supported_params() -> None:
    window_days = 3
    max_runs = 75
    org_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    run_count_payload = {"data": {"policy_runs": 0}}
    runs_payload = {
        "data": [
            {
                "policy_uuid": str(org_uuid),
                "policy_id": 1001,
                "policy_name": "Example Policy",
                "result_status": "success",
                "created_at": "2024-06-01T00:00:00Z",
            }
        ]
    }

    client = StubClient(
        get_responses={
            "/policy-history/policy-run-count": [run_count_payload],
            "/policy-history/policy-runs": [runs_payload],
        }
    )

    result = await summarize_policy_activity(
        cast(AutomoxClient, client),
        org_uuid=org_uuid,
        window_days=window_days,
        top_failures=3,
        max_runs=max_runs,
    )

    assert result["metadata"]["org_uuid"] == str(org_uuid)
    assert len(client.calls) == 2

    count_call = client.calls[0]
    assert count_call[0] == "GET"
    assert count_call[1] == "/policy-history/policy-run-count"
    count_params = count_call[2]
    assert count_params is not None
    assert count_params["days"] == window_days

    runs_call = client.calls[1]
    assert runs_call[1] == "/policy-history/policy-runs"
    run_params = runs_call[2]
    assert run_params is not None
    assert run_params["limit"] == max_runs


@pytest.mark.asyncio
async def test_describe_policy_run_result_summarizes_and_normalizes() -> None:
    org_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    policy_uuid = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    exec_token = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    api_path = f"/policy-history/policies/{policy_uuid}/{exec_token}"
    response_payload = {
        "metadata": {
            "current_page": 0,
            "total_pages": 1,
            "total_count": 2,
            "limit": 25,
        },
        "data": [
            {
                "device_id": 1,
                "device_uuid": "11111111-1111-1111-1111-111111111111",
                "hostname": "alpha",
                "custom_name": "Alpha",
                "display_name": "Alpha",
                "result_status": "SUCCESS",
                "result_reason": "Policy Successfully Ran",
                "run_time": "2024-01-01T00:00:00Z",
                "event_time": "2024-01-01T00:01:00Z",
                "stdout": "ok",
                "stderr": "",
                "exit_code": 0,
                "patches": [],
            },
            {
                "device_id": 2,
                "device_uuid": "22222222-2222-2222-2222-222222222222",
                "hostname": "beta",
                "display_name": "beta",
                "result_status": "FAILED",
                "result_reason": "Error",
                "run_time": "2024-01-01T00:00:30Z",
                "event_time": "2024-01-01T00:01:30Z",
                "stdout": "",
                "stderr": "oops",
                "exit_code": 1,
                "patches": ["KB123"],
            },
        ],
    }

    client = StubClient(get_responses={api_path: [response_payload]})
    result = await describe_policy_run_result(
        cast(AutomoxClient, client),
        org_uuid=org_uuid,
        policy_uuid=policy_uuid,
        exec_token=exec_token,
        page=0,
        limit=25,
    )

    assert result["data"]["result_summary"]["total_devices"] == 2
    assert result["metadata"]["status_breakdown"]["success"] == 1
    assert result["metadata"]["status_breakdown"]["failed"] == 1

    first_device = result["data"]["devices"][0]
    assert first_device["result_status"] == "success"
    assert first_device["stdout"] == "ok"

    method, path, params, _ = client.calls[0]
    assert method == "GET"
    assert path == api_path
    assert params is not None
    assert params["org"] == str(org_uuid)
    assert params["limit"] == 25
    assert params["page"] == 0


# ---------------------------------------------------------------------------
# _normalize_status
# ---------------------------------------------------------------------------


def test_normalize_status_cancelled() -> None:
    assert _normalize_status("cancelling") == "cancelled"
    assert _normalize_status("cancelled") == "cancelled"


def test_normalize_status_empty() -> None:
    assert _normalize_status(None) == "unknown"
    assert _normalize_status("") == "unknown"


# ---------------------------------------------------------------------------
# _decode_schedule_days_bitmask
# ---------------------------------------------------------------------------


def test_decode_schedule_days_bitmask_unscheduled() -> None:
    result = _decode_schedule_days_bitmask(0)
    assert "Unscheduled" in result["interpretation"]


def test_decode_schedule_days_bitmask_weekdays() -> None:
    result = _decode_schedule_days_bitmask(62)
    assert "Weekdays" in result["interpretation"]
    assert result["bitmask_value"] == 62


def test_decode_schedule_days_bitmask_weekend() -> None:
    result = _decode_schedule_days_bitmask(192)
    assert "Weekend" in result["interpretation"]


def test_decode_schedule_days_bitmask_every_day() -> None:
    result = _decode_schedule_days_bitmask(254)
    assert "Every day" in result["interpretation"]


def test_decode_schedule_days_bitmask_custom() -> None:
    # Monday only = bitmask 2
    result = _decode_schedule_days_bitmask(2)
    assert "Monday" in result["selected_days"]
    assert "1 days" in result["interpretation"]


# ---------------------------------------------------------------------------
# summarize_policy_activity — additional paths
# ---------------------------------------------------------------------------


class FlexibleStubClient:
    """StubClient that matches paths by prefix for dynamic query-string paths."""

    def __init__(
        self,
        *,
        get_responses: dict[str, list[Any]] | None = None,
        raise_on_path_prefix: str | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._get_responses = {key: list(value) for key, value in (get_responses or {}).items()}
        self._raise_on_prefix = raise_on_path_prefix
        self._raise_exc = raise_exc
        self.calls: list[tuple[str, str, Any, Any]] = []

    async def get(self, path: str, *, params=None, headers=None) -> Any:
        self.calls.append(("GET", path, params, None))
        if self._raise_on_prefix and path.startswith(self._raise_on_prefix):
            raise self._raise_exc or AutomoxAPIError("error", status_code=500, payload={})
        # Try exact match first, then prefix match
        for key, responses in self._get_responses.items():
            if path == key or path.startswith(key):
                if responses:
                    return copy.deepcopy(responses.pop(0))
        return []


@pytest.mark.asyncio
async def test_summarize_policy_activity_run_count_api_error() -> None:
    """AutomoxAPIError on run-count is swallowed; runs still processed."""
    org_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    runs_payload = [
        {"policy_uuid": "p1", "policy_name": "P1", "failed": 1, "success": 0, "device_count": 2},
        {"policy_uuid": "p2", "policy_name": "P2", "failed": 0, "success": 3, "device_count": 3},
    ]

    client = FlexibleStubClient(
        get_responses={
            "/policy-history/policy-run-count": [],  # empty → raises AssertionError below
            "/policy-history/policy-runs": [runs_payload],
        },
        raise_on_path_prefix="/policy-history/policy-run-count",
    )

    result = await summarize_policy_activity(
        cast(AutomoxClient, client),
        org_uuid=org_uuid,
    )

    # failed > 0 increments status_counter["failed"],
    # success > 0 increments status_counter["success"]
    assert result["data"]["status_breakdown"].get("failed", 0) >= 1
    assert result["data"]["status_breakdown"].get("success", 0) >= 1
    # top_failing_policies should include p1
    top = result["data"]["top_failing_policies"]
    assert any(p.get("policy_uuid") == "p1" or p.get("policy_name") == "P1" for p in top)


@pytest.mark.asyncio
async def test_summarize_policy_activity_runs_as_list() -> None:
    """When /policy-history/policy-runs returns a plain list (not wrapped in data)."""
    org_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    runs_list = [
        {"policy_uuid": "p3", "policy_name": "P3", "failed": 0, "success": 0, "device_count": 0},
    ]

    client = FlexibleStubClient(
        get_responses={
            "/policy-history/policy-run-count": [{"policy_runs": 10}],
            "/policy-history/policy-runs": [runs_list],
        },
    )

    result = await summarize_policy_activity(
        cast(AutomoxClient, client),
        org_uuid=org_uuid,
    )

    # The run has no failed/success → classified as unknown
    assert result["data"]["status_breakdown"].get("unknown", 0) >= 1
    assert result["data"]["total_policy_runs"] == 10


# ---------------------------------------------------------------------------
# summarize_policy_execution_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_policy_execution_history_list_response() -> None:
    """Test when API returns a list of runs directly."""
    org_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    policy_uuid = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    runs = [
        {
            "execution_token": "tok-1",
            "run_time": "2024-06-01T00:00:00Z",
            "failed": 2,
            "success": 0,
            "device_count": 2,
            "policy_name": "Test Policy",
        },
        {
            "execution_token": "tok-2",
            "run_time": "2024-06-02T00:00:00Z",
            "failed": 0,
            "success": 5,
            "device_count": 5,
        },
    ]

    client = FlexibleStubClient(
        get_responses={
            "/policy-history/policy-runs": [runs],
        },
    )

    result = await summarize_policy_execution_history(
        cast(AutomoxClient, client),
        org_uuid=org_uuid,
        policy_uuid=policy_uuid,
        limit=10,
    )

    assert result["data"]["status_breakdown"]["failed"] == 1
    assert result["data"]["status_breakdown"]["success"] == 1
    assert len(result["data"]["recent_executions"]) == 2
    assert result["data"]["policy_uuid"] == str(policy_uuid)
    # policy_name is only extracted when payload is a Mapping — for a plain list it's None
    assert result["data"]["policy_name"] is None


@pytest.mark.asyncio
async def test_summarize_policy_execution_history_mapping_response() -> None:
    """Test when API wraps runs in a data key."""
    org_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    policy_uuid = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    payload = {
        "data": [
            {
                "execution_token": "tok-1",
                "run_time": "2024-06-01T00:00:00Z",
                "failed": 0,
                "success": 0,
                "device_count": 0,
                "policy_name": "Wrapped Policy",
            },
        ]
    }

    client = FlexibleStubClient(
        get_responses={
            "/policy-history/policy-runs": [payload],
        },
    )

    result = await summarize_policy_execution_history(
        cast(AutomoxClient, client),
        org_uuid=org_uuid,
        policy_uuid=policy_uuid,
    )

    execs = result["data"]["recent_executions"]
    assert len(execs) == 1
    # status is None when both failed and success are 0
    assert execs[0]["status"] is None


# ---------------------------------------------------------------------------
# summarize_policies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_policies_raises_when_no_org_id() -> None:
    client = FlexibleStubClient()
    client.org_id = None  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="org_id required"):
        await summarize_policies(cast(AutomoxClient, client))


@pytest.mark.asyncio
async def test_summarize_policies_filters_inactive_by_default() -> None:
    """Policies with status 'inactive' are filtered out unless include_inactive=True."""
    active_policy = {
        "id": 1,
        "name": "Active Policy",
        "policy_type_name": "patch",
        "status": "active",
    }
    inactive_policy = {
        "id": 2,
        "name": "Disabled Policy",
        "policy_type_name": "patch",
        "status": "inactive",
    }

    # Stub provides two calls — one for /policies (page 0), one for /policystats
    # The loop breaks after page 0 since the preview cap (limit=20) is not yet reached
    # but page_results is empty on the second call.
    stub = StubClient(
        get_responses={
            "/policies": [[active_policy, inactive_policy], []],
            "/policystats": [[]],
        }
    )
    stub.org_id = 42  # type: ignore[attr-defined]

    result = await summarize_policies(
        cast(AutomoxClient, stub),
        org_id=42,
        limit=20,
        include_inactive=False,
    )

    names = [p["name"] for p in result["data"]["policies"]]
    assert "Active Policy" in names
    assert "Disabled Policy" not in names


@pytest.mark.asyncio
async def test_summarize_policies_include_inactive() -> None:
    """When include_inactive=True, inactive policies are included."""
    inactive_policy = {
        "id": 2,
        "name": "Old Policy",
        "policy_type_name": "worklet",
        "status": "inactive",
    }

    stub = StubClient(
        get_responses={
            "/policies": [[inactive_policy], []],
            "/policystats": [[]],
        }
    )

    result = await summarize_policies(
        cast(AutomoxClient, stub),
        org_id=42,
        limit=20,
        include_inactive=True,
    )

    assert len(result["data"]["policies"]) == 1


@pytest.mark.asyncio
async def test_summarize_policies_is_active_from_status_raw() -> None:
    """When active/enabled/is_active is None, is_active is derived from status_raw."""
    policy_no_flag = {
        "id": 3,
        "name": "Flag-less Active",
        "policy_type_name": "patch",
        # No active/enabled/is_active key; status is 'enabled' → treated as active
        "status": "enabled",
    }

    stub = StubClient(
        get_responses={
            "/policies": [[policy_no_flag], []],
            "/policystats": [[]],
        }
    )

    result = await summarize_policies(
        cast(AutomoxClient, stub),
        org_id=42,
        limit=20,
        include_inactive=False,
    )

    assert result["data"]["policies"][0]["name"] == "Flag-less Active"


@pytest.mark.asyncio
async def test_summarize_policies_custom_type_normalized_to_worklet() -> None:
    policy = {
        "id": 4,
        "name": "Custom Script",
        "policy_type_name": "custom",
        "status": "active",
    }

    stub = StubClient(
        get_responses={
            "/policies": [[policy], []],
            "/policystats": [[]],
        }
    )

    result = await summarize_policies(cast(AutomoxClient, stub), org_id=42, limit=20)

    assert result["data"]["policy_type_breakdown"].get("worklet", 0) == 1


# ---------------------------------------------------------------------------
# describe_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_policy_raises_when_no_org_id() -> None:
    stub = StubClient()
    stub.org_id = None  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="org_id required"):
        await describe_policy(cast(AutomoxClient, stub), policy_id=1)


@pytest.mark.asyncio
async def test_describe_policy_basic() -> None:
    """describe_policy returns policy data and metadata."""
    policy = {
        "id": 10,
        "name": "Patch Everything",
        "policy_type_name": "patch",
        "org_uuid": None,
        "schedule_days": 62,
        "schedule_time": "02:00",
    }

    # Needs /policies/10 and optionally /orgs if org_uuid is not available
    stub = StubClient(
        get_responses={
            "/policies/10": [policy],
            "/orgs": [[{"id": 42, "org_uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}]],
            "/policy-history/policy-runs?"
            "policy_uuid:equals=None"
            "&org=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            "&limit=5": [{"data": []}],
        }
    )

    result = await describe_policy(
        cast(AutomoxClient, stub),
        org_id=42,
        policy_id=10,
        include_recent_runs=0,
    )

    assert result["data"]["policy"]["id"] == 10
    assert result["metadata"]["policy_id"] == 10
    assert "schedule_interpretation" in result["data"]


@pytest.mark.asyncio
async def test_describe_policy_exception_wrapped() -> None:
    """AutomoxAPIError from the API call is wrapped as ValueError."""

    class _ErrorClient(StubClient):
        async def get(self, path, **kwargs):
            raise AutomoxAPIError("not found", status_code=404)

    stub = _ErrorClient()

    with pytest.raises(ValueError, match="Failed to retrieve policy 999"):
        await describe_policy(
            cast(AutomoxClient, stub),
            org_id=42,
            policy_id=999,
        )
