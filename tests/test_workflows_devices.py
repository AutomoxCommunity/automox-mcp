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
        "compliant": False,
        "uptime": "8077",
        "status": {
            "device_status": "active",
            "agent_status": "active",
            "policy_status": "active",
            "policy_statuses": [
                {"id": 1, "compliant": True},
                {"id": 2, "compliant": False},
                {"id": 3, "compliant": False},
            ],
        },
        # Shape captured from a live GET /servers/{id} payload (sanitized):
        # `status` is the integer enum (0 needs_remediation / 1 up_to_date /
        # 2 pending), `result` is "{}" when empty, `uptime` above is a bare
        # numeric string of minutes.
        "policy_status": [
            {
                "id": 910001,
                "organization_id": 9000,
                "policy_id": 1,
                "server_id": 42,
                "policy_name": "Monthly Patching",
                "policy_type_name": "patch",
                "status": 1,
                "result": "{}",
                "create_time": "2024-05-10T12:00:00+0000",
                "next_remediation": "2024-05-12T01:00:00+0000",
                "pending_count": 0,
                "will_reboot": False,
            },
            {
                "id": 910002,
                "organization_id": 9000,
                "policy_id": 2,
                "server_id": 42,
                "policy_name": "Third Party Patching",
                "policy_type_name": "patch",
                "status": 0,
                "result": "{}",
                "create_time": "2024-05-10T12:00:00+0000",
                "next_remediation": "2024-05-12T01:00:00+0000",
                "pending_count": 0,
                "will_reboot": False,
            },
            {
                "id": 910003,
                "organization_id": 9000,
                "policy_id": 3,
                "server_id": 42,
                "policy_name": "Disk Encryption Check",
                "policy_type_name": "custom",
                "status": 2,
                "result": "{}",
                "create_time": "2024-05-10T12:00:00+0000",
                "next_remediation": "2024-05-12T01:00:00+0000",
                "pending_count": 0,
                "will_reboot": False,
            },
        ],
        # Shape captured from a live GET /servers/{id} server_policies entry
        # (sanitized 2026-06-05): `status` is the integer policy-status enum
        # (here 1 = up_to_date), and `server_groups` is a list of integer
        # group IDs — never objects with a `name`.
        "server_policies": [
            {
                "id": 99,
                "uuid": "33333333-3333-3333-3333-333333333333",
                "name": "VirtualBox Install",
                "policy_type_name": "custom",
                "status": 1,
                "next_remediation": "2024-05-12T01:00:00Z",
                "server_groups": [166208, 204462],
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
        # Shape captured from a live GET /servers/{id}/packages item
        # (sanitized 2026-06-05): there is NO `status` key; real signals are
        # installed/ignored/severity/agent_severity/cve_score/cves/etc.
        # Observed severity vocab: critical/high/no_known_cves/null.
        ("/servers/42/packages", "console"): [
            {
                "name": "zoom",
                "version": "6.3.0",
                "installed": True,
                "ignored": False,
                "severity": "high",
                "agent_severity": None,
                "cve_score": 8.1,
                "cves": ["CVE-2024-0001"],
                "requires_reboot": False,
            }
        ],
        (inventory_path, "console"): {
            "Applications": [{"name": "zoom"}, {"name": "slack"}],
            "Hardware": [{"name": "Disk", "size": "512GB"}],
        },
        # Shape captured from a live GET /servers/{id}/queues item (sanitized
        # 2026-06-05): the real fields are command_type_name and exec_time
        # (an ISO-8601 scheduled-execution timestamp with offset), plus
        # args/policy_id/response. There is NO command/scheduled_time/status.
        ("/servers/42/queues", "console"): [
            {
                "id": 555,
                "server_id": 42,
                "command_id": 777,
                "command_type_name": "Reboot",
                "agent_command_type": 3,
                "exec_time": "2026-06-05T04:09:06+0000",
                "args": "",
                "policy_id": 99,
                "reboot": True,
                "response": None,
                "response_time": None,
            }
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
    # Integer status codes are translated, not passed through raw.
    assert [entry["status"] for entry in core["policy_status"]] == [
        "up_to_date",
        "needs_remediation",
        "pending",
    ]
    # `uptime` is renamed with its (verified) unit and parsed to an int.
    assert "uptime" not in core
    assert core["uptime_minutes"] == 8077

    policy_assignments = result["data"]["policy_assignments"]
    assignment = policy_assignments["policies"][0]
    assert "evaluation_code" not in assignment
    # server_policies[].status is the integer enum, decoded to a label —
    # not the old raw "1"/"2" passthrough.
    assert assignment["status"] == "up_to_date"
    assert policy_assignments["status_breakdown"] == {"up_to_date": 1}
    # server_groups is a list of integer IDs live; the projection surfaces
    # them as server_group_ids, not a (always-empty) `server_groups` name list.
    assert assignment["server_group_ids"] == [166208, 204462]
    assert "server_groups" not in assignment

    # software_preview drops the phantom (always-null) `status` key and
    # carries the real per-package signals.
    software = result["data"]["software_preview"][0]
    assert "status" not in software
    assert software["installed"] is True
    assert software["severity"] == "high"
    assert software["cves"] == ["CVE-2024-0001"]

    # pending_commands maps the live Command fields; the phantom
    # command/scheduled_time/status keys are gone.
    pending = result["data"]["pending_commands"][0]
    assert "command" not in pending
    assert "status" not in pending
    assert pending["command_type"] == "Reboot"
    assert pending["scheduled_time"] == "2026-06-05T04:09:06+0000"

    # The legend that explains these decodings is present.
    assert "field_notes" in result["metadata"]
    field_notes = result["metadata"]["field_notes"]
    assert "policy_assignments.status_breakdown" in field_notes
    assert "software_preview" in field_notes
    assert "pending_commands" in field_notes

    # N2: a reconciling note for the legacy core.status string points the model
    # at the authoritative compliant boolean / rollup.
    assert "core.status" in field_notes
    assert "compliance.device_compliant" in field_notes["core.status"]

    # N10: the status_breakdown note explains it is computed from a different
    # source array (server_policies[]) than compliance.policy_status_counts
    # (policy_status[]), so the two per-policy breakdowns can differ.
    sb_note = field_notes["policy_assignments.status_breakdown"]
    assert "server_policies[]" in sb_note
    assert "policy_status[]" in sb_note

    compliance = result["data"]["compliance"]
    assert compliance["device_compliant"] is False
    assert compliance["policy_status_counts"] == {
        "up_to_date": 1,
        "needs_remediation": 1,
        "pending": 1,
    }
    assert compliance["needs_remediation_policies"] == [
        {"policy_id": 2, "policy_name": "Third Party Patching"}
    ]
    assert "note" in compliance

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
    assert metadata["policy_status_total"] == 3
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
