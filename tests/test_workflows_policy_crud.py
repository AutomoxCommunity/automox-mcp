"""Tests for policy CRUD gap workflows (delete, clone, stats)."""

import copy
from typing import Any, cast

import pytest
from fastmcp.exceptions import ToolError

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy import get_policy_compliance_stats
from automox_mcp.workflows.policy_crud import (
    clone_policy,
    delete_policy,
    list_devices_for_policies,
    preview_policy_device_filters,
)


class StubClient:
    """Minimal Automox client stub for policy CRUD testing."""

    def __init__(
        self,
        *,
        get_responses: dict[str, list[Any]] | None = None,
        post_responses: dict[str, list[Any]] | None = None,
        delete_responses: dict[str, list[Any]] | None = None,
    ) -> None:
        self._get_responses = {key: list(value) for key, value in (get_responses or {}).items()}
        self._post_responses = {key: list(value) for key, value in (post_responses or {}).items()}
        self._delete_responses = {
            key: list(value) for key, value in (delete_responses or {}).items()
        }
        self.org_id: int | None = 555
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

    async def delete(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(("DELETE", path, params, None))
        responses = self._delete_responses.get(path)
        if responses is None:
            raise AssertionError(f"Unexpected DELETE request: {path}")
        if not responses:
            raise AssertionError(f"No remaining DELETE responses for {path}")
        return copy.deepcopy(responses.pop(0))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SOURCE_POLICY: dict[str, Any] = {
    "id": 901,
    "uuid": "11111111-1111-1111-1111-111111111111",
    "name": "Weekday Patching",
    "policy_type_name": "patch",
    "organization_id": 555,
    "configuration": {
        "patch_rule": "filter",
        "filters": ["*Chrome*"],
        "auto_patch": True,
        "auto_reboot": False,
    },
    "schedule_days": 62,
    "schedule_time": "02:00",
    "schedule_weeks_of_month": 62,
    "schedule_months": 8190,
    "use_scheduled_timezone": False,
    "notes": "Original baseline",
    "server_groups": [10, 11],
    "create_time": "2024-01-01T00:00:00Z",
    "status": "active",
    "server_count": 25,
    "policy_uuid": "11111111-1111-1111-1111-111111111111",
    "account_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
}

# Live /policystats shape (sanitized capture 2026-06-05): keys are
# `noncompliant` (no underscore) and a `pending` count rides along.
_POLICYSTATS_RESPONSE: list[dict[str, Any]] = [
    {
        "organization_id": 555,
        "policy_id": 301,
        "policy_name": "Weekday Patching",
        "policy_type_name": "patch",
        "compliant": 18,
        "noncompliant": 2,
        "pending": 20,
    },
    {
        "policy_id": 302,
        "policy_name": "Custom Compliance",
        "compliant": 10,
        "non_compliant": 0,
    },
    {
        "organization_id": 555,
        "policy_id": 303,
        "policy_name": "Required Software",
        "policy_type_name": "required_software",
        "compliant": 5,
        "noncompliant": 5,
        "pending": 0,
    },
]


# ---------------------------------------------------------------------------
# Tests: delete_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_policy_sends_correct_request() -> None:
    client = StubClient(
        delete_responses={"/policies/901": [{}]},
    )

    result = await delete_policy(
        cast(AutomoxClient, client),
        org_id=555,
        policy_id=901,
    )

    assert result["data"]["policy_id"] == 901
    assert result["data"]["deleted"] is True
    assert result["metadata"]["org_id"] == 555

    # Verify the actual API call
    assert len(client.calls) == 1
    method, path, params, _ = client.calls[0]
    assert method == "DELETE"
    assert path == "/policies/901"
    assert params == {"o": 555}


@pytest.mark.asyncio
async def test_delete_policy_uses_client_org_id() -> None:
    client = StubClient(
        delete_responses={"/policies/100": [{}]},
    )
    client.org_id = 777

    result = await delete_policy(
        cast(AutomoxClient, client),
        policy_id=100,
    )

    assert result["metadata"]["org_id"] == 777
    _, _, params, _ = client.calls[0]
    assert params == {"o": 777}


@pytest.mark.asyncio
async def test_delete_policy_requires_org_id() -> None:
    client = StubClient()
    client.org_id = None

    with pytest.raises(ValueError, match="org_id required"):
        await delete_policy(
            cast(AutomoxClient, client),
            policy_id=901,
        )


# ---------------------------------------------------------------------------
# Tests: clone_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_policy_creates_copy_with_default_name() -> None:
    cloned_response = {**_SOURCE_POLICY, "id": 902, "name": "Weekday Patching (Clone)"}

    client = StubClient(
        get_responses={"/policies/901": [_SOURCE_POLICY]},
        post_responses={"/policies": [cloned_response]},
    )

    result = await clone_policy(
        cast(AutomoxClient, client),
        org_id=555,
        policy_id=901,
    )

    assert result["data"]["source_policy_id"] == 901
    assert result["data"]["cloned_policy_id"] == 902
    assert result["data"]["name"] == "Weekday Patching (Clone)"

    # Verify the POST call
    post_calls = [c for c in client.calls if c[0] == "POST"]
    assert len(post_calls) == 1
    _, path, params, body = post_calls[0]
    assert path == "/policies"
    assert params == {"o": 555}
    assert body is not None
    # Read-only fields should be stripped
    assert "id" not in body
    assert "uuid" not in body
    assert "create_time" not in body
    assert "server_count" not in body
    assert "status" not in body
    assert "policy_uuid" not in body
    assert "account_id" not in body
    # Core fields should be preserved
    assert body["policy_type_name"] == "patch"
    assert body["configuration"]["filters"] == ["*Chrome*"]
    assert body["organization_id"] == 555


@pytest.mark.asyncio
async def test_clone_policy_with_custom_name_and_groups() -> None:
    cloned_response = {**_SOURCE_POLICY, "id": 903}

    client = StubClient(
        get_responses={"/policies/901": [_SOURCE_POLICY]},
        post_responses={"/policies": [cloned_response]},
    )

    result = await clone_policy(
        cast(AutomoxClient, client),
        org_id=555,
        policy_id=901,
        name="My Custom Clone",
        server_groups=[20, 30],
    )

    assert result["data"]["name"] == "My Custom Clone"

    post_calls = [c for c in client.calls if c[0] == "POST"]
    _, _, _, body = post_calls[0]
    assert body["name"] == "My Custom Clone"
    assert body["server_groups"] == [20, 30]


@pytest.mark.asyncio
async def test_clone_policy_requires_org_id() -> None:
    client = StubClient()
    client.org_id = None

    with pytest.raises(ValueError, match="org_id required"):
        await clone_policy(
            cast(AutomoxClient, client),
            policy_id=901,
        )


@pytest.mark.asyncio
async def test_clone_policy_raises_on_non_mapping_source() -> None:
    client = StubClient(
        get_responses={"/policies/999": [[]]},  # Array instead of mapping
    )

    with pytest.raises(ValueError, match="Failed to retrieve policy 999"):
        await clone_policy(
            cast(AutomoxClient, client),
            org_id=555,
            policy_id=999,
        )


# ---------------------------------------------------------------------------
# Multi-zone clone (issue #91 category E)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_policy_multi_zone_uses_clone_endpoint() -> None:
    clone_response = {
        "policy_name": "Clone of Patch All Policy",
        "policy_type_name": "patch",
        "data": [
            {
                "policy_id": 38421,
                "zone_id": "59f574fe-04ec-4a38-ad96-1854fc95db20",
                "org_id": 100343,
            },
            {
                "policy_id": 38422,
                "zone_id": "6a1b2c3d-04ec-4a38-ad96-1854fc95db21",
                "org_id": 100344,
            },
        ],
    }
    client = StubClient(post_responses={"/policies/901/clone": [clone_response]})

    result = await clone_policy(
        cast(AutomoxClient, client),
        org_id=555,
        policy_id=901,
        target_zone_ids=[
            "59f574fe-04ec-4a38-ad96-1854fc95db20",
            "6a1b2c3d-04ec-4a38-ad96-1854fc95db21",
        ],
    )

    data = result["data"]
    assert data["multi_zone"] is True
    assert data["source_policy_id"] == 901
    assert data["total_clones"] == 2
    assert data["policy_type_name"] == "patch"
    assert data["clones"][0]["zone_id"] == "59f574fe-04ec-4a38-ad96-1854fc95db20"

    # It must NOT do the client-side GET-then-POST; only the clone endpoint is hit.
    post_calls = [c for c in client.calls if c[0] == "POST"]
    assert len(post_calls) == 1
    _, path, params, body = post_calls[0]
    assert path == "/policies/901/clone"
    assert params == {"o": 555}
    assert body == {
        "target_zone_ids": [
            "59f574fe-04ec-4a38-ad96-1854fc95db20",
            "6a1b2c3d-04ec-4a38-ad96-1854fc95db21",
        ]
    }
    assert not any(c[0] == "GET" for c in client.calls)


def test_clone_policy_params_rejects_zone_ids_with_overrides() -> None:
    from pydantic import ValidationError

    from automox_mcp.schemas import ClonePolicyParams

    with pytest.raises(ValidationError, match="cannot be combined"):
        ClonePolicyParams(
            org_id=555,
            policy_id=901,
            name="Nope",
            target_zone_ids=["59f574fe-04ec-4a38-ad96-1854fc95db20"],
        )


def test_clone_policy_params_rejects_malformed_zone_uuid() -> None:
    from pydantic import ValidationError

    from automox_mcp.schemas import ClonePolicyParams

    with pytest.raises(ValidationError):
        ClonePolicyParams(org_id=555, policy_id=901, target_zone_ids=["not-a-uuid"])


# ---------------------------------------------------------------------------
# Tests: get_policy_compliance_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_compliance_stats_computes_per_policy() -> None:
    client = StubClient(
        get_responses={"/policystats": [_POLICYSTATS_RESPONSE]},
    )

    result = await get_policy_compliance_stats(
        cast(AutomoxClient, client),
        org_id=555,
    )

    data = result["data"]
    per_policy = data["per_policy_stats"]
    assert len(per_policy) == 3

    # Check first policy: compliance rate over evaluated devices only;
    # pending reported as its own count and rate over all targeted devices.
    p1 = per_policy[0]
    assert p1["policy_id"] == 301
    assert p1["policy_type"] == "patch"
    assert p1["compliant_devices"] == 18
    assert p1["noncompliant_devices"] == 2
    assert p1["pending_devices"] == 20
    assert p1["total_devices"] == 40
    assert p1["compliance_rate_percent"] == 90.0  # 18 / (18 + 2)
    assert p1["pending_rate_percent"] == 50.0  # 20 / 40

    # Check second policy (100% compliant)
    p2 = per_policy[1]
    assert p2["compliance_rate_percent"] == 100.0

    # Check third policy (50/50)
    p3 = per_policy[2]
    assert p3["compliance_rate_percent"] == 50.0


@pytest.mark.asyncio
async def test_policy_compliance_stats_overall_rate() -> None:
    client = StubClient(
        get_responses={"/policystats": [_POLICYSTATS_RESPONSE]},
    )

    result = await get_policy_compliance_stats(
        cast(AutomoxClient, client),
        org_id=555,
    )

    overall = result["data"]["overall_compliance"]
    # Total: 18+10+5=33 compliant, 2+0+5=7 noncompliant, 20 pending
    assert overall["compliant"] == 33
    assert overall["noncompliant"] == 7
    assert overall["pending"] == 20
    assert overall["total_devices_evaluated"] == 40  # compliant + noncompliant
    assert overall["total_devices"] == 60
    assert overall["compliance_rate_percent"] == 82.5  # over evaluated only
    assert overall["pending_rate_percent"] == 33.3  # 20 / 60
    assert "pending" in result["metadata"]["rate_semantics"]


@pytest.mark.asyncio
async def test_policy_compliance_stats_empty_org() -> None:
    client = StubClient(
        get_responses={"/policystats": [[]]},
    )

    result = await get_policy_compliance_stats(
        cast(AutomoxClient, client),
        org_id=555,
    )

    data = result["data"]
    assert data["per_policy_stats"] == []
    assert data["overall_compliance"]["total_devices_evaluated"] == 0
    # No evaluated devices: rate is null (honest), not a misleading 0%.
    assert data["overall_compliance"]["compliance_rate_percent"] is None
    assert result["metadata"]["policy_count"] == 0


@pytest.mark.asyncio
async def test_policy_compliance_stats_requires_org_id() -> None:
    client = StubClient()
    client.org_id = None

    with pytest.raises(ValueError, match="org_id required"):
        await get_policy_compliance_stats(
            cast(AutomoxClient, client),
        )


@pytest.mark.asyncio
async def test_policy_compliance_stats_sends_correct_request() -> None:
    client = StubClient(
        get_responses={"/policystats": [_POLICYSTATS_RESPONSE]},
    )

    await get_policy_compliance_stats(
        cast(AutomoxClient, client),
        org_id=555,
    )

    assert len(client.calls) == 1
    method, path, params, _ = client.calls[0]
    assert method == "GET"
    assert path == "/policystats"
    assert params == {"o": 555}


# ---------------------------------------------------------------------------
# Policy → device assessment (issue #91 category C, reads)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_policy_device_filters_returns_devices() -> None:
    devices = [{"id": 1, "name": "host-a"}, {"id": 2, "name": "host-b"}]
    client = StubClient(post_responses={"/policies/device-filters-preview": [devices]})
    result = await preview_policy_device_filters(
        cast(AutomoxClient, client),
        org_id=555,
        device_filters=[{"field": "tag", "op": "in", "value": ["prod"]}],
        server_groups=[10],
    )
    assert result["data"]["total_devices"] == 2
    method, path, params, body = client.calls[0]
    assert method == "POST"
    assert path == "/policies/device-filters-preview"
    assert params == {"o": 555}
    assert body["device_filters"][0]["field"] == "tag"
    assert body["server_groups"] == [10]


@pytest.mark.asyncio
async def test_preview_parses_results_size_envelope() -> None:
    """The live endpoint returns {"results": [...], "size": N}, not a bare list /
    {"data": [...]}. Parsing must read results/size, not wrap the envelope as one
    device (which would report total_devices=1 for any result set)."""
    envelope = {
        "results": [{"id": 1, "name": "host-a"}, {"id": 2, "name": "host-b"}],
        "size": 2,
    }
    client = StubClient(post_responses={"/policies/device-filters-preview": [envelope]})
    result = await preview_policy_device_filters(
        cast(AutomoxClient, client),
        org_id=555,
        device_filters=[{"field": "tag", "op": "in", "value": ["prod"]}],
        server_groups=[10],
    )
    assert result["data"]["total_devices"] == 2
    assert [d["id"] for d in result["data"]["devices"]] == [1, 2]


@pytest.mark.asyncio
async def test_preview_requires_server_groups_when_filtering() -> None:
    """A filter-only target 500s upstream; the wrapper pre-empts it with guidance."""
    client = StubClient()
    with pytest.raises(ToolError, match="requires server_groups"):
        await preview_policy_device_filters(
            cast(AutomoxClient, client),
            org_id=555,
            device_filters=[{"field": "tag", "op": "in", "value": ["prod"]}],
        )
    # no upstream call should have been made
    assert client.calls == []


@pytest.mark.asyncio
async def test_preview_rejects_empty_request() -> None:
    """An empty preview request also 500s upstream — rejected locally."""
    client = StubClient()
    with pytest.raises(ToolError, match="server_groups and/or device_filters"):
        await preview_policy_device_filters(cast(AutomoxClient, client), org_id=555)
    assert client.calls == []


@pytest.mark.asyncio
async def test_list_devices_for_policies_posts_uuids() -> None:
    pols = ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
    devices = [{"id": 1}, {"id": 2}, {"id": 3}]
    client = StubClient(post_responses={"/server-groups-api/policies/servers": [devices]})
    result = await list_devices_for_policies(cast(AutomoxClient, client), policies=pols)
    assert result["data"]["total_devices"] == 3
    assert result["data"]["policies"] == pols
    _, path, _params, body = client.calls[0]
    assert path == "/server-groups-api/policies/servers"
    assert body == {"policies": pols}


def test_list_devices_for_policies_params_rejects_bad_uuid() -> None:
    from pydantic import ValidationError

    from automox_mcp.schemas import ListDevicesForPoliciesParams

    with pytest.raises(ValidationError):
        ListDevicesForPoliciesParams(policies=["not-a-uuid"])


def test_batch_update_devices_params_requires_action_keys() -> None:
    from pydantic import ValidationError

    from automox_mcp.schemas import BatchUpdateDevicesParams

    with pytest.raises(ValidationError, match="attribute"):
        BatchUpdateDevicesParams(org_id=555, devices=[1, 2], actions=[{"value": ["x"]}])
