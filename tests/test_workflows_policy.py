import copy
import pathlib
import sys
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from automox_mcp.client import AutomoxClient  # noqa: E402
from automox_mcp.workflows.policy import (  # noqa: E402
    apply_policy_changes,
    describe_policy_run_result,
    summarize_policy_activity,
)


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
        self.calls: list[
            tuple[str, str, dict[str, Any] | None, dict[str, Any] | None, str | None]
        ] = []

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        api: str | None = None,
    ) -> Any:
        self.calls.append(("GET", path, params, None, api))
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
        api: str | None = None,
    ) -> Any:
        self.calls.append(("POST", path, params, json_data, api))
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
        api: str | None = None,
    ) -> Any:
        self.calls.append(("PUT", path, params, json_data, api))
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

    method, path, params, body, api = client.calls[1]  # PUT call is second (after initial GET)
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
    assert count_call[4] == "policyreport"

    runs_call = client.calls[1]
    assert runs_call[1] == "/policy-history/policy-runs"
    run_params = runs_call[2]
    assert run_params is not None
    assert run_params["limit"] == max_runs
    assert run_params["sort"] == "run_time:desc"
    assert "start_time" in run_params
    parsed = datetime.fromisoformat(run_params["start_time"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.microsecond == 0


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

    method, path, params, _, api = client.calls[0]
    assert method == "GET"
    assert path == api_path
    assert params is not None
    assert params["org"] == str(org_uuid)
    assert params["limit"] == 25
    assert params["page"] == 0
