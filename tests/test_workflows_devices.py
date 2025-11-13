import copy
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.devices import describe_device, summarize_device_health


class StubClient:
    """Lightweight Automox client stub for workflow testing."""

    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self._responses = responses

    async def get(
        self,
        path: str,
        *,
        params=None,  # noqa: ANN001
        headers=None,  # noqa: ANN001
        api: str | None = None,
    ) -> Any:
        key = (path, api or "console")
        if key not in self._responses:
            raise AssertionError(f"Unexpected GET request: {key!r}")
        return copy.deepcopy(self._responses[key])


@pytest.fixture()
def device_payload() -> dict[str, Any]:
    org_uuid = "11111111-1111-1111-1111-111111111111"
    device_uuid = "22222222-2222-2222-2222-222222222222"
    return {
        "device_uuid": device_uuid,
        "org_uuid": org_uuid,
        "name": "mac-host",
        "os_name": "macOS",
        "os_version": "14.4.1",
        "agent_version": "38.0",
        "ip_address": "10.0.0.1",
        "ip_addrs_private": [
            "10.0.0.1",
            "10.0.0.2",
            "10.0.0.3",
            "10.0.0.4",
            "10.0.0.5",
            "10.0.0.6",
        ],
        "server_group_id": 456,
        "managed": True,
        "patch_status": "missing",
        "status": {"policy_status": "success"},
        "policy_status": [
            {
                "policy_id": 1,
                "policy_name": "Monthly Patching",
                "status": "success",
                "create_time": "2024-05-10T12:00:00Z",
                "pending_count": 0,
                "will_reboot": False,
            }
        ],
        "server_policies": [
            {
                "id": 99,
                "uuid": "33333333-3333-3333-3333-333333333333",
                "name": "VirtualBox Install",
                "policy_type_name": "custom",
                "status": "success",
                "next_remediation": "2024-05-12T01:00:00Z",
                "server_groups": [{"name": "Engineering"}, {"name": "QA"}],
                "configuration": {
                    "auto_reboot": False,
                    "device_filters": ["isManaged"],
                    "evaluation_code": "A" * 1200,
                },
            }
        ],
        "detail": {
            "MODEL": "MacBookPro18,3",
            "IPS": ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5", "10.0.0.6"],
            "LAST_USER_LOGON": {"USER": "admin", "TIME": "2024-05-10T12:00:00Z", "SRC": "console"},
        },
        "tags": ["prod", "critical", "west"],
    }


def _build_responses(payload: dict[str, Any]) -> dict[tuple[str, str], Any]:
    org_uuid = payload["org_uuid"]
    device_uuid = payload["device_uuid"]
    inventory_path = f"/device-details/orgs/{org_uuid}/devices/{device_uuid}/inventory"
    return {
        ("/servers/42", "console"): payload,
        ("/servers/42/packages", "console"): [
            {"name": "zoom", "version": "6.3.0", "status": "installed"}
        ],
        (inventory_path, "console"): {
            "Applications": [{"name": "zoom"}, {"name": "slack"}],
            "Hardware": [{"name": "Disk", "size": "512GB"}],
        },
        ("/servers/42/queues", "console"): [
            {"command": "Reboot", "scheduled_time": "2024-05-12T14:00:00Z", "status": "pending"}
        ],
    }


@pytest.mark.asyncio
async def test_describe_device_trims_large_payload(device_payload: dict[str, Any]) -> None:
    client = cast(AutomoxClient, StubClient(_build_responses(device_payload)))
    result = await describe_device(
        client,
        org_id=123,
        device_id=42,
        include_packages=True,
        include_inventory=True,
        include_queue=True,
        include_raw_details=False,
    )

    core = result["data"]["core"]
    assert core["device_id"] == 42
    assert core["server_group_id"] == 456
    assert "group" not in core
    assert core["policy_status"][0]["policy_name"] == "Monthly Patching"
    assert "evaluation_code" not in result["data"]["policy_assignments"]["policies"][0]

    raw_details = result["data"]["raw_details"]
    assert raw_details["included"] is False
    assert "payload" not in raw_details
    assert (
        "available_fields" in raw_details and "server_policies" in raw_details["available_fields"]
    )

    device_facts = result["data"]["device_facts"]
    assert device_facts["ip_addresses"][-1].startswith("...")
    assert device_facts["last_user_logon"]["user"] == "admin"

    metadata = result["metadata"]
    assert metadata["policy_status_total"] == 1
    assert metadata["policy_assignments_total"] == 1
    assert metadata["include_raw_details"] is False


@pytest.mark.asyncio
async def test_describe_device_includes_sanitized_raw_payload(
    device_payload: dict[str, Any],
) -> None:
    client = cast(AutomoxClient, StubClient(_build_responses(device_payload)))
    result = await describe_device(
        client,
        org_id=123,
        device_id=42,
        include_packages=False,
        include_inventory=False,
        include_queue=False,
        include_raw_details=True,
    )

    raw_details = result["data"]["raw_details"]
    assert raw_details["included"] is True
    payload = raw_details["payload"]
    assert payload["server_policies"][0]["configuration"]["evaluation_code"].startswith(
        "... (script"
    )
    assert payload["detail"]["IPS"][-1]["_note"].endswith("truncated")
    assert result["metadata"]["include_raw_details"] is True


@pytest.mark.asyncio
async def test_summarize_device_health_respects_alternate_check_in_fields() -> None:
    responses = {
        ("/servers", "console"): [
            {
                "id": 1001,
                "managed": True,
                "patch_status": "success",
                "status": {"policy_status": "success"},
                "last_seen_time": "2024-05-10T12:00:00Z",
            },
            {
                "id": 1002,
                "managed": True,
                "patch_status": "failed",
                "status": {"policy_status": "failed"},
                "last_check_in": "2024-05-11T12:00:00Z",
            },
        ]
    }
    client = cast(AutomoxClient, StubClient(responses))

    reference_time = datetime(2024, 5, 12, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        client,
        org_id=321,
        limit=500,
        include_unmanaged=False,
        current_time=reference_time,
    )

    data = result["data"]
    assert data["total_devices"] == 2
    assert data["managed_breakdown"]["managed"] == 2
    assert data["stale_devices"] == []


@pytest.mark.asyncio
async def test_summarize_device_health_marks_old_checkins_as_stale() -> None:
    responses = {
        ("/servers", "console"): [
            {
                "id": 2001,
                "managed": True,
                "patch_status": "success",
                "status": {"policy_status": "success"},
                "last_check_in": "2024-01-01T12:00:00Z",
            }
        ]
    }
    client = cast(AutomoxClient, StubClient(responses))

    reference_time = datetime(2024, 3, 31, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        client,
        org_id=999,
        limit=500,
        include_unmanaged=False,
        current_time=reference_time,
    )

    data = result["data"]
    stale_devices = data["stale_devices"]
    assert len(stale_devices) == 1
    stale_device = stale_devices[0]
    assert stale_device["device_id"] == 2001
    assert stale_device["days_since_check_in"] == 90
    assert "last check-in" in stale_device["reason"]

    metadata = result["metadata"]
    assert metadata["stale_device_count"] == 1
    assert metadata["stale_check_in_threshold_days"] == 30
