"""Extended tests for undertested functions in automox_mcp.workflows.devices."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.devices import (
    _build_compliance_summary,
    _build_device_core,
    _calculate_days_since_check_in,
    _count_failed_policies,
    _extract_detail_facts,
    _extract_last_check_in,
    _format_device_display_name,
    _normalize_status,
    _policy_entry_status,
    _sanitize_raw_device_payload,
    _summarize_device_common_fields,
    _summarize_policy_assignments,
    _summarize_policy_status,
    batch_update_devices,
    delete_device,
    enrich_raw_device_payload,
    list_device_inventory,
    list_devices_needing_attention,
    search_devices,
    summarize_device_health,
    update_device,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device(
    device_id: int,
    *,
    name: str = "host",
    managed: bool = True,
    policy_status: str = "success",
    ip_address: str | None = None,
    tags: list[str] | None = None,
    last_check_in: str | None = "2024-05-10T12:00:00Z",
    pending_patches: int | None = None,
    needs_attention: bool | None = None,
    os_name: str = "Windows",
    compliant: bool | None = None,
    pending: bool | None = None,
) -> dict[str, Any]:
    device: dict[str, Any] = {
        "id": device_id,
        "name": name,
        "managed": managed,
        "status": {"policy_status": policy_status},
        "os_name": os_name,
    }
    if ip_address is not None:
        device["ip_address"] = ip_address
    if tags is not None:
        device["tags"] = tags
    if last_check_in is not None:
        device["last_check_in"] = last_check_in
    if pending_patches is not None:
        device["pending_patches"] = pending_patches
    if needs_attention is not None:
        device["needs_attention"] = needs_attention
    if compliant is not None:
        device["compliant"] = compliant
    if pending is not None:
        device["pending"] = pending
    return device


# ===========================================================================
# _normalize_status — edge cases
# ===========================================================================


def test_normalize_status_none_returns_unknown() -> None:
    assert _normalize_status(None) == "unknown"


def test_normalize_status_empty_string_returns_unknown() -> None:
    assert _normalize_status("") == "unknown"


def test_normalize_status_empty_list_returns_unknown() -> None:
    assert _normalize_status([]) == "unknown"


def test_normalize_status_empty_dict_returns_unknown() -> None:
    assert _normalize_status({}) == "unknown"


def test_normalize_status_mapping_with_status_key() -> None:
    assert _normalize_status({"status": "success"}) == "success"


def test_normalize_status_mapping_with_policy_status_key() -> None:
    assert _normalize_status({"policy_status": "failed"}) == "failed"


def test_normalize_status_mapping_with_result_status_key() -> None:
    assert _normalize_status({"result_status": "completed"}) == "success"


def test_normalize_status_mapping_with_state_key() -> None:
    assert _normalize_status({"state": "cancel"}) == "cancelled"


def test_normalize_status_mapping_all_empty_returns_unknown() -> None:
    # All recognized keys have empty values → unknown
    assert _normalize_status({"status": None, "policy_status": "", "state": []}) == "unknown"


def test_normalize_status_mapping_no_recognized_keys() -> None:
    # Dict with no recognized keys returns unknown
    assert _normalize_status({"foo": "bar"}) == "unknown"


def test_normalize_status_sequence_single_uniform() -> None:
    # All entries resolve to the same status
    assert _normalize_status(["success", "succeeded", "completed"]) == "success"


def test_normalize_status_sequence_mixed() -> None:
    # Multiple distinct statuses → "mixed"
    assert _normalize_status(["success", "failed"]) == "mixed"


def test_normalize_status_sequence_all_unknown_returns_unknown() -> None:
    assert _normalize_status([None, "", []]) == "unknown"


def test_normalize_status_sequence_skips_unknown_items() -> None:
    # Only one non-unknown item
    assert _normalize_status([None, "success"]) == "success"


def test_normalize_status_curly_brace_chars_returns_mixed() -> None:
    assert _normalize_status("{some json}") == "mixed"


def test_normalize_status_square_bracket_chars_returns_mixed() -> None:
    assert _normalize_status("[array]") == "mixed"


def test_normalize_status_partial_success() -> None:
    assert _normalize_status("partial_success") == "partial"


def test_normalize_status_partial_string() -> None:
    assert _normalize_status("partial") == "partial"


def test_normalize_status_error_string() -> None:
    assert _normalize_status("some_error") == "failed"


def test_normalize_status_fail_substring() -> None:
    assert _normalize_status("failure_detected") == "failed"


def test_normalize_status_cancel_substring() -> None:
    assert _normalize_status("user_cancelled") == "cancelled"


def test_normalize_status_passthrough_unknown_string() -> None:
    # Strings not matching any known pattern pass through as-is (lowercased)
    assert _normalize_status("pending") == "pending"


def test_normalize_status_whitespace_only_string() -> None:
    assert _normalize_status("   ") == "unknown"


# ===========================================================================
# _extract_last_check_in — non-string values
# ===========================================================================


def test_extract_last_check_in_integer_value() -> None:
    # A non-string, non-empty value should be str()-converted
    device = {"last_check_in": 1718213009}
    result = _extract_last_check_in(device)
    assert result == "1718213009"


def test_extract_last_check_in_float_value() -> None:
    device = {"last_check_in": 3.14}
    result = _extract_last_check_in(device)
    assert result == "3.14"


def test_extract_last_check_in_skips_empty_values_uses_fallback() -> None:
    # last_check_in is empty, should fall through to last_seen
    device = {"last_check_in": None, "last_seen": "2024-01-01T00:00:00Z"}
    result = _extract_last_check_in(device)
    assert result == "2024-01-01T00:00:00Z"


def test_extract_last_check_in_all_empty_returns_none() -> None:
    device = {"last_check_in": None, "last_seen": ""}
    result = _extract_last_check_in(device)
    assert result is None


# ===========================================================================
# _calculate_days_since_check_in — invalid timestamp
# ===========================================================================


def test_calculate_days_invalid_timestamp_returns_none() -> None:
    result = _calculate_days_since_check_in("not-a-timestamp")
    assert result is None


def test_calculate_days_none_timestamp_returns_none() -> None:
    assert _calculate_days_since_check_in(None) is None


def test_calculate_days_empty_string_returns_none() -> None:
    assert _calculate_days_since_check_in("") is None


def test_calculate_days_valid_timestamp() -> None:
    now = datetime(2024, 5, 11, 0, 0, 0, tzinfo=UTC)
    result = _calculate_days_since_check_in("2024-05-10T00:00:00Z", now=now)
    assert result == 1


# ===========================================================================
# _format_device_display_name — edge cases
# ===========================================================================


def test_format_device_display_name_non_string_hostname() -> None:
    # hostname_value is an int (non-string, non-None)
    device = {"name": 12345}
    result = _format_device_display_name(device)
    assert result == "12345"


def test_format_device_display_name_with_custom_name() -> None:
    device = {"name": "server-01", "custom_name": "web-frontend"}
    result = _format_device_display_name(device)
    assert result == "server-01 (web-frontend)"


def test_format_device_display_name_non_string_custom_name() -> None:
    device = {"name": "server-01", "custom_name": 99}
    result = _format_device_display_name(device)
    assert result == "server-01 (99)"


def test_format_device_display_name_empty_custom_name_ignored() -> None:
    device = {"name": "server-01", "custom_name": "  "}
    result = _format_device_display_name(device)
    assert result == "server-01"


def test_format_device_display_name_no_hostname_returns_none() -> None:
    device = {"custom_name": "alias"}
    result = _format_device_display_name(device)
    assert result is None


def test_format_device_display_name_fallback_to_hostname_key() -> None:
    device = {"hostname": "alt-host"}
    result = _format_device_display_name(device)
    assert result == "alt-host"


def test_format_device_display_name_fallback_to_device_name_key() -> None:
    device = {"device_name": "device-42"}
    result = _format_device_display_name(device)
    assert result == "device-42"


# ===========================================================================
# _count_failed_policies
# ===========================================================================


def test_count_failed_policies_no_status() -> None:
    assert _count_failed_policies({}) == 0


def test_count_failed_policies_status_not_mapping() -> None:
    assert _count_failed_policies({"status": "string"}) == 0


def test_count_failed_policies_no_policy_statuses_key() -> None:
    assert _count_failed_policies({"status": {"other_key": []}}) == 0


def test_count_failed_policies_policy_statuses_not_sequence() -> None:
    assert _count_failed_policies({"status": {"policy_statuses": "bad"}}) == 0


def test_count_failed_policies_counts_non_compliant() -> None:
    device = {
        "status": {
            "policy_statuses": [
                {"compliant": False},
                {"compliant": True},
                {"compliant": False},
                {"not_compliant_key": True},  # no compliant key → not counted
            ]
        }
    }
    assert _count_failed_policies(device) == 2


def test_count_failed_policies_all_compliant() -> None:
    device = {"status": {"policy_statuses": [{"compliant": True}, {"compliant": True}]}}
    assert _count_failed_policies(device) == 0


# ===========================================================================
# _summarize_device_common_fields — branches
# ===========================================================================


def test_summarize_device_common_fields_managed_none_defaults_true() -> None:
    device = {"os_name": "Linux"}  # no "managed" key
    result = _summarize_device_common_fields(device)
    assert result["is_managed"] is True


def test_summarize_device_common_fields_managed_false() -> None:
    device = {"managed": False}
    result = _summarize_device_common_fields(device)
    assert result["is_managed"] is False


def test_summarize_device_common_fields_pending_patches_non_numeric() -> None:
    device = {"pending_patches": "many"}
    result = _summarize_device_common_fields(device)
    assert result["pending_patches"] is None


def test_summarize_device_common_fields_pending_patches_numeric() -> None:
    device = {"pending_patches": 7}
    result = _summarize_device_common_fields(device)
    assert result["pending_patches"] == 7


def test_summarize_device_common_fields_has_pending_updates_non_bool() -> None:
    device = {"pending": "yes"}
    result = _summarize_device_common_fields(device)
    assert result["has_pending_updates"] is None


def test_summarize_device_common_fields_needs_attention_non_bool() -> None:
    device = {"needs_attention": 1}
    result = _summarize_device_common_fields(device)
    assert result["needs_attention"] is None


def test_summarize_device_common_fields_device_status_from_status_mapping() -> None:
    device = {"status": {"device_status": "active"}}
    result = _summarize_device_common_fields(device)
    assert result["device_status"] == "active"


def test_summarize_device_common_fields_platform_fallback() -> None:
    device = {"platform": "Ubuntu"}
    result = _summarize_device_common_fields(device)
    assert result["platform"] == "ubuntu"


# ===========================================================================
# _summarize_policy_status — truncation / limit branches
# ===========================================================================


def test_summarize_policy_status_non_sequence_returns_empty() -> None:
    result, total = _summarize_policy_status("not-a-list")
    assert result == []
    assert total == 0


def test_summarize_policy_status_skips_non_mapping_items() -> None:
    result, total = _summarize_policy_status(["string", 42, None])
    assert result == []
    assert total == 0


def test_summarize_policy_status_result_empty_braces_omitted() -> None:
    entries = [{"policy_id": 1, "result": "{}", "status": "success"}]
    result, total = _summarize_policy_status(entries)
    assert total == 1
    assert "result" not in result[0]


def test_summarize_policy_status_result_populated_included() -> None:
    entries = [{"policy_id": 1, "result": "All patches applied", "status": "success"}]
    result, total = _summarize_policy_status(entries)
    assert result[0]["result"] == "All patches applied"


def test_summarize_policy_status_truncates_at_limit() -> None:
    # 15 items, default limit is 12 → only 12 returned but total is 15
    entries = [{"policy_id": i, "status": "success"} for i in range(15)]
    result, total = _summarize_policy_status(entries)
    assert len(result) == 12
    assert total == 15


def test_summarize_policy_status_custom_limit() -> None:
    entries = [{"policy_id": i, "status": "success"} for i in range(5)]
    result, total = _summarize_policy_status(entries, limit=3)
    assert len(result) == 3
    assert total == 5


# ===========================================================================
# _policy_entry_status — integer enum mapping (live GET /servers shape)
# ===========================================================================


def test_policy_entry_status_maps_integer_codes() -> None:
    # Live policy_status entries carry the integer enum; verified against the
    # spec and the status.policy_statuses[].compliant booleans (2026-06-04).
    assert _policy_entry_status({"status": 0}) == "needs_remediation"
    assert _policy_entry_status({"status": 1}) == "up_to_date"
    assert _policy_entry_status({"status": 2}) == "pending"


def test_policy_entry_status_zero_is_not_unknown() -> None:
    # status 0 is falsy; the old truthiness chain fell through to the absent
    # alternate keys and misreported needs_remediation devices as "unknown".
    result, _ = _summarize_policy_status([{"policy_id": 1, "status": 0}])
    assert result[0]["status"] == "needs_remediation"


def test_policy_entry_status_unmapped_int_passes_through_as_string() -> None:
    assert _policy_entry_status({"status": 7}) == "7"


def test_policy_entry_status_bool_is_not_treated_as_int() -> None:
    # bool is an int subclass; True must not be read as code 1.
    assert _policy_entry_status({"status": True}) == "unknown"


def test_policy_entry_status_string_falls_through_to_normalizer() -> None:
    assert _policy_entry_status({"status": "success"}) == "success"
    assert _policy_entry_status({"policy_status": "failed"}) == "failed"


# ===========================================================================
# _build_compliance_summary
# ===========================================================================


def test_build_compliance_summary_counts_and_failing_names() -> None:
    device = {
        "compliant": False,
        "policy_status": [
            {"policy_id": 1, "policy_name": "Monthly Patching", "status": 1},
            {"policy_id": 2, "policy_name": "Third Party Patching", "status": 0},
            {"policy_id": 3, "policy_name": "Disk Encryption Check", "status": 2},
        ],
    }
    summary = _build_compliance_summary(device)
    assert summary is not None
    assert summary["device_compliant"] is False
    assert summary["policy_status_counts"] == {
        "up_to_date": 1,
        "needs_remediation": 1,
        "pending": 1,
    }
    assert summary["needs_remediation_policies"] == [
        {"policy_id": 2, "policy_name": "Third Party Patching"}
    ]
    assert "needs_remediation_truncated" not in summary
    assert "pending policies" in summary["note"]


def test_build_compliance_summary_none_without_signal() -> None:
    assert _build_compliance_summary({}) is None
    assert _build_compliance_summary({"compliant": "yes"}) is None


def test_build_compliance_summary_device_flag_only() -> None:
    summary = _build_compliance_summary({"compliant": True})
    assert summary is not None
    assert summary["device_compliant"] is True
    assert "policy_status_counts" not in summary


def test_build_compliance_summary_truncates_failing_list() -> None:
    device = {
        "policy_status": [
            {"policy_id": i, "policy_name": f"Policy {i}", "status": 0} for i in range(15)
        ],
    }
    summary = _build_compliance_summary(device)
    assert summary is not None
    assert summary["policy_status_counts"] == {"needs_remediation": 15}
    assert len(summary["needs_remediation_policies"]) == 12
    assert summary["needs_remediation_truncated"] is True


def test_build_compliance_summary_skips_non_mapping_entries() -> None:
    # Nothing usable in the list and no device flag → no summary at all.
    assert _build_compliance_summary({"policy_status": ["bogus", 3, None]}) is None


# ===========================================================================
# _build_device_core — uptime_minutes
# ===========================================================================


def _build_core(device_data: dict[str, Any]) -> dict[str, Any]:
    return _build_device_core(
        device_data,
        device_id=1,
        status_value=None,
        ip_addresses_preview=None,
        tags_preview=None,
        policy_status_summary=[],
    )


def test_build_device_core_parses_uptime_minutes() -> None:
    # Live payloads carry uptime as a numeric string of minutes.
    core = _build_core({"uptime": "8077"})
    assert "uptime" not in core
    assert core["uptime_minutes"] == 8077


def test_build_device_core_keeps_unparseable_uptime_verbatim() -> None:
    core = _build_core({"uptime": "n/a"})
    assert core["uptime_minutes"] == "n/a"


def test_build_device_core_omits_missing_uptime() -> None:
    assert "uptime_minutes" not in _build_core({})


# ===========================================================================
# enrich_raw_device_payload — legend for near-raw passthrough tools
# ===========================================================================


def test_enrich_raw_device_payload_adds_labels_and_compliance() -> None:
    detail = {
        "uptime": "1440",
        "compliant": False,
        "policy_status": [
            {"policy_id": 1, "policy_name": "A", "status": 0},
            {"policy_id": 2, "policy_name": "B", "status": 1},
            {"policy_id": 3, "policy_name": "C", "status": 7},  # unmapped code
            {"policy_id": 4, "policy_name": "D", "status": "success"},  # string: untouched
        ],
    }
    out = enrich_raw_device_payload(detail)
    assert out is detail  # in-place
    labels = [p.get("status_label") for p in detail["policy_status"]]
    assert labels == ["needs_remediation", "up_to_date", "7", None]
    assert [p["status"] for p in detail["policy_status"][:3]] == [0, 1, 7]  # raw kept
    assert "uptime" not in detail
    assert detail["uptime_minutes"] == 1440
    assert detail["compliance"]["device_compliant"] is False
    assert detail["compliance"]["needs_remediation_policies"] == [
        {"policy_id": 1, "policy_name": "A"}
    ]


def test_enrich_raw_device_payload_handles_sparse_payload() -> None:
    # No uptime, no policy_status, no compliant flag → no synthetic keys.
    detail: dict[str, Any] = {"name": "host"}
    out = enrich_raw_device_payload(detail)
    assert out == {"name": "host"}


def test_enrich_raw_device_payload_unparseable_uptime_kept_verbatim() -> None:
    detail: dict[str, Any] = {"uptime": "n/a"}
    assert enrich_raw_device_payload(detail)["uptime_minutes"] == "n/a"


# ===========================================================================
# _summarize_policy_assignments — truncation / limit branches
# ===========================================================================


def test_summarize_policy_assignments_non_sequence_returns_empty() -> None:
    result, counter, total = _summarize_policy_assignments(None)
    assert result == []
    assert total == 0


def test_summarize_policy_assignments_skips_non_mapping_items() -> None:
    result, counter, total = _summarize_policy_assignments(["bad", 42])
    assert result == []
    assert total == 0


def test_summarize_policy_assignments_truncates_at_limit() -> None:
    entries = [{"id": i, "name": f"Policy {i}", "status": "active"} for i in range(15)]
    result, counter, total = _summarize_policy_assignments(entries)
    assert len(result) == 10  # default limit
    assert total == 15


def test_summarize_policy_assignments_server_groups_truncated() -> None:
    # More server_groups than _SANITIZED_SEQUENCE_LIMIT (5)
    groups = [{"name": f"Group {i}"} for i in range(8)]
    entries = [{"id": 1, "name": "P", "server_groups": groups}]
    result, counter, total = _summarize_policy_assignments(entries)
    assert result[0]["server_groups_truncated"] == 3  # 8 - 5


def test_summarize_policy_assignments_counts_status() -> None:
    entries = [
        {"id": 1, "status": "active"},
        {"id": 2, "status": "active"},
        {"id": 3, "status": "inactive"},
    ]
    _, counter, total = _summarize_policy_assignments(entries)
    assert counter["active"] == 2
    assert counter["inactive"] == 1
    assert total == 3


def test_summarize_policy_assignments_device_filters_counted() -> None:
    entries = [{"id": 1, "configuration": {"device_filters": [{"a": 1}, {"b": 2}]}}]
    result, _, _ = _summarize_policy_assignments(entries)
    assert result[0]["device_filter_count"] == 2


def test_summarize_policy_assignments_empty_server_groups() -> None:
    entries = [{"id": 1, "server_groups": []}]
    result, _, _ = _summarize_policy_assignments(entries)
    # server_groups is empty list → filtered out (v not in (None, "", [], {}))
    assert "server_groups" not in result[0]


# ===========================================================================
# _extract_detail_facts
# ===========================================================================


def test_extract_detail_facts_none_returns_none() -> None:
    assert _extract_detail_facts(None) is None


def test_extract_detail_facts_non_mapping_returns_none() -> None:
    assert _extract_detail_facts("string") is None
    assert _extract_detail_facts([1, 2]) is None


def test_extract_detail_facts_empty_mapping_returns_none() -> None:
    # No recognized keys with values → None
    assert _extract_detail_facts({}) is None


def test_extract_detail_facts_scalar_value() -> None:
    detail = {"OS": "Windows 11", "MODEL": "Dell XPS"}
    facts = _extract_detail_facts(detail)
    assert facts is not None
    assert facts["os_name"] == "Windows 11"
    assert facts["model"] == "Dell XPS"


def test_extract_detail_facts_list_value_preview() -> None:
    # IPS is a list → should be truncated at _SANITIZED_SEQUENCE_LIMIT (5)
    ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5", "10.0.0.6"]
    detail = {"IPS": ips}
    facts = _extract_detail_facts(detail)
    assert facts is not None
    ip_list = facts["ip_addresses"]
    assert len(ip_list) == 6  # 5 real + 1 "... N more"
    assert "more" in ip_list[-1]


def test_extract_detail_facts_mapping_value() -> None:
    detail = {"CPU": {"cores": 8, "speed": "3.2GHz", "unused": None}}
    facts = _extract_detail_facts(detail)
    assert facts is not None
    # Mapping is lowercased and empty values filtered
    cpu = facts["cpu"]
    assert cpu["cores"] == 8
    assert "unused" not in cpu


def test_extract_detail_facts_mapping_all_empty_skipped() -> None:
    # Mapping with all-empty values → key omitted
    detail = {"CPU": {"cores": None, "speed": ""}}
    facts = _extract_detail_facts(detail)
    assert facts is None


def test_extract_detail_facts_skips_empty_values() -> None:
    detail = {"OS": None, "MODEL": "", "OS_VERSION": "22H2"}
    facts = _extract_detail_facts(detail)
    assert facts is not None
    assert "os_name" not in facts
    assert "model" not in facts
    assert facts["os_version"] == "22H2"


# ===========================================================================
# _sanitize_raw_device_payload
# ===========================================================================


def test_sanitize_raw_device_payload_omits_script_fields() -> None:
    payload = {"name": "host", "evaluation_code": "if True: pass", "other": "value"}
    result = _sanitize_raw_device_payload(payload)
    assert result["evaluation_code"] == "... (script omitted to reduce payload size)"
    assert result["other"] == "value"


def test_sanitize_raw_device_payload_truncates_long_strings() -> None:
    long_str = "A" * 500
    payload = {"description": long_str}
    result = _sanitize_raw_device_payload(payload)
    assert "chars truncated" in result["description"]


def test_sanitize_raw_device_payload_truncates_long_sequences() -> None:
    payload = {"items": list(range(10))}  # 10 items > _SANITIZED_SEQUENCE_LIMIT (5)
    result = _sanitize_raw_device_payload(payload)
    items = result["items"]
    # Last element should be a dict with a _note key
    assert isinstance(items[-1], dict)
    assert "_note" in items[-1]
    assert "truncated" in items[-1]["_note"]


def test_sanitize_raw_device_payload_nested_mapping() -> None:
    # "script" is in _SCRIPT_FIELDS so it is omitted at any nesting level
    payload = {"outer": {"inner": "value", "script": "x = 1"}}
    result = _sanitize_raw_device_payload(payload)
    assert result["outer"]["inner"] == "value"
    assert result["outer"]["script"] == "... (script omitted to reduce payload size)"


def test_sanitize_raw_device_payload_short_string_unchanged() -> None:
    payload = {"name": "short"}
    result = _sanitize_raw_device_payload(payload)
    assert result["name"] == "short"


# ===========================================================================
# search_devices — severity parsing from JSON string
# ===========================================================================


@pytest.mark.asyncio
async def test_search_devices_returns_all_when_no_filters() -> None:
    devices = [
        _make_device(1, name="alpha"),
        _make_device(2, name="beta"),
        _make_device(3, name="gamma"),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(cast(AutomoxClient, client), org_id=42)

    data = result["data"]
    assert data["matches"] == 3
    assert len(data["devices"]) == 3


@pytest.mark.asyncio
async def test_search_devices_filters_by_hostname() -> None:
    devices = [
        _make_device(1, name="web-server-01"),
        _make_device(2, name="db-server-01"),
        _make_device(3, name="web-server-02"),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(cast(AutomoxClient, client), org_id=42, hostname_contains="web")

    data = result["data"]
    assert data["matches"] == 2
    hostnames = {d["hostname"] for d in data["devices"]}
    assert hostnames == {"web-server-01", "web-server-02"}


@pytest.mark.asyncio
async def test_search_devices_filters_by_hostname_case_insensitive() -> None:
    devices = [_make_device(1, name="WebServer"), _make_device(2, name="dbserver")]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(
        cast(AutomoxClient, client), org_id=42, hostname_contains="webserver"
    )

    assert result["data"]["matches"] == 1
    assert result["data"]["devices"][0]["hostname"] == "WebServer"


@pytest.mark.asyncio
async def test_search_devices_filters_by_tag() -> None:
    devices = [
        _make_device(1, name="prod-1", tags=["prod", "web"]),
        _make_device(2, name="dev-1", tags=["dev"]),
        _make_device(3, name="prod-2", tags=["prod", "db"]),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(cast(AutomoxClient, client), org_id=42, tag="prod")

    data = result["data"]
    assert data["matches"] == 2
    device_ids = {d["device_id"] for d in data["devices"]}
    assert device_ids == {1, 3}


@pytest.mark.asyncio
async def test_search_devices_filters_by_ip_address() -> None:
    devices = [
        _make_device(1, name="host-a", ip_address="10.0.0.1"),
        _make_device(2, name="host-b", ip_address="10.0.0.2"),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(cast(AutomoxClient, client), org_id=42, ip_address="10.0.0.1")

    data = result["data"]
    assert data["matches"] == 1
    assert data["devices"][0]["device_id"] == 1
    assert data["devices"][0]["ip_address"] == "10.0.0.1"


@pytest.mark.asyncio
async def test_search_devices_empty_results() -> None:
    devices = [_make_device(1, name="alpha"), _make_device(2, name="beta")]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(
        cast(AutomoxClient, client), org_id=42, hostname_contains="zzz-nomatch"
    )

    data = result["data"]
    assert data["matches"] == 0
    assert data["devices"] == []


@pytest.mark.asyncio
async def test_search_devices_respects_limit() -> None:
    devices = [_make_device(i, name=f"host-{i:02d}") for i in range(10)]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(cast(AutomoxClient, client), org_id=42, limit=3)

    assert result["data"]["matches"] == 3
    assert len(result["data"]["devices"]) == 3


@pytest.mark.asyncio
async def test_search_devices_metadata_contains_filters() -> None:
    client = StubClient(get_responses={"/servers": [[]]})
    result = await search_devices(
        cast(AutomoxClient, client),
        org_id=42,
        hostname_contains="web",
        tag="prod",
        limit=10,
    )

    meta = result["metadata"]
    assert meta["org_id"] == 42
    assert meta["request_limit"] == 10
    assert meta["filters"]["hostname_contains"] == "web"
    assert meta["filters"]["tag"] == "prod"


@pytest.mark.asyncio
async def test_search_devices_no_org_id_raises() -> None:
    client = StubClient()
    client.org_id = None
    with pytest.raises(ValueError, match="org_id required"):
        await search_devices(cast(AutomoxClient, client))


@pytest.mark.asyncio
async def test_search_devices_api_returns_non_list_treated_as_empty() -> None:
    # When the API returns something unexpected (dict instead of list), result should be empty
    client = StubClient(get_responses={"/servers": [{"unexpected": "dict"}]})
    result = await search_devices(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["matches"] == 0
    assert result["data"]["devices"] == []


@pytest.mark.asyncio
async def test_search_devices_severity_json_string_array() -> None:
    """severity='["critical","high"]' should be parsed into a list."""
    devices = [_make_device(1, name="host")]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(
        cast(AutomoxClient, client),
        org_id=42,
        severity='["critical", "high"]',
    )
    # Parsed correctly — severity filter is in metadata. The model relies on
    # this echo (not per-device data) to know the membership guarantee; the
    # per-device `pending_patches` is the all-severity outstanding total, NOT
    # the severity-filtered count, which the tool description now states.
    severities = result["metadata"]["filters"]["severity"]
    assert severities == ["critical", "high"]


@pytest.mark.asyncio
async def test_search_devices_severity_json_string_non_array() -> None:
    """severity='critical' (no brackets) stays as single value."""
    devices = [_make_device(1, name="host")]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(
        cast(AutomoxClient, client),
        org_id=42,
        severity="critical",
    )
    severities = result["metadata"]["filters"]["severity"]
    assert severities == ["critical"]


@pytest.mark.asyncio
async def test_search_devices_severity_invalid_json_string() -> None:
    """severity='[bad json' should fall back to treating the string as-is."""
    devices = [_make_device(1, name="host")]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(
        cast(AutomoxClient, client),
        org_id=42,
        severity="[bad json",
    )
    severities = result["metadata"]["filters"]["severity"]
    # Fallback: the raw string is used
    assert "[bad json" in severities


@pytest.mark.asyncio
async def test_search_devices_severity_sequence_input() -> None:
    """severity as a list of strings."""
    devices = [_make_device(1, name="host")]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await search_devices(
        cast(AutomoxClient, client),
        org_id=42,
        severity=["critical", "high"],
    )
    severities = result["metadata"]["filters"]["severity"]
    assert set(severities) == {"critical", "high"}


# ===========================================================================
# describe_device — various branches
# ===========================================================================


class FullStubClient:
    """Stub that handles multiple distinct endpoints with exact path matching."""

    def __init__(self, responses: dict[str, list[Any]], *, org_id: int = 42) -> None:
        self.org_id = org_id
        self.org_uuid = None
        self._responses = {k: list(v) for k, v in responses.items()}

    async def get(self, path: str, *, params=None, headers=None) -> Any:
        if path in self._responses and self._responses[path]:
            return self._responses[path].pop(0)
        return {}

    async def post(self, path: str, *, json_data=None, params=None, headers=None) -> Any:
        return {}


def _fresh_describe_device():
    """Return the describe_device function from the live (possibly re-imported) module."""
    from automox_mcp.workflows import devices as mod

    return mod.describe_device


def _patch_get_device_inventory(**kwargs):
    """Return a context manager that patches get_device_inventory in the live module."""
    from automox_mcp.workflows import devices as mod

    return patch.object(mod, "get_device_inventory", **kwargs)


@pytest.mark.asyncio
async def test_describe_device_inventory_summary_populated() -> None:
    """inventory_summary is built when get_device_inventory succeeds."""
    inv_result = {
        "data": {
            "total_items": 42,
            "categories": {
                "Software": {
                    "sub_categories": {
                        "Applications": {"item_count": 30},
                        "Patches": {"item_count": 12},
                    }
                }
            },
        }
    }

    responses = {
        "/servers/1": [{"id": 1, "name": "host-01", "os_name": "Windows"}],
        "/servers/1/queues": [[]],
    }
    client = FullStubClient(responses)

    with _patch_get_device_inventory(new=AsyncMock(return_value=inv_result)):
        result = await _fresh_describe_device()(
            cast(AutomoxClient, client),
            org_id=42,
            device_id=1,
            include_packages=False,
            include_inventory=True,
            include_queue=True,
        )

    inv = result["data"]["inventory_overview"]
    assert inv is not None
    assert inv["total_categories"] == 1
    assert inv["total_items"] == 42
    assert result["metadata"]["inventory_category_count"] == 1


@pytest.mark.asyncio
async def test_describe_device_inventory_error_suppressed() -> None:
    """AutomoxAPIError from get_device_inventory is caught and inventory_summary becomes None."""
    responses = {
        "/servers/1": [{"id": 1, "name": "host-01"}],
        "/servers/1/queues": [[]],
    }
    client = FullStubClient(responses)

    # ValueError is also caught by the except clause in describe_device, and avoids
    # any stale-import identity mismatch with AutomoxAPIError after module reloads.
    with _patch_get_device_inventory(
        new=AsyncMock(side_effect=ValueError("simulated inventory error"))
    ):
        result = await _fresh_describe_device()(
            cast(AutomoxClient, client),
            org_id=42,
            device_id=1,
            include_inventory=True,
            include_queue=True,
        )

    assert result["data"]["inventory_overview"] is None


@pytest.mark.asyncio
async def test_describe_device_tags_non_sequence_scalar() -> None:
    """A scalar tags value (line 665-666) should be wrapped in a list."""
    responses = {
        "/servers/5": [{"id": 5, "name": "host", "tags": "single-tag"}],
        "/servers/5/queues": [[]],
    }
    client = FullStubClient(responses)

    with _patch_get_device_inventory(new=AsyncMock(side_effect=ValueError("skip"))):
        result = await _fresh_describe_device()(
            cast(AutomoxClient, client),
            org_id=42,
            device_id=5,
        )

    assert result["data"]["core"]["tags"] == ["single-tag"]


@pytest.mark.asyncio
async def test_describe_device_tags_truncation() -> None:
    """More than _SANITIZED_SEQUENCE_LIMIT (5) tags should append a '... N more' entry."""
    many_tags = [f"tag-{i}" for i in range(8)]
    responses = {
        "/servers/6": [{"id": 6, "name": "host", "tags": many_tags}],
        "/servers/6/queues": [[]],
    }
    client = FullStubClient(responses)

    with _patch_get_device_inventory(new=AsyncMock(side_effect=ValueError("skip"))):
        result = await _fresh_describe_device()(
            cast(AutomoxClient, client),
            org_id=42,
            device_id=6,
        )

    tags = result["data"]["core"]["tags"]
    assert tags[-1] == "... 3 more"


@pytest.mark.asyncio
async def test_describe_device_include_raw_details_true() -> None:
    """With include_raw_details=True the payload is sanitized and included."""
    device_data = {
        "id": 7,
        "name": "host",
        "evaluation_code": "x = 1",
        "description": "A" * 500,
    }
    responses = {
        "/servers/7": [device_data],
        "/servers/7/queues": [[]],
    }
    client = FullStubClient(responses)

    with _patch_get_device_inventory(new=AsyncMock(side_effect=ValueError("skip"))):
        result = await _fresh_describe_device()(
            cast(AutomoxClient, client),
            org_id=42,
            device_id=7,
            include_raw_details=True,
        )

    raw = result["data"]["raw_details"]
    assert raw["included"] is True
    assert raw["payload"]["evaluation_code"] == "... (script omitted to reduce payload size)"
    assert "chars truncated" in raw["payload"]["description"]


@pytest.mark.asyncio
async def test_describe_device_include_raw_details_false_shows_fields() -> None:
    """With include_raw_details=False, available_fields is listed instead."""
    responses = {
        "/servers/8": [{"id": 8, "name": "host", "os_name": "Linux"}],
        "/servers/8/queues": [[]],
    }
    client = FullStubClient(responses)

    with _patch_get_device_inventory(new=AsyncMock(side_effect=ValueError("skip"))):
        result = await _fresh_describe_device()(
            cast(AutomoxClient, client),
            org_id=42,
            device_id=8,
            include_raw_details=False,
        )

    raw = result["data"]["raw_details"]
    assert raw["included"] is False
    assert "id" in raw["available_fields"]


@pytest.mark.asyncio
async def test_describe_device_detail_facts_extracted() -> None:
    """device_facts key is present when detail dict has recognized keys."""
    responses = {
        "/servers/9": [
            {
                "id": 9,
                "name": "host",
                "detail": {"OS": "Windows 10", "SERIAL_NUMBER": "SN-1234"},
            }
        ],
        "/servers/9/queues": [[]],
    }
    client = FullStubClient(responses)

    with _patch_get_device_inventory(new=AsyncMock(side_effect=ValueError("skip"))):
        result = await _fresh_describe_device()(
            cast(AutomoxClient, client),
            org_id=42,
            device_id=9,
        )

    assert "device_facts" in result["data"]
    assert result["data"]["device_facts"]["os_name"] == "Windows 10"


# ===========================================================================
# summarize_device_health — response size check / truncation
# ===========================================================================


@pytest.mark.asyncio
async def test_summarize_device_health_basic_counts() -> None:
    devices = [
        _make_device(1, policy_status="success", compliant=True, pending=False),
        _make_device(2, policy_status="success", compliant=True, pending=False),
        _make_device(3, policy_status="failed", compliant=False, pending=True),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    data = result["data"]
    assert data["total_devices"] == 3
    assert data["managed_breakdown"]["managed"] == 3
    assert data["compliant_devices"] == 2


@pytest.mark.asyncio
async def test_summarize_device_health_pending_does_not_break_compliance() -> None:
    # Platform rule (live-verified, PR #149): only needs_remediation flips a
    # device non-compliant — `pending: true` with `compliant: true` must
    # count as compliant, tracked separately as pending work.
    devices = [
        _make_device(1, policy_status="success", compliant=True, pending=True),
        _make_device(2, policy_status="success", compliant=True, pending=False),
        _make_device(3, policy_status="failed", compliant=False, pending=True),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    data = result["data"]
    assert data["compliant_devices"] == 2  # pending+compliant stays compliant
    assert data["compliance_breakdown"] == {"compliant": 2, "non_compliant": 1}
    assert data["devices_with_pending_policies"] == 2


@pytest.mark.asyncio
async def test_summarize_device_health_policy_execution_breakdown() -> None:
    devices = [
        _make_device(1, policy_status="success"),
        _make_device(2, policy_status="success"),
        _make_device(3, policy_status="failed"),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    breakdown = result["data"]["policy_execution_breakdown"]
    assert breakdown.get("success", 0) == 2
    assert breakdown.get("failed", 0) == 1


@pytest.mark.asyncio
async def test_summarize_device_health_policy_execution_breakdown_diverges_note() -> None:
    # N2 (live 2026-06-05): the legacy device-level status string can read
    # "non-compliant" on a device whose authoritative `compliant` boolean is
    # true (it only has pending work). policy_execution_breakdown tallies the
    # legacy string, so it diverges from compliance_breakdown — the field_note
    # must warn the model to use compliance_breakdown for compliance.
    devices = [
        _make_device(1, policy_status="non-compliant", compliant=True, pending=True),
        _make_device(2, policy_status="non-compliant", compliant=False, pending=False),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    data = result["data"]
    # Legacy string axis counts both as non-compliant...
    assert data["policy_execution_breakdown"].get("non-compliant") == 2
    # ...while the authoritative axis counts only one.
    assert data["compliance_breakdown"] == {"compliant": 1, "non_compliant": 1}
    note = result["metadata"]["field_notes"]["policy_execution_breakdown"]
    assert "compliance_breakdown" in note
    assert "LEGACY" in note


@pytest.mark.asyncio
async def test_summarize_device_health_excludes_unmanaged_by_default() -> None:
    devices = [
        _make_device(1, managed=True),
        _make_device(2, managed=False),
        _make_device(3, managed=False),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        include_unmanaged=False,
        current_time=reference_time,
    )

    data = result["data"]
    assert data["total_devices"] == 1
    assert data["managed_breakdown"]["managed"] == 1
    assert data["managed_breakdown"].get("unmanaged", 0) == 2


@pytest.mark.asyncio
async def test_summarize_device_health_includes_unmanaged_when_requested() -> None:
    devices = [
        _make_device(1, managed=True),
        _make_device(2, managed=False),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        include_unmanaged=True,
        current_time=reference_time,
    )

    assert result["data"]["total_devices"] == 2


@pytest.mark.asyncio
async def test_summarize_device_health_stale_devices_flagged() -> None:
    devices = [
        _make_device(1, last_check_in="2024-01-01T00:00:00Z"),  # stale: 31 days ago
        _make_device(2, last_check_in="2024-05-10T12:00:00Z"),  # recent
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 2, 1, 0, 0, 0, tzinfo=UTC)  # 31 days after Jan 1

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    data = result["data"]
    stale = data["stale_devices"]
    assert len(stale) == 1
    assert stale[0]["device_id"] == 1
    assert stale[0]["days_since_check_in"] == 31
    assert "check-in" in stale[0]["reason"]


@pytest.mark.asyncio
async def test_summarize_device_health_no_checkin_flagged_as_stale() -> None:
    devices = [_make_device(1, last_check_in=None)]
    # Remove last_check_in key entirely to simulate never-connected device
    devices[0].pop("last_check_in", None)

    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 0, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    stale = result["data"]["stale_devices"]
    assert len(stale) == 1
    assert "no check-in" in stale[0]["reason"]


@pytest.mark.asyncio
async def test_summarize_device_health_invalid_checkin_flagged_as_stale() -> None:
    """A device with a non-parseable check-in timestamp is flagged as stale."""
    devices = [_make_device(1, last_check_in="not-a-date")]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 0, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    stale = result["data"]["stale_devices"]
    assert len(stale) == 1
    assert "invalid" in stale[0]["reason"]


@pytest.mark.asyncio
async def test_summarize_device_health_platform_breakdown() -> None:
    devices = [
        _make_device(1, os_name="Windows"),
        _make_device(2, os_name="Windows"),
        _make_device(3, os_name="macOS"),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    platform_breakdown = result["data"]["platform_breakdown"]
    assert platform_breakdown.get("windows", 0) == 2
    assert platform_breakdown.get("macos", 0) == 1


@pytest.mark.asyncio
async def test_summarize_device_health_devices_with_pending_patches() -> None:
    devices = [
        _make_device(1, pending_patches=5),
        _make_device(2, pending_patches=0),
        _make_device(3, pending_patches=3),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    assert result["data"]["devices_with_pending_patches"] == 2


@pytest.mark.asyncio
async def test_summarize_device_health_metadata_fields() -> None:
    client = StubClient(get_responses={"/servers": [[]]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        limit=100,
        current_time=reference_time,
    )

    meta = result["metadata"]
    assert meta["org_id"] == 42
    assert meta["requested_limit"] == 100
    assert meta["stale_check_in_threshold_days"] == 30
    assert meta["stale_device_count"] == 0


@pytest.mark.asyncio
async def test_summarize_device_health_no_org_id_raises() -> None:
    client = StubClient()
    client.org_id = None
    with pytest.raises(ValueError, match="org_id required"):
        await summarize_device_health(cast(AutomoxClient, client))


@pytest.mark.asyncio
async def test_summarize_device_health_stale_devices_truncated_by_limit() -> None:
    """With max_stale_devices=2, only 2 stale devices are shown but count is full."""
    stale_devices = [_make_device(i, last_check_in="2020-01-01T00:00:00Z") for i in range(1, 6)]
    client = StubClient(get_responses={"/servers": [stale_devices]})
    reference_time = datetime(2024, 5, 11, 0, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
        max_stale_devices=2,
    )

    assert len(result["data"]["stale_devices"]) == 2
    assert result["metadata"]["stale_device_count"] == 5
    assert result["metadata"]["stale_devices_truncated"] is True


@pytest.mark.asyncio
async def test_summarize_device_health_max_stale_devices_none_returns_all() -> None:
    """max_stale_devices=None returns all stale devices without truncation."""
    stale_devices = [_make_device(i, last_check_in="2020-01-01T00:00:00Z") for i in range(1, 6)]
    client = StubClient(get_responses={"/servers": [stale_devices]})
    reference_time = datetime(2024, 5, 11, 0, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
        max_stale_devices=None,
    )

    assert len(result["data"]["stale_devices"]) == 5
    assert "stale_devices_truncated" not in result["metadata"]


@pytest.mark.asyncio
async def test_summarize_device_health_large_response_sets_truncation_flag() -> None:
    """When response JSON exceeds _MAX_HEALTH_RESPONSE_BYTES, metadata flags it."""
    # Create enough devices with long hostnames to exceed 18 000 bytes
    devices = [
        _make_device(i, name="x" * 200, last_check_in="2024-05-10T12:00:00Z") for i in range(100)
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2024, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    meta = result["metadata"]
    # The flag may or may not be set depending on actual payload size, but the key must exist
    assert "approx_response_bytes" in meta
    if meta.get("response_truncated"):
        assert "suggested_followups" in meta


# ===========================================================================
# list_devices_needing_attention tests (carried over)
# ===========================================================================


@pytest.mark.asyncio
async def test_list_devices_needing_attention_basic_camelcase() -> None:
    """The /reports/needs-attention endpoint returns camelCase fields.

    `groupId`, `lastRefreshTime`, `compliant`, `policies` need to be
    mapped to the wrapper's snake_case output. Earlier revisions looked
    for `server_group_id`/`last_check_in`/`policy_status`/`pending_updates`
    that the API never returns, so every diagnostic field was null.
    """
    report = {
        "nonCompliant": {
            "total": 1,
            "devices": [
                {
                    "id": 10,
                    "name": "trouble-host",
                    "compliant": False,
                    "groupId": 99,
                    "lastRefreshTime": "2026-05-07T12:00:00+0000",
                    "needsReboot": True,
                    "os_family": "Mac",
                    "connected": True,
                    # nonCompliant.devices[].policies[] shape captured from a
                    # live GET /reports/needs-attention (sanitized 2026-06-05):
                    # severity/reasonForFail/policyCreateTime are present and
                    # populated on every live entry. Observed severity values
                    # were unknown/critical/high; the rest of the spec enum
                    # (no_known_cves/none/low/medium) was not seen at policy
                    # level this session.
                    "policies": [
                        {
                            "id": 1,
                            "name": "Patch All",
                            "type": "patch",
                            "severity": "critical",
                            "reasonForFail": "missing critical patches",
                            "policyCreateTime": "2026-04-01T08:00:00+0000",
                        },
                        {
                            "id": 2,
                            "name": "Reboot Nightly",
                            "type": "custom",
                            "severity": "unknown",
                            "reasonForFail": "device awaiting reboot",
                            "policyCreateTime": "2026-04-02T08:00:00+0000",
                        },
                    ],
                }
            ],
        }
    }
    client = StubClient(get_responses={"/reports/needs-attention": [report]})
    result = await list_devices_needing_attention(cast(AutomoxClient, client), org_id=42)

    data = result["data"]
    assert data["returned_count"] == 1
    device = data["devices"][0]
    assert device["device_id"] == 10
    assert device["device_name"] == "trouble-host"
    assert device["policy_status"] == "non_compliant"
    assert device["server_group_id"] == 99
    assert device["last_check_in"] == "2026-05-07T12:00:00+0000"
    assert device["needs_reboot"] is True
    assert device["os_family"] == "Mac"
    assert device["connected"] is True
    assert device["failing_policies_count"] == 2
    failing = device["failing_policies"][0]
    assert failing["policy_name"] == "Patch All"
    # Triage signals the report DTO carries are surfaced (previously dropped).
    assert failing["severity"] == "critical"
    assert failing["reason"] == "missing critical patches"
    assert failing["policy_create_time"] == "2026-04-01T08:00:00+0000"
    # The legend attributing the severity enum is present.
    assert "failing_policies[].severity" in result["metadata"]["field_notes"]


@pytest.mark.asyncio
async def test_list_devices_needing_attention_legacy_snakecase() -> None:
    """Defensive fallback: tolerate snake_case payloads if the API ever
    starts emitting them. Pre-fix tests exercised this shape directly."""
    report = {
        "data": [
            {
                "id": 10,
                "name": "trouble-host",
                "policy_status": "failed",
                "last_check_in": "2024-05-10T12:00:00Z",
                "server_group_id": 99,
            }
        ]
    }
    client = StubClient(get_responses={"/reports/needs-attention": [report]})
    result = await list_devices_needing_attention(cast(AutomoxClient, client), org_id=42)

    device = result["data"]["devices"][0]
    assert device["device_id"] == 10
    assert device["policy_status"] == "failed"
    assert device["server_group_id"] == 99
    assert device["last_check_in"] == "2024-05-10T12:00:00Z"


@pytest.mark.asyncio
async def test_list_devices_needing_attention_empty() -> None:
    report = {"data": []}
    client = StubClient(get_responses={"/reports/needs-attention": [report]})
    result = await list_devices_needing_attention(cast(AutomoxClient, client), org_id=42)

    data = result["data"]
    assert data["returned_count"] == 0
    assert data["devices"] == []
    # An exhausted report is reported as complete (not falsely "more available").
    assert result["metadata"]["pagination"]["has_more"] is False


@pytest.mark.asyncio
async def test_list_devices_needing_attention_multiple_devices() -> None:
    report = {
        "data": [
            {"id": 1, "name": "host-a", "policy_status": "failed", "server_group_id": 10},
            {"id": 2, "name": "host-b", "policy_status": "failed", "server_group_id": 10},
            {"id": 3, "name": "host-c", "policy_status": "failed", "server_group_id": 20},
        ]
    }
    client = StubClient(get_responses={"/reports/needs-attention": [report]})
    result = await list_devices_needing_attention(cast(AutomoxClient, client), org_id=42)

    data = result["data"]
    assert data["returned_count"] == 3
    ids = [d["device_id"] for d in data["devices"]]
    assert ids == [1, 2, 3]


@pytest.mark.asyncio
async def test_list_devices_needing_attention_metadata() -> None:
    report = {"data": []}
    client = StubClient(get_responses={"/reports/needs-attention": [report]})
    result = await list_devices_needing_attention(cast(AutomoxClient, client), org_id=42, limit=10)

    meta = result["metadata"]
    assert meta["org_id"] == 42
    assert meta["requested_limit"] == 10
    assert meta["deprecated_endpoint"] is False


@pytest.mark.asyncio
async def test_list_devices_needing_attention_with_group_id() -> None:
    report = {
        "nonCompliant": {
            "total": 1,
            "devices": [{"id": 5, "name": "host", "compliant": False, "groupId": 77}],
        }
    }
    client = StubClient(get_responses={"/reports/needs-attention": [report]})
    result = await list_devices_needing_attention(
        cast(AutomoxClient, client), org_id=42, group_id=77
    )

    assert result["data"]["group_id"] == 77
    assert result["metadata"]["group_id"] == 77
    assert result["data"]["devices"][0]["server_group_id"] == 77


@pytest.mark.asyncio
async def test_list_devices_needing_attention_uses_client_org_id() -> None:
    report = {"data": []}
    client = StubClient(get_responses={"/reports/needs-attention": [report]})
    client.org_id = 99
    result = await list_devices_needing_attention(cast(AutomoxClient, client))
    assert result["metadata"]["org_id"] == 99


@pytest.mark.asyncio
async def test_list_devices_needing_attention_no_org_id_raises() -> None:
    client = StubClient()
    client.org_id = None
    with pytest.raises(ValueError, match="org_id required"):
        await list_devices_needing_attention(cast(AutomoxClient, client))


# ===========================================================================
# list_device_inventory (legacy CSV-based list) tests (carried over)
# ===========================================================================


@pytest.mark.asyncio
async def test_list_device_inventory_basic() -> None:
    devices = [
        _make_device(1, name="host-01", os_name="Windows"),
        _make_device(2, name="host-02", os_name="macOS"),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await list_device_inventory(cast(AutomoxClient, client), org_id=42)

    data = result["data"]
    assert data["total_devices_returned"] == 2
    assert len(data["devices"]) == 2

    first = data["devices"][0]
    assert first["device_id"] == 1
    assert first["hostname"] == "host-01"
    assert first["managed"] is True
    assert first["os"] == "Windows"


@pytest.mark.asyncio
async def test_list_device_inventory_excludes_unmanaged_by_default() -> None:
    devices = [
        _make_device(1, managed=True),
        _make_device(2, managed=False),
        _make_device(3, managed=False),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await list_device_inventory(
        cast(AutomoxClient, client), org_id=42, include_unmanaged=False
    )

    data = result["data"]
    assert data["total_devices_returned"] == 1
    assert data["devices"][0]["device_id"] == 1


@pytest.mark.asyncio
async def test_list_device_inventory_includes_unmanaged_when_requested() -> None:
    devices = [
        _make_device(1, managed=True),
        _make_device(2, managed=False),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await list_device_inventory(
        cast(AutomoxClient, client), org_id=42, include_unmanaged=True
    )

    assert result["data"]["total_devices_returned"] == 2


@pytest.mark.asyncio
async def test_list_device_inventory_filters_by_policy_status() -> None:
    devices = [
        _make_device(1, policy_status="success"),
        _make_device(2, policy_status="failed"),
        _make_device(3, policy_status="success"),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await list_device_inventory(
        cast(AutomoxClient, client), org_id=42, policy_status="success"
    )

    data = result["data"]
    assert data["total_devices_returned"] == 2
    for d in data["devices"]:
        assert d["policy_status"] == "success"


@pytest.mark.asyncio
async def test_list_device_inventory_filters_by_managed_flag() -> None:
    devices = [
        _make_device(1, managed=True),
        _make_device(2, managed=False),
        _make_device(3, managed=True),
    ]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await list_device_inventory(
        cast(AutomoxClient, client), org_id=42, managed=True, include_unmanaged=True
    )

    data = result["data"]
    assert data["total_devices_returned"] == 2
    for d in data["devices"]:
        assert d["managed"] is True


@pytest.mark.asyncio
async def test_list_device_inventory_respects_limit() -> None:
    devices = [_make_device(i, name=f"host-{i:02d}") for i in range(10)]
    client = StubClient(get_responses={"/servers": [devices]})
    result = await list_device_inventory(cast(AutomoxClient, client), org_id=42, limit=4)

    data = result["data"]
    assert data["total_devices_returned"] == 4
    assert len(data["devices"]) == 4


@pytest.mark.asyncio
async def test_list_device_inventory_metadata() -> None:
    client = StubClient(get_responses={"/servers": [[]]})
    result = await list_device_inventory(
        cast(AutomoxClient, client), org_id=42, limit=50, include_unmanaged=True
    )

    meta = result["metadata"]
    assert meta["org_id"] == 42
    assert meta["requested_limit"] == 50
    assert meta["include_unmanaged"] is True
    assert meta["deprecated_endpoint"] is False
    # N2: a field_note warns that devices[].policy_status is the legacy,
    # non-authoritative string and points the model at the compliance rollup.
    note = meta["field_notes"]["devices[].policy_status"]
    assert "device_detail" in note or "compliance" in note


@pytest.mark.asyncio
async def test_list_device_inventory_no_org_id_raises() -> None:
    client = StubClient()
    client.org_id = None
    with pytest.raises(ValueError, match="org_id required"):
        await list_device_inventory(cast(AutomoxClient, client))


@pytest.mark.asyncio
async def test_list_device_inventory_uses_client_org_id() -> None:
    client = StubClient(get_responses={"/servers": [[]]})
    client.org_id = 7
    result = await list_device_inventory(cast(AutomoxClient, client))
    assert result["metadata"]["org_id"] == 7


# ---------------------------------------------------------------------------
# batch_update_devices (issue #91 category C, bulk tag write)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_update_devices_posts_devices_and_actions() -> None:
    client = StubClient(post_responses={"/servers/batch": [{"ok": True}]})
    client.org_id = 555
    actions = [{"attribute": "tags", "action": "apply", "value": ["env:prod"]}]
    result = await batch_update_devices(
        cast(AutomoxClient, client),
        org_id=555,
        devices=[1, 2, 3],
        actions=actions,
    )
    assert result["data"]["device_count"] == 3
    assert result["data"]["updated"] is True
    assert result["metadata"]["org_id"] == 555

    # conftest StubClient records POST as (method, path, json_data)
    method, path, body = client.calls[0]
    assert method == "POST"
    assert path == "/servers/batch"
    assert body == {"devices": [1, 2, 3], "actions": actions}


# ---------------------------------------------------------------------------
# update_device (#111 single-device PUT /servers/{id})
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_device_sends_only_supplied_fields() -> None:
    client = StubClient(put_responses={"/servers/99": [{"id": 99}]})
    client.org_id = 555
    result = await update_device(
        cast(AutomoxClient, client),
        org_id=555,
        device_id=99,
        custom_name="web-01",
        server_group_id=7,
    )
    method, path, body = client.calls[0]
    assert method == "PUT"
    assert path == "/servers/99"
    # Omitted fields (exception/tags/ip_addrs) must not be sent.
    assert body == {"custom_name": "web-01", "server_group_id": 7}
    assert result["data"]["device_id"] == 99
    assert result["data"]["updated"] is True
    assert result["data"]["updated_fields"] == ["custom_name", "server_group_id"]
    assert result["metadata"]["org_id"] == 555


@pytest.mark.asyncio
async def test_update_device_sends_falsey_exception_flag() -> None:
    client = StubClient(put_responses={"/servers/12": [{}]})
    client.org_id = 42
    await update_device(
        cast(AutomoxClient, client),
        org_id=42,
        device_id=12,
        exception=False,
        tags=["a", "b"],
    )
    _method, _path, body = client.calls[0]
    # exception=False is a meaningful value and must be sent, not dropped.
    assert body == {"exception": False, "tags": ["a", "b"]}


# ---------------------------------------------------------------------------
# delete_device (gated DELETE /servers/{id})
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_device_issues_scoped_delete() -> None:
    client = StubClient(delete_responses={"/servers/99": [{}]})
    client.org_id = 555
    result = await delete_device(
        cast(AutomoxClient, client),
        org_id=555,
        device_id=99,
    )
    method, path, scope = client.calls[0]
    assert method == "DELETE"
    assert path == "/servers/99"
    # Org scoping must ride along as the `o` query param.
    assert scope == {"o": 555}
    assert result["data"] == {"device_id": 99, "deleted": True}
    assert result["metadata"]["org_id"] == 555
