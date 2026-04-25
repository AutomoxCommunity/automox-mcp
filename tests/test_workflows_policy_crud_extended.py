"""Extended tests for policy_crud.py — targeting uncovered branches."""

from __future__ import annotations

import copy
from typing import Any, cast

import pytest
from fastmcp.exceptions import ToolError

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy_crud import (
    _coerce_policy_payload_defaults,
    _deep_merge_dicts,
    _normalize_filters,
    _normalize_policy_type,
    _normalize_schedule_days_input,
    _normalize_schedule_time,
    apply_policy_changes,
    execute_policy,
    normalize_policy_operations_input,
    resolve_patch_approval,
)

# ---------------------------------------------------------------------------
# Stub client matching the prescribed pattern (prefix-based dispatch)
# ---------------------------------------------------------------------------


class StubClient:
    def __init__(
        self,
        *,
        get_responses: dict[str, list[Any]] | None = None,
        post_responses: dict[str, list[Any]] | None = None,
        put_responses: dict[str, list[Any]] | None = None,
        delete_responses: dict[str, list[Any]] | None = None,
        org_id: int = 42,
        org_uuid: str | None = None,
        account_uuid: str = "test-acct",
    ):
        self.org_id = org_id
        self.org_uuid = org_uuid
        self.account_uuid = account_uuid
        self._get = {k: list(v) for k, v in (get_responses or {}).items()}
        self._post = {k: list(v) for k, v in (post_responses or {}).items()}
        self._put = {k: list(v) for k, v in (put_responses or {}).items()}
        self._delete = {k: list(v) for k, v in (delete_responses or {}).items()}
        self.calls: list[tuple[str, str, Any, Any]] = []

    async def get(self, path: str, *, params: Any = None, headers: Any = None) -> Any:
        self.calls.append(("GET", path, params, None))
        for prefix, responses in self._get.items():
            if path.startswith(prefix) and responses:
                return copy.deepcopy(responses.pop(0))
        return {}

    async def post(
        self, path: str, *, json_data: Any = None, params: Any = None, headers: Any = None
    ) -> Any:
        self.calls.append(("POST", path, params, json_data))
        for prefix, responses in self._post.items():
            if path.startswith(prefix) and responses:
                return copy.deepcopy(responses.pop(0))
        return {}

    async def put(
        self, path: str, *, json_data: Any = None, params: Any = None, headers: Any = None
    ) -> Any:
        self.calls.append(("PUT", path, params, json_data))
        for prefix, responses in self._put.items():
            if path.startswith(prefix) and responses:
                return copy.deepcopy(responses.pop(0))
        return {}

    async def delete(self, path: str, *, params: Any = None, headers: Any = None) -> Any:
        self.calls.append(("DELETE", path, params, None))
        for prefix, responses in self._delete.items():
            if path.startswith(prefix) and responses:
                return copy.deepcopy(responses.pop(0))
        return {}


# ===========================================================================
# normalize_policy_operations_input
# ===========================================================================


def test_normalize_raises_on_non_mapping_item() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        normalize_policy_operations_input(["not-a-dict"])


def test_normalize_raises_tool_error_when_operation_used_instead_of_action() -> None:
    """Using 'operation' instead of 'action' raises ToolError with helpful message."""
    ops = [{"operation": "create", "policy": {"name": "X", "policy_type_name": "patch"}}]
    with pytest.raises(ToolError, match="uses 'operation' field but should use 'action'"):
        normalize_policy_operations_input(ops)


def test_normalize_raises_tool_error_when_action_missing() -> None:
    """Missing 'action' field raises ToolError with guidance."""
    ops = [{"policy": {"name": "X", "policy_type_name": "patch", "configuration": {}}}]
    with pytest.raises(ToolError, match="missing required 'action' field"):
        normalize_policy_operations_input(ops)


def test_normalize_lifts_non_core_keys_into_policy() -> None:
    """When 'policy' key is absent, non-core keys are promoted into a policy dict."""
    ops = [
        {
            "action": "create",
            "name": "Promoted Policy",
            "policy_type_name": "patch",
            "configuration": {"patch_rule": "all"},
            "server_groups": [1],
        }
    ]
    result = normalize_policy_operations_input(ops)
    assert len(result) == 1
    policy = result[0]["policy"]
    assert policy["name"] == "Promoted Policy"
    assert policy["policy_type_name"] == "patch"
    # core key 'action' must not be inside the policy sub-dict
    assert "action" not in policy


def test_normalize_policy_type_field_renamed() -> None:
    """'policy_type' is renamed to 'policy_type_name' inside the policy block."""
    ops = [
        {
            "action": "create",
            "policy": {
                "name": "My Policy",
                "policy_type": "patch",
                "configuration": {"patch_rule": "all"},
            },
        }
    ]
    result = normalize_policy_operations_input(ops)
    policy = result[0]["policy"]
    assert "policy_type_name" in policy
    assert "policy_type" not in policy


def test_normalize_camelCase_policy_type_renamed() -> None:
    """'policyType' (camelCase) is also renamed to 'policy_type_name'."""
    ops = [
        {
            "action": "create",
            "policy": {
                "name": "My Policy",
                "policyType": "patch",
                "configuration": {"patch_rule": "all"},
            },
        }
    ]
    result = normalize_policy_operations_input(ops)
    policy = result[0]["policy"]
    assert "policy_type_name" in policy
    assert "policyType" not in policy


def test_normalize_software_name_converted_to_filters() -> None:
    """'software_name' in configuration is converted to a wildcard filter."""
    ops = [
        {
            "action": "create",
            "policy": {
                "name": "Chrome Policy",
                "policy_type_name": "patch",
                "configuration": {"patch_rule": "filter", "software_name": "Google Chrome"},
            },
        }
    ]
    result = normalize_policy_operations_input(ops)
    config = result[0]["policy"]["configuration"]
    assert "filters" in config
    assert config["filters"] == ["*Google Chrome*"]
    assert "software_name" not in config


def test_normalize_filter_type_stripped_from_configuration() -> None:
    """'filter_type' is removed from configuration during normalization."""
    ops = [
        {
            "action": "create",
            "policy": {
                "name": "P",
                "policy_type_name": "patch",
                "configuration": {
                    "patch_rule": "filter",
                    "filters": ["*Chrome*"],
                    "filter_type": "include",
                },
            },
        }
    ]
    result = normalize_policy_operations_input(ops)
    config = result[0]["policy"]["configuration"]
    assert "filter_type" not in config


def test_normalize_device_filters_dict_format_removed() -> None:
    """device_filters in {device_id: N} format are stripped and moved to notes."""
    ops = [
        {
            "action": "create",
            "policy": {
                "name": "P",
                "policy_type_name": "patch",
                "configuration": {"patch_rule": "all"},
                "device_filters": [{"device_id": 101}, {"device_id": 202}],
            },
        }
    ]
    result = normalize_policy_operations_input(ops)
    policy = result[0]["policy"]
    assert "device_filters" not in policy
    assert "101" in policy.get("notes", "")
    assert "202" in policy.get("notes", "")


def test_normalize_missing_configuration_for_patch_raises_tool_error() -> None:
    """Patch policy without 'configuration' raises ToolError."""
    ops = [
        {
            "action": "create",
            "policy": {
                "name": "P",
                "policy_type_name": "patch",
                # No configuration key
            },
        }
    ]
    with pytest.raises(ToolError, match="require a 'configuration' block"):
        normalize_policy_operations_input(ops)


def test_normalize_empty_sequence_returns_empty() -> None:
    result = normalize_policy_operations_input([])
    assert result == []


# ===========================================================================
# _normalize_policy_type
# ===========================================================================


def test_normalize_policy_type_patch() -> None:
    assert _normalize_policy_type("patch") == "patch"
    assert _normalize_policy_type("PATCH") == "patch"
    assert _normalize_policy_type("  Patch  ") == "patch"


def test_normalize_policy_type_custom() -> None:
    assert _normalize_policy_type("custom") == "custom"


def test_normalize_policy_type_required_software() -> None:
    assert _normalize_policy_type("required_software") == "required_software"


def test_normalize_policy_type_none_raises() -> None:
    with pytest.raises(ValueError, match="policy_type_name is required"):
        _normalize_policy_type(None)


def test_normalize_policy_type_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported policy_type_name"):
        _normalize_policy_type("worklet")


# ===========================================================================
# _normalize_filters
# ===========================================================================


def test_normalize_filters_adds_wildcards() -> None:
    result = _normalize_filters(["Google Chrome", "Firefox"])
    assert result == ["*Google Chrome*", "*Firefox*"]


def test_normalize_filters_keeps_existing_wildcards() -> None:
    result = _normalize_filters(["*Chrome*", "Firefox*"])
    assert result == ["*Chrome*", "Firefox*"]


def test_normalize_filters_skips_empty_strings() -> None:
    result = _normalize_filters(["", "  ", "Chrome"])
    assert result == ["*Chrome*"]


def test_normalize_filters_leading_wildcard_only() -> None:
    result = _normalize_filters(["*Patch"])
    assert result == ["*Patch"]


# ===========================================================================
# _normalize_schedule_time
# ===========================================================================


def test_normalize_schedule_time_none_returns_none() -> None:
    assert _normalize_schedule_time(None) is None


def test_normalize_schedule_time_empty_string_returns_none() -> None:
    assert _normalize_schedule_time("") is None


def test_normalize_schedule_time_hh_mm() -> None:
    assert _normalize_schedule_time("02:00") == "02:00"
    assert _normalize_schedule_time("18:30") == "18:30"


def test_normalize_schedule_time_without_minutes() -> None:
    assert _normalize_schedule_time("3") == "03:00"


def test_normalize_schedule_time_invalid_format_raises() -> None:
    # "abc" does not match the HH[:MM] pattern at all
    with pytest.raises(ValueError, match="HH:MM"):
        _normalize_schedule_time("abc")


def test_normalize_schedule_time_out_of_range_raises() -> None:
    # Hours 25 fail in the regex match but 24:00 passes regex and hits range check
    with pytest.raises(ValueError):
        _normalize_schedule_time("24:00")


def test_normalize_schedule_time_bad_minutes_raises() -> None:
    with pytest.raises(ValueError):
        _normalize_schedule_time("12:60")


# ===========================================================================
# _normalize_schedule_days_input
# ===========================================================================


def test_normalize_schedule_days_none_returns_none() -> None:
    assert _normalize_schedule_days_input(None) is None


def test_normalize_schedule_days_empty_list_returns_none() -> None:
    assert _normalize_schedule_days_input([]) is None


def test_normalize_schedule_days_monday() -> None:
    result = _normalize_schedule_days_input(["monday"])
    assert result == 2  # Monday bitmask


def test_normalize_schedule_days_aliases_weekday() -> None:
    result = _normalize_schedule_days_input(["weekday"])
    # weekday = Mon+Tue+Wed+Thu+Fri = 2+4+8+16+32 = 62
    assert result == 62


def test_normalize_schedule_days_aliases_weekend() -> None:
    result = _normalize_schedule_days_input(["weekend"])
    # weekend = Sat+Sun = 64+128 = 192
    assert result == 192


def test_normalize_schedule_days_abbreviations() -> None:
    result = _normalize_schedule_days_input(["mon", "wed", "fri"])
    assert result == 2 | 8 | 32  # 42


def test_normalize_schedule_days_numeric_index() -> None:
    # 0 = Sunday, 1 = Monday
    result = _normalize_schedule_days_input([1])
    assert result == 2  # Monday bitmask


def test_normalize_schedule_days_numeric_string() -> None:
    result = _normalize_schedule_days_input(["1"])
    assert result == 2


def test_normalize_schedule_days_mapping_raises() -> None:
    with pytest.raises(ValueError, match="not nested objects"):
        _normalize_schedule_days_input([{"day": "monday"}])


def test_normalize_schedule_days_unrecognized_name_raises() -> None:
    with pytest.raises(ValueError, match="Unrecognized day name"):
        _normalize_schedule_days_input(["funday"])


def test_normalize_schedule_days_all_alias() -> None:
    result = _normalize_schedule_days_input(["all"])
    # all 7 days = 2+4+8+16+32+64+128 = 254
    assert result == 254


# ===========================================================================
# _coerce_policy_payload_defaults
# ===========================================================================


def test_coerce_defaults_expands_schedule_alias() -> None:
    payload: dict[str, Any] = {
        "policy_type_name": "patch",
        "name": "P",
        "schedule": {"days": ["monday"], "time": "02:00"},
        "configuration": {"patch_rule": "all"},
    }
    warnings = _coerce_policy_payload_defaults(payload)
    assert "schedule" not in payload
    assert payload["schedule_days"] == 2
    assert payload["schedule_time"] == "02:00"
    # schedule_weeks_of_month and schedule_months should be auto-set
    assert payload["schedule_weeks_of_month"] == 62
    assert payload["schedule_months"] == 8190
    assert any("schedule_weeks_of_month" in w for w in warnings)
    assert any("schedule_months" in w for w in warnings)


def test_coerce_defaults_patch_policy_defaults() -> None:
    """patch_rule defaults to 'all' when no filter fields present."""
    payload: dict[str, Any] = {
        "policy_type_name": "patch",
        "name": "P",
        "configuration": {},
    }
    _coerce_policy_payload_defaults(payload)
    assert payload["configuration"]["patch_rule"] == "all"


def test_coerce_defaults_patch_filter_rule_auto_detected() -> None:
    """patch_rule is set to 'filter' when filters are present."""
    payload: dict[str, Any] = {
        "policy_type_name": "patch",
        "name": "P",
        "configuration": {"filters": ["*Chrome*"]},
    }
    warnings = _coerce_policy_payload_defaults(payload)
    assert payload["configuration"]["patch_rule"] == "filter"
    assert any("Auto-set patch_rule" in w for w in warnings)


def test_coerce_defaults_schedule_frequency_warning() -> None:
    """Unknown 'frequency' key inside schedule block produces a warning."""
    payload: dict[str, Any] = {
        "policy_type_name": "patch",
        "name": "P",
        "schedule": {"days": ["monday"], "time": "02:00", "frequency": "weekly"},
        "configuration": {"patch_rule": "all"},
    }
    warnings = _coerce_policy_payload_defaults(payload)
    assert any("frequency" in w for w in warnings)


def test_coerce_defaults_schedule_unknown_keys_warning() -> None:
    """Unrecognized keys inside the schedule block generate a warning."""
    payload: dict[str, Any] = {
        "policy_type_name": "patch",
        "name": "P",
        "schedule": {"days": ["monday"], "time": "02:00", "unknown_key": "value"},
        "configuration": {"patch_rule": "all"},
    }
    warnings = _coerce_policy_payload_defaults(payload)
    assert any("unknown_key" in w for w in warnings)


def test_coerce_defaults_sets_sensible_server_groups() -> None:
    payload: dict[str, Any] = {
        "policy_type_name": "patch",
        "name": "P",
        "configuration": {"patch_rule": "all"},
    }
    _coerce_policy_payload_defaults(payload)
    assert payload["server_groups"] == []


def test_coerce_defaults_timezone_propagated() -> None:
    payload: dict[str, Any] = {
        "policy_type_name": "patch",
        "name": "P",
        "schedule": {"days": ["monday"], "time": "02:00", "timezone": "America/New_York"},
        "configuration": {"patch_rule": "all"},
    }
    _coerce_policy_payload_defaults(payload)
    assert payload.get("scheduled_timezone") == "America/New_York"
    assert payload.get("use_scheduled_timezone") is True


# ===========================================================================
# apply_policy_changes — create (real, not preview)
# ===========================================================================


@pytest.mark.asyncio
async def test_apply_policy_changes_real_create_fetches_policy_after_create() -> None:
    """Non-preview create POSTs and then GETs the new policy."""
    created_response = {"id": 200, "name": "New Policy", "policy_type_name": "patch"}
    fetched_policy = {**created_response, "configuration": {"patch_rule": "all"}}

    client = StubClient(
        post_responses={"/policies": [created_response]},
        get_responses={"/policies/200": [fetched_policy]},
        org_id=555,
    )

    result = await apply_policy_changes(
        cast(AutomoxClient, client),
        org_id=555,
        operations=[
            {
                "action": "create",
                "policy": {
                    "name": "New Policy",
                    "policy_type_name": "patch",
                    "configuration": {"patch_rule": "all"},
                    "schedule": {"days": ["monday"], "time": "02:00"},
                    "server_groups": [],
                },
            }
        ],
        preview=False,
    )

    op = result["data"]["operations"][0]
    assert op["status"] == "created"
    assert op["policy_id"] == 200
    assert op["policy"]["name"] == "New Policy"

    post_calls = [c for c in client.calls if c[0] == "POST"]
    assert len(post_calls) == 1
    get_calls = [c for c in client.calls if c[0] == "GET"]
    assert any("/policies/200" in c[1] for c in get_calls)


@pytest.mark.asyncio
async def test_apply_policy_changes_create_no_policy_id_in_response() -> None:
    """When POST response contains no policy ID, policy_id is set to None."""
    client = StubClient(
        post_responses={"/policies": [{}]},  # empty response — no id
        org_id=555,
    )

    result = await apply_policy_changes(
        cast(AutomoxClient, client),
        org_id=555,
        operations=[
            {
                "action": "create",
                "policy": {
                    "name": "New Policy",
                    "policy_type_name": "patch",
                    "configuration": {"patch_rule": "all"},
                    "schedule": {"days": ["monday"], "time": "02:00"},
                    "server_groups": [],
                },
            }
        ],
        preview=False,
    )

    op = result["data"]["operations"][0]
    assert op["status"] == "created"
    assert op["policy_id"] is None


@pytest.mark.asyncio
async def test_apply_policy_changes_unsupported_action_raises() -> None:
    client = StubClient(org_id=555)

    with pytest.raises(ValueError, match="unsupported action"):
        await apply_policy_changes(
            cast(AutomoxClient, client),
            org_id=555,
            operations=[
                {
                    "action": "delete",
                    "policy": {
                        "name": "P",
                        "policy_type_name": "patch",
                        "configuration": {"patch_rule": "all"},
                    },
                }
            ],
        )


@pytest.mark.asyncio
async def test_apply_policy_changes_missing_policy_id_for_update_raises() -> None:
    client = StubClient(org_id=555)

    with pytest.raises(ValueError, match="requires policy_id"):
        await apply_policy_changes(
            cast(AutomoxClient, client),
            org_id=555,
            operations=[
                {
                    "action": "update",
                    # No policy_id
                    "policy": {"name": "P"},
                }
            ],
        )


@pytest.mark.asyncio
async def test_apply_policy_changes_update_no_merge_uses_put_directly() -> None:
    """merge_existing=False skips the GET and sends PUT directly."""
    existing_policy = {
        "id": 300,
        "name": "Direct Update",
        "policy_type_name": "patch",
        "organization_id": 555,
        "configuration": {"patch_rule": "all"},
        "schedule_days": 62,
        "schedule_time": "03:00",
        "schedule_weeks_of_month": 62,
        "schedule_months": 8190,
        "use_scheduled_timezone": False,
        "notes": "",
        "server_groups": [],
    }

    client = StubClient(
        put_responses={"/policies/300": [{}]},
        get_responses={"/policies/300": [existing_policy]},
        org_id=555,
    )

    result = await apply_policy_changes(
        cast(AutomoxClient, client),
        org_id=555,
        operations=[
            {
                "action": "update",
                "policy_id": 300,
                "merge_existing": False,
                "policy": {
                    "name": "Direct Update",
                    "policy_type_name": "patch",
                    "configuration": {"patch_rule": "all"},
                    "schedule_days": 62,
                    "schedule_time": "03:00",
                    "schedule_weeks_of_month": 62,
                    "schedule_months": 8190,
                    "notes": "",
                    "server_groups": [],
                    "use_scheduled_timezone": False,
                },
            }
        ],
        preview=False,
    )

    op = result["data"]["operations"][0]
    assert op["status"] == "updated"
    # No previous_policy because merge_existing=False
    assert "previous_policy" not in op

    put_calls = [c for c in client.calls if c[0] == "PUT"]
    assert len(put_calls) == 1


@pytest.mark.asyncio
async def test_apply_policy_changes_update_preview() -> None:
    """Preview update mode does a GET to build the payload but does not PUT."""
    existing_policy = {
        "id": 400,
        "name": "Preview Update",
        "policy_type_name": "patch",
        "organization_id": 555,
        "configuration": {"patch_rule": "all"},
        "schedule_days": 62,
        "schedule_time": "04:00",
        "schedule_weeks_of_month": 62,
        "schedule_months": 8190,
        "use_scheduled_timezone": False,
        "notes": "",
        "server_groups": [],
    }

    client = StubClient(
        get_responses={"/policies/400": [existing_policy]},
        org_id=555,
    )

    result = await apply_policy_changes(
        cast(AutomoxClient, client),
        org_id=555,
        operations=[
            {
                "action": "update",
                "policy_id": 400,
                "merge_existing": True,
                "policy": {"notes": "Updated note"},
            }
        ],
        preview=True,
    )

    op = result["data"]["operations"][0]
    assert op["status"] == "preview"
    assert op["request"]["method"] == "PUT"
    assert op["previous_policy"]["id"] == 400

    put_calls = [c for c in client.calls if c[0] == "PUT"]
    assert len(put_calls) == 0


# ===========================================================================
# execute_policy
# ===========================================================================


@pytest.mark.asyncio
async def test_execute_policy_remediate_all() -> None:
    client = StubClient(
        post_responses={"/policies/101/action": [{"status": "ok"}]},
        org_id=555,
    )

    result = await execute_policy(
        cast(AutomoxClient, client),
        org_id=555,
        policy_id=101,
        action="remediateAll",
    )

    assert result["data"]["action"] == "remediateAll"
    assert result["data"]["execution_initiated"] is True
    assert result["data"]["device_id"] is None
    assert result["metadata"]["policy_id"] == 101

    post_calls = [c for c in client.calls if c[0] == "POST"]
    assert len(post_calls) == 1
    _, path, params, body = post_calls[0]
    assert path == "/policies/101/action"
    assert params == {"o": 555}
    assert body == {"action": "remediateAll"}


@pytest.mark.asyncio
async def test_execute_policy_remediate_server_with_device_id() -> None:
    client = StubClient(
        post_responses={"/policies/202/action": [{}]},
        org_id=555,
    )

    result = await execute_policy(
        cast(AutomoxClient, client),
        org_id=555,
        policy_id=202,
        action="remediateDevice",
        device_id=999,
    )

    assert result["data"]["action"] == "remediateServer"
    assert result["data"]["device_id"] == 999

    _, _, _, body = [c for c in client.calls if c[0] == "POST"][0]
    assert body == {"action": "remediateServer", "serverId": 999}


@pytest.mark.asyncio
async def test_execute_policy_invalid_action_raises() -> None:
    client = StubClient(org_id=555)

    with pytest.raises(ValueError, match="Invalid action"):
        await execute_policy(
            cast(AutomoxClient, client),
            org_id=555,
            policy_id=101,
            action="doSomethingElse",
        )


@pytest.mark.asyncio
async def test_execute_policy_remediate_server_without_device_id_raises() -> None:
    client = StubClient(org_id=555)

    with pytest.raises(ValueError, match="device_id is required"):
        await execute_policy(
            cast(AutomoxClient, client),
            org_id=555,
            policy_id=101,
            action="remediateDevice",
        )


@pytest.mark.asyncio
async def test_execute_policy_no_org_id_raises() -> None:
    client = StubClient(org_id=0)
    client.org_id = None  # type: ignore[assignment]

    with pytest.raises(ValueError, match="org_id required"):
        await execute_policy(
            cast(AutomoxClient, client),
            policy_id=101,
            action="remediateAll",
        )


# ===========================================================================
# resolve_patch_approval
# ===========================================================================


@pytest.mark.asyncio
async def test_resolve_patch_approval_approve() -> None:
    client = StubClient(
        put_responses={"/approvals/77": [{"id": 77, "status": "approved"}]},
        org_id=555,
    )

    result = await resolve_patch_approval(
        cast(AutomoxClient, client),
        org_id=555,
        approval_id=77,
        decision="approve",
        notes="LGTM",
    )

    assert result["data"]["decision"] == "approved"
    assert result["data"]["approval_id"] == 77
    assert result["data"]["notes"] == "LGTM"

    put_calls = [c for c in client.calls if c[0] == "PUT"]
    assert len(put_calls) == 1
    _, path, params, body = put_calls[0]
    assert path == "/approvals/77"
    assert params == {"o": 555}
    assert body == {"status": "approved", "notes": "LGTM"}


@pytest.mark.asyncio
async def test_resolve_patch_approval_reject() -> None:
    client = StubClient(
        put_responses={"/approvals/88": [{}]},
        org_id=555,
    )

    result = await resolve_patch_approval(
        cast(AutomoxClient, client),
        org_id=555,
        approval_id=88,
        decision="reject",
    )

    assert result["data"]["decision"] == "rejected"
    assert result["data"]["notes"] is None

    _, _, _, body = [c for c in client.calls if c[0] == "PUT"][0]
    assert body == {"status": "rejected"}  # notes omitted when falsy


@pytest.mark.asyncio
async def test_resolve_patch_approval_deny_alias() -> None:
    client = StubClient(
        put_responses={"/approvals/99": [{}]},
        org_id=555,
    )

    result = await resolve_patch_approval(
        cast(AutomoxClient, client),
        org_id=555,
        approval_id=99,
        decision="deny",
    )

    assert result["data"]["decision"] == "rejected"


@pytest.mark.asyncio
async def test_resolve_patch_approval_accept_alias() -> None:
    client = StubClient(
        put_responses={"/approvals/11": [{}]},
        org_id=555,
    )

    result = await resolve_patch_approval(
        cast(AutomoxClient, client),
        org_id=555,
        approval_id=11,
        decision="accept",
    )

    assert result["data"]["decision"] == "approved"


@pytest.mark.asyncio
async def test_resolve_patch_approval_invalid_decision_raises() -> None:
    client = StubClient(org_id=555)

    with pytest.raises(ValueError, match="Unsupported decision"):
        await resolve_patch_approval(
            cast(AutomoxClient, client),
            org_id=555,
            approval_id=1,
            decision="maybe",
        )


@pytest.mark.asyncio
async def test_resolve_patch_approval_no_org_id_raises() -> None:
    client = StubClient(org_id=0)
    client.org_id = None  # type: ignore[assignment]

    with pytest.raises(ValueError, match="org_id required"):
        await resolve_patch_approval(
            cast(AutomoxClient, client),
            approval_id=1,
            decision="approve",
        )


# ===========================================================================
# _deep_merge_dicts
# ===========================================================================


def test_deep_merge_dicts_nested() -> None:
    base = {"a": 1, "b": {"x": 10, "y": 20}}
    overrides = {"b": {"y": 99, "z": 30}, "c": 3}
    result = _deep_merge_dicts(base, overrides)
    assert result["a"] == 1
    assert result["b"]["x"] == 10
    assert result["b"]["y"] == 99
    assert result["b"]["z"] == 30
    assert result["c"] == 3


def test_deep_merge_dicts_override_wins_for_non_mapping() -> None:
    base = {"list_field": [1, 2, 3]}
    overrides = {"list_field": [4, 5]}
    result = _deep_merge_dicts(base, overrides)
    assert result["list_field"] == [4, 5]


def test_deep_merge_dicts_does_not_mutate_base() -> None:
    base = {"a": {"nested": 1}}
    overrides = {"a": {"nested": 2}}
    _deep_merge_dicts(base, overrides)
    assert base["a"]["nested"] == 1
