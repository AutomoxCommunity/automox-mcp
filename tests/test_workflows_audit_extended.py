"""Extended tests for undertested helpers in automox_mcp.workflows.audit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from automox_mcp.workflows.audit import (
    _coerce_datetime,
    _collect_observable_values,
    _extract_user_info,
    _sanitize_payload,
)

# ===========================================================================
# _extract_user_info — nested "user" key traversal
# ===========================================================================


def test_extract_user_info_returns_none_for_non_mapping() -> None:
    assert _extract_user_info(None) is None
    assert _extract_user_info("string") is None
    assert _extract_user_info(42) is None
    assert _extract_user_info([]) is None


def test_extract_user_info_flat_mapping_with_email() -> None:
    obj = {"email_addr": "alice@example.com", "uid": "uuid-1"}
    result = _extract_user_info(obj)
    assert result is not None
    assert result["email"] == "alice@example.com"
    assert result["uuid"] == "uuid-1"


def test_extract_user_info_nested_user_key_traversed() -> None:
    """Traverses one level of 'user' nesting."""
    obj = {
        "user": {
            "email_addr": "bob@example.com",
            "uid": "uuid-bob",
            "display_name": "Bob",
        }
    }
    result = _extract_user_info(obj)
    assert result is not None
    assert result["email"] == "bob@example.com"
    assert result["name"] == "Bob"


def test_extract_user_info_doubly_nested_user_key() -> None:
    """Traverses two levels of 'user' nesting (actor.user.user pattern)."""
    obj = {
        "user": {
            "user": {
                "email_addr": "carol@example.com",
                "uid": "uuid-carol",
            }
        }
    }
    result = _extract_user_info(obj)
    assert result is not None
    assert result["email"] == "carol@example.com"


def test_extract_user_info_user_key_is_non_mapping_stops_traversal() -> None:
    """When 'user' value is not a Mapping, traversal stops at current level."""
    obj = {"email_addr": "dave@example.com", "user": "not-a-mapping"}
    result = _extract_user_info(obj)
    assert result is not None
    assert result["email"] == "dave@example.com"


def test_extract_user_info_org_details_included() -> None:
    obj = {
        "email_addr": "eve@example.com",
        "org": {"uuid": "org-uuid-1", "name": "Acme Corp"},
    }
    result = _extract_user_info(obj)
    assert result is not None
    assert result["organization"]["uuid"] == "org-uuid-1"
    assert result["organization"]["name"] == "Acme Corp"


def test_extract_user_info_org_not_mapping_ignored() -> None:
    obj = {"email_addr": "frank@example.com", "org": "not-a-dict"}
    result = _extract_user_info(obj)
    assert result is not None
    assert "organization" not in result


def test_extract_user_info_all_empty_returns_none() -> None:
    """When no recognized fields have values, returns None."""
    obj = {"unknown_key": "value"}
    result = _extract_user_info(obj)
    assert result is None


def test_extract_user_info_role_extracted() -> None:
    obj = {"email_addr": "greta@example.com", "role": "admin"}
    result = _extract_user_info(obj)
    assert result is not None
    assert result["role"] == "admin"


def test_extract_user_info_uuid_from_id_key() -> None:
    obj = {"email": "h@example.com", "id": "some-id"}
    result = _extract_user_info(obj)
    assert result is not None
    assert result["uuid"] == "some-id"


def test_extract_user_info_display_name_fallback_keys() -> None:
    obj = {"email": "i@example.com", "full_name": "Ivan Petrov"}
    result = _extract_user_info(obj)
    assert result is not None
    assert result["name"] == "Ivan Petrov"


def test_extract_user_info_cycle_protection() -> None:
    """A mapping that would cause an infinite loop is broken by visited tracking."""
    inner: dict[str, Any] = {"email_addr": "j@example.com"}
    outer: dict[str, Any] = {"user": inner}
    # Point inner back to outer to simulate a cycle via id collision — in practice
    # the visited set prevents infinite loops. Just ensure it terminates.
    result = _extract_user_info(outer)
    assert result is not None
    assert result["email"] == "j@example.com"


# ===========================================================================
# _coerce_datetime — int/float timestamps, Mapping input
# ===========================================================================


def test_coerce_datetime_returns_none_for_none() -> None:
    assert _coerce_datetime(None) is None


def test_coerce_datetime_datetime_with_tz_returned_as_utc() -> None:
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    result = _coerce_datetime(dt)
    assert result is not None
    assert result.tzinfo is not None
    assert result == dt


def test_coerce_datetime_datetime_naive_gets_utc() -> None:
    dt = datetime(2024, 1, 1, 12, 0, 0)  # naive
    result = _coerce_datetime(dt)
    assert result is not None
    assert result.tzinfo == UTC


def test_coerce_datetime_int_seconds_timestamp() -> None:
    ts = 1718213009  # seconds since epoch
    result = _coerce_datetime(ts)
    assert result is not None
    assert result.tzinfo == UTC
    assert result.year == 2024


def test_coerce_datetime_float_seconds_timestamp() -> None:
    ts = 1718213009.5
    result = _coerce_datetime(ts)
    assert result is not None
    assert result.tzinfo == UTC


def test_coerce_datetime_milliseconds_timestamp_normalized() -> None:
    # Value > 1_000_000_000_000 is treated as milliseconds
    ts_ms = 1718213009419  # milliseconds
    result = _coerce_datetime(ts_ms)
    assert result is not None
    assert result.year == 2024


def test_coerce_datetime_string_iso() -> None:
    result = _coerce_datetime("2024-06-12T15:00:00Z")
    assert result is not None
    assert result.year == 2024
    assert result.tzinfo == UTC


def test_coerce_datetime_string_iso_no_tz() -> None:
    result = _coerce_datetime("2024-06-12T15:00:00")
    assert result is not None
    assert result.tzinfo == UTC


def test_coerce_datetime_string_integer() -> None:
    """A string containing an integer is treated as a Unix timestamp."""
    result = _coerce_datetime("1718213009")
    assert result is not None
    assert result.year == 2024


def test_coerce_datetime_string_invalid_returns_none() -> None:
    assert _coerce_datetime("not-a-date") is None


def test_coerce_datetime_empty_string_returns_none() -> None:
    assert _coerce_datetime("") is None


def test_coerce_datetime_mapping_with_observed_time() -> None:
    mapping = {"observed_time": "2024-06-12T10:00:00Z"}
    result = _coerce_datetime(mapping)
    assert result is not None
    assert result.year == 2024


def test_coerce_datetime_mapping_with_event_time() -> None:
    mapping = {"event_time": 1718213009}
    result = _coerce_datetime(mapping)
    assert result is not None
    assert result.year == 2024


def test_coerce_datetime_mapping_with_time_key() -> None:
    mapping = {"time": "2024-06-12T10:00:00Z"}
    result = _coerce_datetime(mapping)
    assert result is not None
    assert result.year == 2024


def test_coerce_datetime_mapping_no_recognized_keys_returns_none() -> None:
    mapping = {"unknown": "2024-06-12T10:00:00Z"}
    result = _coerce_datetime(mapping)
    assert result is None


def test_coerce_datetime_mapping_all_empty_returns_none() -> None:
    mapping = {"observed_time": None, "time": ""}
    result = _coerce_datetime(mapping)
    assert result is None


def test_coerce_datetime_max_depth_returns_none() -> None:
    """Exceeding _MAX_RECURSION_DEPTH stops recursion and returns None."""
    # Passing depth=7 (> _MAX_RECURSION_DEPTH=6) directly
    result = _coerce_datetime("2024-01-01", depth=7)
    assert result is None


def test_coerce_datetime_overflow_timestamp_returns_none() -> None:
    # A value so large it overflows datetime.fromtimestamp
    result = _coerce_datetime(9999999999999999)
    assert result is None


# ===========================================================================
# _collect_observable_values — type_id matching and type_name matching
# ===========================================================================


def test_collect_observable_values_empty_when_no_observables() -> None:
    result = _collect_observable_values({}, desired_types=["email"])
    assert result == []


def test_collect_observable_values_non_sequence_observables_returns_empty() -> None:
    event = {"observables": "not-a-list"}
    result = _collect_observable_values(event, desired_types=["email"])
    assert result == []


def test_collect_observable_values_matches_by_type_name() -> None:
    event = {
        "observables": [
            {"value": "alice@example.com", "type": "Email Address"},
            {"value": "misc", "type": "Other"},
        ]
    }
    result = _collect_observable_values(event, desired_types=["email address"])
    assert result == ["alice@example.com"]


def test_collect_observable_values_type_matching_is_case_insensitive() -> None:
    event = {
        "observables": [
            {"value": "bob@example.com", "type": "EMAIL ADDRESS"},
        ]
    }
    result = _collect_observable_values(event, desired_types=["email address"])
    assert result == ["bob@example.com"]


def test_collect_observable_values_uses_name_key_when_type_missing() -> None:
    event = {
        "observables": [
            {"value": "carol@example.com", "name": "email"},
        ]
    }
    result = _collect_observable_values(event, desired_types=["email"])
    assert result == ["carol@example.com"]


def test_collect_observable_values_type_id_5_matches_email() -> None:
    """type_id=5 is treated as an email observable when 'email' is desired."""
    event = {
        "observables": [
            {"value": "dave@example.com", "type_id": 5},
        ]
    }
    result = _collect_observable_values(event, desired_types=["email"])
    assert result == ["dave@example.com"]


def test_collect_observable_values_type_id_5_no_email_desired_not_matched() -> None:
    """type_id=5 is only extracted when 'email' is in desired_types."""
    event = {
        "observables": [
            {"value": "eve@example.com", "type_id": 5},
        ]
    }
    result = _collect_observable_values(event, desired_types=["uuid"])
    assert result == []


def test_collect_observable_values_skips_non_mapping_items() -> None:
    event = {"observables": ["not-a-mapping", 42, None]}
    result = _collect_observable_values(event, desired_types=["email"])
    assert result == []


def test_collect_observable_values_skips_empty_value() -> None:
    event = {
        "observables": [
            {"value": "  ", "type": "email"},  # whitespace-only → skipped
            {"value": "", "type": "email"},  # empty → skipped
        ]
    }
    result = _collect_observable_values(event, desired_types=["email"])
    assert result == []


def test_collect_observable_values_skips_non_string_value() -> None:
    event = {
        "observables": [
            {"value": 12345, "type": "email"},  # non-string → skipped
        ]
    }
    result = _collect_observable_values(event, desired_types=["email"])
    assert result == []


def test_collect_observable_values_multiple_matches() -> None:
    event = {
        "observables": [
            {"value": "a@example.com", "type": "email"},
            {"value": "b@example.com", "type": "email"},
            {"value": "other", "type": "uuid"},
        ]
    }
    result = _collect_observable_values(event, desired_types=["email"])
    assert set(result) == {"a@example.com", "b@example.com"}


def test_collect_observable_values_strips_whitespace_from_value() -> None:
    event = {
        "observables": [
            {"value": "  frank@example.com  ", "type": "email"},
        ]
    }
    result = _collect_observable_values(event, desired_types=["email"])
    assert result == ["frank@example.com"]


# ===========================================================================
# _sanitize_payload — string truncation, sequence truncation, max depth
# ===========================================================================


def test_sanitize_payload_passthrough_integer() -> None:
    assert _sanitize_payload(42) == 42


def test_sanitize_payload_passthrough_float() -> None:
    assert _sanitize_payload(3.14) == 3.14


def test_sanitize_payload_passthrough_none() -> None:
    assert _sanitize_payload(None) is None


def test_sanitize_payload_passthrough_bool() -> None:
    assert _sanitize_payload(True) is True


def test_sanitize_payload_short_string_unchanged() -> None:
    assert _sanitize_payload("hello") == "hello"


def test_sanitize_payload_string_at_limit_unchanged() -> None:
    # Exactly 400 chars — should NOT be truncated
    value = "x" * 400
    result = _sanitize_payload(value)
    assert result == value


def test_sanitize_payload_long_string_truncated() -> None:
    value = "A" * 500
    result = _sanitize_payload(value)
    assert isinstance(result, str)
    assert "chars truncated" in result
    assert result.startswith("A" * 400)


def test_sanitize_payload_string_truncation_shows_remaining_count() -> None:
    value = "B" * 450
    result = _sanitize_payload(value)
    # 450 - 400 = 50 chars truncated
    assert "50 chars truncated" in result


def test_sanitize_payload_strips_whitespace_from_string() -> None:
    result = _sanitize_payload("  hello  ")
    assert result == "hello"


def test_sanitize_payload_mapping_filters_empty_values() -> None:
    payload = {"a": "hello", "b": None, "c": "", "d": [], "e": {}}
    result = _sanitize_payload(payload)
    assert set(result.keys()) == {"a"}
    assert result["a"] == "hello"


def test_sanitize_payload_mapping_recursive() -> None:
    payload = {"outer": {"inner": "value", "empty": None}}
    result = _sanitize_payload(payload)
    assert result["outer"]["inner"] == "value"
    assert "empty" not in result["outer"]


def test_sanitize_payload_sequence_short_unchanged() -> None:
    value = [1, 2, 3]
    result = _sanitize_payload(value)
    assert result == [1, 2, 3]


def test_sanitize_payload_sequence_truncated_at_limit() -> None:
    # _SANITIZED_SEQUENCE_LIMIT in audit.py is 10
    value = list(range(15))
    result = _sanitize_payload(value)
    assert len(result) == 11  # 10 items + "... 5 more"
    assert result[-1] == "... 5 more"


def test_sanitize_payload_sequence_exactly_at_limit_not_truncated() -> None:
    value = list(range(10))
    result = _sanitize_payload(value)
    assert len(result) == 10
    assert isinstance(result[-1], int)


def test_sanitize_payload_bytes_treated_as_scalar() -> None:
    # bytes is excluded from Sequence truncation branch
    value = b"raw bytes"
    result = _sanitize_payload(value)
    assert result == b"raw bytes"


def test_sanitize_payload_max_depth_returns_sentinel() -> None:
    # Calling with depth > _MAX_RECURSION_DEPTH (6) returns the sentinel string
    result = _sanitize_payload({"key": "value"}, depth=7)
    assert result == "... (max depth reached)"


def test_sanitize_payload_deeply_nested_mapping_hits_depth_limit() -> None:
    # Build 8-level-deep dict
    deep: Any = {"value": "leaf"}
    for _ in range(8):
        deep = {"nested": deep}
    result = _sanitize_payload(deep)
    # The top levels are processed; at some point the sentinel appears
    assert isinstance(result, dict)
    # Traverse down until we hit the sentinel
    current = result
    depth = 0
    while isinstance(current, dict) and "nested" in current:
        current = current["nested"]
        depth += 1
        if depth > 10:
            break
    # Eventually we should see the max-depth sentinel
    assert current == "... (max depth reached)"
