"""Policy create/update/delete workflows for Automox MCP."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from fastmcp.exceptions import ToolError

from ..client import AutomoxAPIError, AutomoxClient
from ..utils.response import require_org_id

logger = logging.getLogger(__name__)


_ALLOWED_POLICY_TYPES = {"patch", "custom", "required_software"}
_READ_ONLY_POLICY_FIELDS = {
    "id",
    "uuid",
    "create_time",
    "server_count",
    "status",
    "next_remediation",
    "policy_uuid",
    "account_id",
    "community_worklet_id",
    "community_worklet_uuid",
    "policy_template_id",
    "policy_template_uuid",
}
_OPERATION_CORE_KEYS = {"action", "policy", "policy_id", "merge_existing"}
_DAY_NAME_TO_BITMASK = {
    "sunday": 128,  # Bit 7 - Sunday is the high bit with trailing zero pattern
    "sun": 128,
    "monday": 2,  # Bit 1 - Bit 0 is the trailing zero (unused)
    "mon": 2,
    "tuesday": 4,  # Bit 2
    "tue": 4,
    "tues": 4,
    "wednesday": 8,  # Bit 3
    "wed": 8,
    "thursday": 16,  # Bit 4
    "thu": 16,
    "thur": 16,
    "thurs": 16,
    "friday": 32,  # Bit 5
    "fri": 32,
    "saturday": 64,  # Bit 6
    "sat": 64,
}
_DAY_INDEX_TO_NAME = {
    0: "sunday",
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
}
_BITMASK_TO_DAY_NAME = {
    128: "sunday",
    2: "monday",
    4: "tuesday",
    8: "wednesday",
    16: "thursday",
    32: "friday",
    64: "saturday",
}
_DAY_GROUP_ALIASES = {
    "weekday": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "weekend": ["saturday", "sunday"],
    "weekends": ["saturday", "sunday"],
    "all": [
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    ],
    "everyday": [
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    ],
}
_SCHEDULE_TIME_PATTERN = re.compile(r"^(\d{1,2})(?::(\d{2}))?$")


def normalize_policy_operations_input(raw_operations: Sequence[Any]) -> list[dict[str, Any]]:
    """Normalize loosely structured operations into the expected payload shape.

    This function helps handle common mistakes and variations in the input format,
    particularly the common error of using 'operation' instead of 'action'.
    """

    normalized: list[dict[str, Any]] = []
    for index, raw_op in enumerate(raw_operations):
        if not isinstance(raw_op, Mapping):
            raise ValueError(
                f"Operation at index {index} must be an object. "
                f"Example: {{'action': 'create', 'policy': {{'name': '...', ...}}}}"
            )

        op_dict = dict(raw_op)

        # Check for common mistake: using 'operation' instead of 'action'
        if "operation" in op_dict and "action" not in op_dict:
            operation_value = str(op_dict.pop("operation"))
            # Sanitize user-provided value before reflecting in error message
            safe_value = operation_value[:50].replace("\n", " ").replace("\r", " ")
            if safe_value not in ("create", "update"):
                safe_value = repr(safe_value)
            raise ToolError(
                f"Operation at index {index} uses 'operation' field but should use "
                f"'action' field instead. "
                f"Found: 'operation': {safe_value}. "
                f"Change to: 'action': 'create' or 'action': 'update'. "
                f"\n\nCorrect format:\n"
                f"{{\n"
                f'  "action": "create",\n'
                f'  "policy": {{\n'
                f'    "name": "Policy Name",\n'
                f'    "policy_type_name": "patch",\n'
                f'    "configuration": {{ ... }},\n'
                f'    "schedule": {{ "days": ["monday"], "time": "02:00" }}\n'
                f"  }}\n"
                f"}}"
            )

        # Ensure 'action' field exists
        if "action" not in op_dict:
            raise ToolError(
                f"Operation at index {index} is missing required 'action' field. "
                f"Must be either 'create' or 'update'. "
                f"\n\nExample for create:\n"
                f"{{\n"
                f'  "action": "create",\n'
                f'  "policy": {{ ... }}\n'
                f"}}\n\n"
                f"Example for update:\n"
                f"{{\n"
                f'  "action": "update",\n'
                f'  "policy_id": 12345,\n'
                f'  "policy": {{ ... }}\n'
                f"}}"
            )

        policy_payload = op_dict.get("policy")
        if not isinstance(policy_payload, Mapping):
            # Lift non-operation keys into the policy payload
            policy_payload = {
                key: value
                for key, value in list(op_dict.items())
                if key not in _OPERATION_CORE_KEYS
            }
            for key in list(policy_payload.keys()):
                op_dict.pop(key, None)
            op_dict["policy"] = policy_payload
        else:
            op_dict["policy"] = dict(policy_payload)

        policy = op_dict["policy"]

        # Normalize policy_type field names
        if "policy_type" in policy and "policy_type_name" not in policy:
            policy["policy_type_name"] = policy.pop("policy_type")
        if "policyType" in policy and "policy_type_name" not in policy:
            policy["policy_type_name"] = policy.pop("policyType")

        # Auto-fix configuration dict
        if "configuration" in policy and isinstance(policy["configuration"], Mapping):
            config = dict(policy["configuration"])

            # Fix common configuration field name mistakes
            if "software_name" in config and "filters" not in config:
                # Claude used "software_name" instead of "filters"
                config["filters"] = [f"*{config.pop('software_name')}*"]

            if "filter_type" in config:
                # Remove filter_type - it's not a valid field
                config.pop("filter_type")

            policy["configuration"] = config

        # Auto-fix device_filters structure
        if "device_filters" in policy and isinstance(policy["device_filters"], list):
            filters = policy["device_filters"]
            if filters and isinstance(filters[0], Mapping) and "device_id" in filters[0]:
                # Claude provided [{"device_id": 123}, ...] instead of proper server_groups
                # Extract device IDs and add note
                device_ids = [f["device_id"] for f in filters if "device_id" in f]
                policy.pop("device_filters")
                # Store as note since device-level targeting requires proper group setup
                if "notes" not in policy:
                    policy["notes"] = ""
                policy["notes"] += f" Target device IDs: {device_ids}"

        # Ensure configuration exists for patch policies
        if policy.get("policy_type_name") == "patch" and "configuration" not in policy:
            raise ToolError(
                f"Operation at index {index}: Patch policies require a 'configuration' block. "
                f"Example: {{'configuration': {{'patch_rule': 'filter', "
                f"'filters': ['*Google Chrome*']}}}}"
            )

        normalized.append(op_dict)

    return normalized


def _normalize_policy_type(value: str | None) -> str:
    """Normalize policy type names and validate the Automox enum."""
    if value is None:
        raise ValueError("policy_type_name is required for policy create/update operations.")
    normalized = value.strip().lower()
    if normalized not in _ALLOWED_POLICY_TYPES:
        allowed = ", ".join(sorted(_ALLOWED_POLICY_TYPES))
        raise ValueError(f"Unsupported policy_type_name '{value}'. Expected one of: {allowed}.")
    return normalized


def _sanitize_policy_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strip Automox response-only fields and deep copy mutable values."""
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _READ_ONLY_POLICY_FIELDS:
            continue
        sanitized[key] = deepcopy(value)
    return sanitized


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


def _normalize_filters(filters: Sequence[Any], *, exact: bool = False) -> list[str]:
    normalized: list[str] = []
    for item in filters:
        text = str(item).strip()
        if not text:
            continue
        if exact or text.startswith("*") or text.endswith("*"):
            normalized.append(text)
        else:
            normalized.append(f"*{text}*")
    return normalized


def _normalize_schedule_time(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _SCHEDULE_TIME_PATTERN.fullmatch(text)
    if not match:
        raise ValueError(
            "schedule time must be provided in HH:MM (24-hour) format. Examples: '02:00', '18:30'."
        )
    hours = int(match.group(1))
    minutes = int(match.group(2) or "0")
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError("schedule time must use a valid 24-hour clock (00:00 through 23:59).")
    return f"{hours:02d}:{minutes:02d}"


def _expand_day_alias(value: str) -> list[str]:
    alias = value.lower()
    if alias in _DAY_GROUP_ALIASES:
        return _DAY_GROUP_ALIASES[alias]
    if alias in _DAY_NAME_TO_BITMASK:
        # Map back from bitmask to day name using the reverse lookup
        bitmask = _DAY_NAME_TO_BITMASK[alias]
        day_name = _BITMASK_TO_DAY_NAME.get(bitmask)
        if day_name:
            return [day_name]
    raise ValueError(
        f"Unrecognized day name '{value}'. Use values like 'monday', 'wed', "
        "'weekdays', or provide numeric day indexes (0-6 or 1-7)."
    )


def _normalize_schedule_days_input(value: Any) -> int | None:
    if value is None:
        return None
    items = _ensure_list(value)
    if not items:
        return None

    bitmask = 0
    for item in items:
        if isinstance(item, Mapping):
            raise ValueError(
                "schedule.days must be a list of names or integers, not nested objects."
            )
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            if text.isdigit():
                item = int(text)
            else:
                for expanded in _expand_day_alias(text):
                    normalized_bit = _DAY_NAME_TO_BITMASK[expanded]
                    bitmask |= normalized_bit
                continue
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            # Accept 0-6 only (Sunday=0 through Saturday=6).
            # Previously accepted 1-7, but the ambiguous mapping (is 1=Monday
            # or 1=Sunday?) caused incorrect schedules.
            integer_value = int(item)
            if integer_value not in range(0, 7):
                raise ValueError(
                    "Numeric schedule days must be in the range 0-6 "
                    "(0=Sunday, 1=Monday, ..., 6=Saturday). "
                    "Use day names (e.g., 'monday') for unambiguous input."
                )
            index = integer_value
            day_name = _DAY_INDEX_TO_NAME[index]
            bitmask |= _DAY_NAME_TO_BITMASK[day_name]
            continue
        raise ValueError(
            "schedule.days must contain day names (e.g., 'monday') or numeric day indexes."
        )

    return bitmask or None


def _apply_schedule_aliases(payload: dict[str, Any]) -> list[str]:
    """Normalize friendly schedule helpers into Automox bitmask fields."""
    warnings: list[str] = []
    schedule_block = payload.pop("schedule", None)
    if not isinstance(schedule_block, Mapping):
        return warnings

    schedule = dict(schedule_block)
    days_value = schedule.pop("days", schedule.pop("day", None))
    if days_value is not None:
        payload["schedule_days"] = _normalize_schedule_days_input(days_value)

    time_value = schedule.pop("time", None)
    if time_value is not None:
        payload["schedule_time"] = _normalize_schedule_time(time_value)

    timezone_value = schedule.pop("timezone", schedule.pop("tz", None))
    if timezone_value is not None and payload.get("scheduled_timezone") is None:
        payload["scheduled_timezone"] = str(timezone_value)
        payload.setdefault("use_scheduled_timezone", True)

    frequency = schedule.pop("frequency", None)
    if frequency:
        warnings.append(
            f"Ignored schedule.frequency='{frequency}'. Automox policies expect explicit "
            "bitmask fields (schedule_days/schedule_weeks_of_month/schedule_months)."
        )

    # Surface any leftover keys so the caller knows they were ignored.
    if schedule:
        warnings.append(
            "Ignored unrecognized keys in schedule block: " + ", ".join(sorted(schedule.keys()))
        )

    return warnings


def _normalize_device_filters(config: dict[str, Any]) -> None:
    filters = config.get("device_filters")
    if not filters:
        return
    if isinstance(filters, Mapping):
        return
    if not isinstance(filters, Sequence) or isinstance(filters, (str, bytes)):
        raise ValueError(
            "configuration.device_filters must be a list of filter definitions or device IDs."
        )

    filter_values: list[int] = []
    for item in filters:
        if isinstance(item, Mapping):
            return  # Already structured filter definitions
        if isinstance(item, bool):
            raise ValueError(
                "configuration.device_filters cannot include boolean values. "
                "Provide Automox device IDs or full filter objects."
            )
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            integer_value = int(item)
            if integer_value <= 0:
                raise ValueError("Device filter IDs must be positive integers.")
            filter_values.append(integer_value)
            continue
        if isinstance(item, str):
            stripped = item.strip()
            if not stripped:
                continue
            if not stripped.isdigit():
                raise ValueError(f"Device filter value '{item}' is not a valid Automox device ID.")
            filter_values.append(int(stripped))
            continue
        raise ValueError(
            "configuration.device_filters must contain device IDs (ints/strings) "
            "or full filter definitions."
        )

    if not filter_values:
        return

    config["device_filters"] = [
        {
            "op": "in",
            "field": "device-id",
            "value": filter_values,
        }
    ]
    config["device_filters_enabled"] = True


def _validate_schedule_days(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("schedule_days must be an integer bitmask, not a boolean.")
    error_msg = (
        "schedule_days must be an integer bitmask aligned with Automox scheduling requirements."
    )
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if not text.isdigit():
            raise ValueError(error_msg)
        value = int(text)
    if not isinstance(value, int):
        raise ValueError(error_msg)
    if value < 0:
        raise ValueError("schedule_days must be non-negative.")
    return value


def _coerce_policy_payload_defaults(payload: dict[str, Any]) -> list[str]:
    """Apply Automox-friendly defaults and helper transformations."""

    warnings = _apply_schedule_aliases(payload)

    payload.setdefault("notes", "")
    payload.setdefault("server_groups", [])
    payload.setdefault("use_scheduled_timezone", False)

    # Initialize schedule fields to 0 (unscheduled) - will be updated later if needed
    payload.setdefault("schedule_weeks_of_month", 0)
    payload.setdefault("schedule_months", 0)

    config = payload.get("configuration")
    if not isinstance(config, Mapping):
        return warnings

    config_dict = dict(config)
    payload["configuration"] = config_dict

    policy_type = payload.get("policy_type_name")

    # Auto-fix: Move patch policy fields into configuration
    if policy_type == "patch":
        # Move auto_patch, auto_reboot, notify_user, notify_reboot_user
        for field_name in ["auto_patch", "auto_reboot", "notify_user", "notify_reboot_user"]:
            if field_name in payload:
                field_value = payload.pop(field_name)
                if field_name not in config_dict:
                    config_dict[field_name] = field_value
                    warnings.append(
                        f"Moved '{field_name}' from top-level into configuration block "
                        f"for patch policy"
                    )

        # Move filter shortcuts (filter_name, filter_names) into configuration
        for field_name in ["filter_name", "filter_names"]:
            if field_name in payload:
                field_value = payload.pop(field_name)
                if field_name not in config_dict:
                    config_dict[field_name] = field_value
                    warnings.append(
                        f"Moved '{field_name}' from top-level into configuration block "
                        f"for patch policy"
                    )

    if policy_type == "patch":
        # Auto-detect patch_rule based on presence of filter fields
        has_filter_fields = bool(
            config_dict.get("filters")
            or config_dict.get("filter_name")
            or config_dict.get("filter_names")
        )
        patch_rule = config_dict.get("patch_rule")
        if not patch_rule:
            # Default to "filter" if filter fields present, otherwise "all"
            patch_rule = "filter" if has_filter_fields else "all"
            if has_filter_fields:
                warnings.append(
                    "Auto-set patch_rule='filter' because "
                    "filter_name/filter_names/filters was provided"
                )
        patch_rule = patch_rule.strip().lower()
        config_dict["patch_rule"] = patch_rule

        if patch_rule == "filter":
            available_filters = _ensure_list(config_dict.get("filters"))
            # Support convenience keys filter_name / filter_names
            available_filters.extend(_ensure_list(config_dict.pop("filter_name", None)))
            available_filters.extend(_ensure_list(config_dict.pop("filter_names", None)))
            normalized_filters = _normalize_filters(available_filters)
            if not normalized_filters:
                raise ValueError(
                    "Patch policies using patch_rule='filter' require at least one "
                    "filter pattern. Provide configuration.filters (e.g., "
                    "['*Google Chrome*']) or filter_name/filter_names."
                )
            config_dict["filters"] = normalized_filters
            filter_type_value = config_dict.get("filter_type")
            config_dict["filter_type"] = (
                filter_type_value.strip().lower()
                if isinstance(filter_type_value, str) and filter_type_value.strip()
                else "include"
            )
        else:
            config_dict.pop("filter_name", None)
            config_dict.pop("filter_names", None)

        _normalize_device_filters(config_dict)
        if "device_filters_enabled" not in config_dict:
            config_dict["device_filters_enabled"] = bool(config_dict.get("device_filters"))
    else:
        _normalize_device_filters(config_dict)

    # Clean up empty scheduled_timezone when not needed
    if not payload["use_scheduled_timezone"]:
        payload.pop("scheduled_timezone", None)

    validated_schedule_days = _validate_schedule_days(payload.get("schedule_days"))
    if validated_schedule_days is not None:
        payload["schedule_days"] = validated_schedule_days

    # Automox scheduling requirement: If schedule_days is set (policy has a schedule),
    # then BOTH schedule_weeks_of_month and schedule_months must also be set.
    # Auto-fix by setting sensible defaults if the user provided days but not weeks/months.
    schedule_days_value = payload.get("schedule_days")
    has_schedule = isinstance(schedule_days_value, int) and schedule_days_value > 0

    if has_schedule:
        # Set default for schedule_weeks_of_month if not provided or is 0
        if payload.get("schedule_weeks_of_month", 0) == 0:
            payload["schedule_weeks_of_month"] = 62  # All 5 weeks with trailing zero (111110 = 62)
            warnings.append(
                "Auto-set schedule_weeks_of_month=62 (all 5 weeks) because "
                "schedule_days was provided. Automox requires DAYS, WEEKS, and MONTHS "
                "to all be set for scheduled policies."
            )

        # Set default for schedule_months if not provided or is 0
        if payload.get("schedule_months", 0) == 0:
            payload["schedule_months"] = (
                8190  # All 12 months with trailing zero (1111111111110 = 8190)
            )
            warnings.append(
                "Auto-set schedule_months=8190 (all 12 months) because schedule_days was provided. "
                "Automox requires DAYS, WEEKS, and MONTHS to all be set for scheduled policies."
            )

    return warnings


_MAX_MERGE_DEPTH = 10


def _deep_merge_dicts(
    base: Mapping[str, Any],
    overrides: Mapping[str, Any],
    *,
    _depth: int = 0,
) -> dict[str, Any]:
    """Recursively merge dictionaries, preferring override values.

    V-152: Capped at ``_MAX_MERGE_DEPTH`` levels to prevent stack overflow
    from adversarially nested configuration payloads.
    """
    merged = dict(base)
    for key, override_value in overrides.items():
        base_value = merged.get(key)
        if (
            isinstance(base_value, Mapping)
            and isinstance(override_value, Mapping)
            and _depth < _MAX_MERGE_DEPTH
        ):
            merged[key] = _deep_merge_dicts(base_value, override_value, _depth=_depth + 1)
        else:
            merged[key] = deepcopy(override_value)
    return merged


def _extract_policy_id_from_response(response: Any) -> int | None:
    """Attempt to pull a policy identifier from an Automox API response."""
    if not isinstance(response, Mapping):
        return None
    for candidate_key in ("id", "policy_id"):
        candidate = response.get(candidate_key)
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str):
            try:
                return int(candidate)
            except ValueError:
                continue
    return None


def _ensure_required_policy_fields(
    payload: Mapping[str, Any],
    *,
    require_all: bool,
) -> None:
    """Validate required Automox fields are present before submission."""
    missing = []
    for field in (
        "name",
        "policy_type_name",
        "configuration",
        "schedule_days",
        "schedule_time",
        "use_scheduled_timezone",
        "server_groups",
        "notes",
    ):
        if payload.get(field) is None:
            missing.append(field)
    if missing and require_all:
        message = "Policy payload missing required fields: " + ", ".join(sorted(missing))
        hints: list[str] = []
        if "schedule_days" in missing or "schedule_time" in missing:
            hints.append(
                "Provide schedule_days (Automox bitmask) and schedule_time (HH:MM) "
                "or supply a 'schedule' helper block like "
                "{'schedule': {'days': ['monday', 'wednesday'], 'time': '02:00'}}."
            )
        if "configuration" in missing:
            hints.append(
                "Patch policies require a configuration object. For example: "
                "{'configuration': {'patch_rule': 'filter', 'filters': ['*Google Chrome*']}}."
            )
        if hints:
            message = f"{message}. Guidance: " + " ".join(hints)
        raise ValueError(message)
    configuration = payload.get("configuration")
    if configuration is not None and not isinstance(configuration, Mapping):
        raise ValueError("configuration must be an object matching Automox expectations.")
    server_groups = payload.get("server_groups")
    if server_groups is not None:
        if not isinstance(server_groups, Sequence) or isinstance(server_groups, (str, bytes)):
            raise ValueError("server_groups must be a list of Automox server group IDs.")


def _prepare_policy_payload_for_create(
    policy_data: Mapping[str, Any],
    *,
    org_id: int,
) -> tuple[dict[str, Any], list[str]]:
    """Build the payload for creating a policy."""
    payload = _sanitize_policy_payload(policy_data)
    payload["organization_id"] = org_id
    payload["policy_type_name"] = _normalize_policy_type(payload.get("policy_type_name"))
    warnings = _coerce_policy_payload_defaults(payload)
    _ensure_required_policy_fields(payload, require_all=True)
    return payload, warnings


async def _prepare_policy_payload_for_update(
    client: AutomoxClient,
    policy_id: int,
    policy_data: Mapping[str, Any],
    *,
    org_id: int,
    merge_existing: bool,
) -> tuple[dict[str, Any], Mapping[str, Any] | None, list[str]]:
    """Build the payload for updating a policy and return the latest Automox copy."""
    existing_original: Mapping[str, Any] | None = None
    existing_sanitized: Mapping[str, Any] | None = None
    if merge_existing:
        existing = await client.get(f"/policies/{policy_id}", params={"o": org_id})
        if not isinstance(existing, Mapping):
            raise ValueError(f"Failed to retrieve policy {policy_id} for update.")
        existing_original = existing
        existing_sanitized = _sanitize_policy_payload(existing)
        base = existing_sanitized
    else:
        base = {}
    overrides = _sanitize_policy_payload(policy_data)
    if not overrides and not base:
        raise ValueError("No policy fields provided for update.")
    payload = _deep_merge_dicts(base, overrides)

    if "policy_type_name" in payload and payload["policy_type_name"] is not None:
        payload["policy_type_name"] = _normalize_policy_type(payload["policy_type_name"])
    elif existing_sanitized and existing_sanitized.get("policy_type_name"):
        payload["policy_type_name"] = _normalize_policy_type(
            str(existing_sanitized.get("policy_type_name"))
        )
    else:
        raise ValueError(
            "policy_type_name is required when updating a policy without merge_existing."
        )

    if ("name" not in payload or payload["name"] is None) and existing_sanitized:
        payload["name"] = existing_sanitized.get("name")

    payload["organization_id"] = org_id
    if existing_sanitized:
        payload.setdefault("notes", existing_sanitized.get("notes"))
        payload.setdefault("server_groups", existing_sanitized.get("server_groups"))
        payload.setdefault(
            "schedule_weeks_of_month", existing_sanitized.get("schedule_weeks_of_month")
        )
        payload.setdefault("schedule_months", existing_sanitized.get("schedule_months"))
        payload.setdefault(
            "use_scheduled_timezone", existing_sanitized.get("use_scheduled_timezone")
        )
        if existing_sanitized.get("use_scheduled_timezone"):
            payload.setdefault("scheduled_timezone", existing_sanitized.get("scheduled_timezone"))

    warnings = _coerce_policy_payload_defaults(payload)
    payload["id"] = policy_id

    require_all = not merge_existing
    _ensure_required_policy_fields(payload, require_all=require_all)
    return payload, existing_original, warnings


async def apply_policy_changes(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    operations: Sequence[Mapping[str, Any]],
    preview: bool = False,
) -> dict[str, Any]:
    """Create or update Automox policies from structured change requests."""

    resolved_org_id = require_org_id(client, org_id)

    normalized_operations = normalize_policy_operations_input(operations)
    results: list[dict[str, Any]] = []

    for index, operation in enumerate(normalized_operations):
        action = str(operation.get("action") or "").strip().lower()
        if action not in {"create", "update"}:
            raise ValueError(
                f"Operation at index {index} has unsupported action '{operation.get('action')}'."
            )

        raw_policy = operation.get("policy")
        if not isinstance(raw_policy, Mapping):
            raise ValueError(f"Operation at index {index} is missing a 'policy' object.")

        entry: dict[str, Any] = {
            "index": index,
            "action": action,
        }

        if action == "create":
            payload, payload_warnings = _prepare_policy_payload_for_create(
                raw_policy, org_id=resolved_org_id
            )
            entry["policy_name"] = payload.get("name")
            entry["policy_type_name"] = payload.get("policy_type_name")
            entry["request"] = {
                "method": "POST",
                "path": "/policies",
                "params": {"o": resolved_org_id},
                "body": payload,
            }
            if payload_warnings:
                entry.setdefault("warnings", []).extend(payload_warnings)

            if preview:
                entry["status"] = "preview"
            else:
                response_data = await client.post(
                    "/policies",
                    json_data=payload,
                    params={"o": resolved_org_id},
                )
                entry["status"] = "created"
                entry["response"] = response_data
                policy_id = _extract_policy_id_from_response(response_data)
                if policy_id is not None:
                    entry["policy_id"] = policy_id
                    try:
                        latest_policy = await client.get(
                            f"/policies/{policy_id}",
                            params={"o": resolved_org_id},
                        )
                        if isinstance(latest_policy, Mapping):
                            entry["policy"] = latest_policy
                    except (AutomoxAPIError, ValueError, TypeError, KeyError) as exc:
                        logger.debug("Failed to fetch created policy %s: %s", policy_id, exc)
                        entry.setdefault("warnings", []).append(
                            f"Created policy {policy_id}, but failed to retrieve latest state."
                        )
                else:
                    entry["policy_id"] = None

        else:  # update
            policy_id_value = operation.get("policy_id")
            if policy_id_value is None:
                raise ValueError(f"Operation at index {index} requires policy_id for updates.")
            try:
                policy_id = int(policy_id_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Operation at index {index} has invalid policy_id '{policy_id_value}'."
                ) from exc

            merge_flag_raw = operation.get("merge_existing")
            merge_existing = True if merge_flag_raw is None else bool(merge_flag_raw)

            payload, previous_policy, payload_warnings = await _prepare_policy_payload_for_update(
                client,
                policy_id,
                raw_policy,
                org_id=resolved_org_id,
                merge_existing=merge_existing,
            )

            entry["policy_id"] = policy_id
            entry["policy_name"] = payload.get("name")
            entry["policy_type_name"] = payload.get("policy_type_name")
            if previous_policy is not None:
                entry["previous_policy"] = previous_policy
            if payload_warnings:
                entry.setdefault("warnings", []).extend(payload_warnings)

            entry["request"] = {
                "method": "PUT",
                "path": f"/policies/{policy_id}",
                "params": {"o": resolved_org_id},
                "body": payload,
            }

            if preview:
                entry["status"] = "preview"
            else:
                response_data = await client.put(
                    f"/policies/{policy_id}",
                    json_data=payload,
                    params={"o": resolved_org_id},
                )
                entry["status"] = "updated"
                entry["response"] = response_data
                try:
                    latest_policy = await client.get(
                        f"/policies/{policy_id}",
                        params={"o": resolved_org_id},
                    )
                    if isinstance(latest_policy, Mapping):
                        entry["policy"] = latest_policy
                except (AutomoxAPIError, ValueError, TypeError, KeyError) as exc:
                    logger.debug("Failed to fetch updated policy %s: %s", policy_id, exc)
                    entry.setdefault("warnings", []).append(
                        f"Updated policy {policy_id}, but failed to retrieve latest state."
                    )

        results.append(entry)

    data = {
        "operations": results,
        "preview": preview,
    }
    metadata = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "operation_count": len(results),
        "preview": preview,
    }
    return {
        "data": data,
        "metadata": metadata,
    }


async def resolve_patch_approval(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    approval_id: int,
    decision: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Approve or reject an Automox patch approval request."""

    decision_normalized = decision.lower()
    decision_map = {
        "approve": "approved",
        "approved": "approved",
        "accept": "approved",
        "deny": "rejected",
        "reject": "rejected",
        "rejected": "rejected",
    }
    status_value = decision_map.get(decision_normalized)
    if not status_value:
        raise ValueError(f"Unsupported decision '{decision}'. Use approve/deny or approve/reject.")

    resolved_org_id = require_org_id(client, org_id)

    body = {"status": status_value}
    if notes:
        body["notes"] = notes

    params = {"o": resolved_org_id}
    response_data = await client.put(f"/approvals/{approval_id}", json_data=body, params=params)

    data = {
        "approval_id": approval_id,
        "decision": status_value,
        "notes": notes,
        "response": response_data,
    }

    metadata = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
    }

    return {
        "data": data,
        "metadata": metadata,
    }


async def execute_policy(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    policy_id: int,
    action: str,
    device_id: int | None = None,
) -> dict[str, Any]:
    """Execute an Automox policy immediately for remediation.

    Args:
        client: Automox API client
        org_id: Organization ID (optional, uses client default)
        policy_id: Policy ID to execute
        action: Action type - "remediateAll" or "remediateDevice"
        device_id: Device ID (required if action is "remediateDevice")

    Returns:
        Dictionary with execution data and metadata
    """
    resolved_org_id = require_org_id(client, org_id)

    normalized_action = action.strip()
    alias_map = {
        "remediateDevice": "remediateServer",
        "remediatedevice": "remediateServer",
    }
    effective_action = alias_map.get(normalized_action, normalized_action)

    # Validate action
    if effective_action not in {"remediateAll", "remediateServer"}:
        raise ValueError(
            f"Invalid action '{action}'. Use 'remediateAll' for all devices or "
            f"'remediateDevice' for a specific device."
        )

    # Validate device_id requirement
    if effective_action == "remediateServer" and device_id is None:
        raise ValueError("device_id is required when action is 'remediateDevice'")

    body: dict[str, Any] = {"action": effective_action}
    if device_id is not None:
        body["serverId"] = device_id

    params = {"o": resolved_org_id}
    response_data = await client.post(
        f"/policies/{policy_id}/action", json_data=body, params=params
    )

    data = {
        "policy_id": policy_id,
        "action": effective_action,
        "device_id": device_id,
        "execution_initiated": True,
        "response": response_data,
    }

    metadata = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "policy_id": policy_id,
    }

    return {
        "data": data,
        "metadata": metadata,
    }


async def delete_policy(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    policy_id: int,
) -> dict[str, Any]:
    """Delete an Automox policy by ID."""
    resolved_org_id = require_org_id(client, org_id)

    params = {"o": resolved_org_id}
    await client.delete(f"/policies/{policy_id}", params=params)

    return {
        "data": {
            "policy_id": policy_id,
            "deleted": True,
        },
        "metadata": {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
        },
    }


async def clone_policy(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    policy_id: int,
    name: str | None = None,
    server_groups: list[int] | None = None,
) -> dict[str, Any]:
    """Clone an existing Automox policy.

    Fetches the source policy, strips read-only fields, optionally overrides
    name and server_groups, then creates a new policy via POST.
    """
    resolved_org_id = require_org_id(client, org_id)

    params = {"o": resolved_org_id}
    source = await client.get(f"/policies/{policy_id}", params=params)
    if not isinstance(source, Mapping):
        raise ValueError(f"Failed to retrieve policy {policy_id} for cloning.")

    # Build the clone payload — strip read-only fields
    payload = {k: v for k, v in source.items() if k not in _READ_ONLY_POLICY_FIELDS}
    payload["organization_id"] = resolved_org_id

    # Apply overrides
    if name is not None:
        payload["name"] = name
    else:
        source_name = source.get("name") or f"Policy {policy_id}"
        payload["name"] = f"{source_name} (Clone)"

    if server_groups is not None:
        payload["server_groups"] = server_groups
    elif payload.get("server_groups") is None:
        payload["server_groups"] = []

    response = await client.post("/policies", json_data=payload, params=params)

    new_policy_id = (
        _extract_policy_id_from_response(response) if isinstance(response, Mapping) else None
    )

    # API may return empty body — search for the clone by name to get the ID
    if new_policy_id is None:
        clone_name = payload.get("name")
        try:
            all_policies = await client.get(
                "/policies", params={"o": resolved_org_id, "limit": 250}
            )
            if isinstance(all_policies, Sequence):
                for p in reversed(list(all_policies)):
                    if isinstance(p, Mapping) and p.get("name") == clone_name:
                        new_policy_id = p.get("id")
                        break
        except (AutomoxAPIError, ValueError, TypeError) as exc:
            logger.debug("Best-effort clone ID lookup failed: %s", exc)

    return {
        "data": {
            "source_policy_id": policy_id,
            "cloned_policy_id": new_policy_id,
            "name": payload.get("name"),
            "response": response,
        },
        "metadata": {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
        },
    }


__all__ = [
    "apply_policy_changes",
    "clone_policy",
    "delete_policy",
    "execute_policy",
    "normalize_policy_operations_input",
    "resolve_patch_approval",
]
