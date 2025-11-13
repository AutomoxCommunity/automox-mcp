"""Device workflows for Automox MCP."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from ..client import AutomoxClient


def _normalize_status(value: Any) -> str:
    """Normalize policy/device status values to consistent format."""
    if value in (None, "", [], {}):
        return "unknown"

    if isinstance(value, Mapping):
        for key in ("status", "policy_status", "result_status", "state"):
            inner = value.get(key)
            if inner not in (None, "", [], {}):
                return _normalize_status(inner)
        return "unknown"

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        statuses: list[str] = []
        for item in value:
            normalized = _normalize_status(item)
            if normalized != "unknown":
                statuses.append(normalized)
        if not statuses:
            return "unknown"
        unique_statuses = sorted(set(statuses))
        if len(unique_statuses) == 1:
            return unique_statuses[0]
        priority_order = ["failed", "error", "cancelled", "partial", "pending", "success"]
        for label in priority_order:
            if label in unique_statuses:
                return "mixed"
        return "mixed"

    status = str(value).strip().lower()
    if not status:
        return "unknown"
    if any(ch in status for ch in "{}[]"):
        return "mixed"
    if status in {"success", "succeeded", "completed", "complete"}:
        return "success"
    if status in {"partial", "partial_success"}:
        return "partial"
    if "fail" in status or "error" in status:
        return "failed"
    if "cancel" in status:
        return "cancelled"
    return status


def _extract_last_check_in(device: Mapping[str, Any]) -> str | None:
    """Find the most relevant last check-in timestamp for a device."""
    for key in (
        "last_check_in",
        "last_seen",
        "last_seen_time",
        "last_refresh_time",
        "last_process_time",
        "last_update_time",
        "last_disconnect_time",
    ):
        value = device.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _calculate_days_since_check_in(
    timestamp_str: str | None, *, now: datetime | None = None
) -> int | None:
    """Calculate the number of days since a check-in timestamp.

    Returns None if timestamp is missing or invalid.
    """
    if not timestamp_str:
        return None

    try:
        # Parse ISO 8601 timestamp (Automox uses this format)
        check_in_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        reference_time = now or datetime.now(UTC)
        delta = reference_time - check_in_time
        return int(delta.total_seconds() / 86400)  # Convert to days
    except (ValueError, AttributeError):
        return None


def _format_device_display_name(device: Mapping[str, Any]) -> str | None:
    """Format device display name with custom name in parentheses if present.

    Args:
        device: Device data dict from Automox API

    Returns:
        Formatted name like "hostname (custom-name)" or just "hostname",
        or None if no hostname found
    """
    hostname_value = device.get("name") or device.get("hostname") or device.get("device_name")
    hostname: str | None
    if isinstance(hostname_value, str):
        hostname = hostname_value.strip() or None
    elif hostname_value is not None:
        hostname = str(hostname_value).strip() or None
    else:
        hostname = None
    if not hostname:
        return None

    custom_name_value = device.get("custom_name")
    custom_name: str | None
    if isinstance(custom_name_value, str):
        custom_name = custom_name_value.strip() or None
    elif custom_name_value is not None:
        custom_name = str(custom_name_value).strip() or None
    else:
        custom_name = None

    if custom_name:
        return f"{hostname} ({custom_name})"
    return hostname


def _summarize_device_common_fields(device: Mapping[str, Any]) -> dict[str, Any]:
    """Extract shared classification fields used by inventory/health summaries."""
    managed_flag = device.get("managed")
    is_managed = bool(managed_flag) if managed_flag is not None else True

    policy_status = _extract_policy_status(device)
    last_check_in = _extract_last_check_in(device)

    pending_patches = device.get("pending_patches")
    if not isinstance(pending_patches, (int, float)):
        pending_patches = None

    has_pending_updates = device.get("pending")
    if not isinstance(has_pending_updates, bool):
        has_pending_updates = None

    needs_attention = device.get("needs_attention")
    if not isinstance(needs_attention, bool):
        needs_attention = None

    status_mapping = device.get("status")
    device_status_value = None
    if isinstance(status_mapping, Mapping):
        device_status_value = status_mapping.get("device_status") or status_mapping.get("status")
    device_status = _normalize_status(device_status_value)

    platform_raw = device.get("os_name") or device.get("platform") or "unknown"
    platform = str(platform_raw).lower()

    return {
        "is_managed": is_managed,
        "policy_status": policy_status,
        "pending_patches": pending_patches,
        "has_pending_updates": has_pending_updates,
        "needs_attention": needs_attention,
        "last_check_in": last_check_in,
        "device_status": device_status,
        "platform": platform,
    }


def _extract_policy_status(device: Mapping[str, Any]) -> str:
    """Derive the overall policy status string reported by Automox."""
    status_mapping = device.get("status")
    if isinstance(status_mapping, Mapping):
        primary = (
            status_mapping.get("policy_status")
            or status_mapping.get("device_status")
            or status_mapping.get("agent_status")
        )
        normalized = _normalize_status(primary)
        if normalized != "unknown":
            return normalized

    direct = device.get("policy_status")
    if isinstance(direct, str):
        return _normalize_status(direct)

    return "unknown"


def _count_failed_policies(device: Mapping[str, Any]) -> int:
    """Count the number of policy entries marked non-compliant."""
    status_mapping = device.get("status")
    entries = None
    if isinstance(status_mapping, Mapping):
        entries = status_mapping.get("policy_statuses")
    if not isinstance(entries, Sequence):
        return 0
    failures = 0
    for entry in entries:
        if isinstance(entry, Mapping) and entry.get("compliant") is False:
            failures += 1
    return failures


_POLICY_STATUS_LIMIT = 12
_POLICY_ASSIGNMENTS_LIMIT = 10
_SANITIZED_SEQUENCE_LIMIT = 5
_SANITIZED_STRING_LIMIT = 400
_SCRIPT_FIELDS = {
    "evaluation_code",
    "remediation_code",
    "installation_code",
    "script",
    "powershell_script",
    "powershellScript",
}
_DETAIL_KEY_MAP = {
    "MODEL": "model",
    "OS": "os_name",
    "OS_VERSION": "os_version",
    "SERIAL_NUMBER": "serial_number",
    "CHASSIS_TYPE": "chassis_type",
    "LAST_REBOOT_TIME": "last_reboot",
    "LAST_USER_LOGON": "last_user_logon",
    "IPS": "ip_addresses",
    "CPU": "cpu",
    "MEMORY": "memory",
    "DISK_TOTAL": "disk_total",
    "DISK_USED": "disk_used",
}

_MAX_HEALTH_RESPONSE_BYTES = 18_000
_DEFAULT_MAX_STALE_DEVICES = 25
_MAX_STALE_DEVICE_LIMIT = 200
_STALE_CHECK_IN_THRESHOLD_DAYS = 30


def _add_followup(metadata: dict[str, Any], tool: str, note: str) -> None:
    """Append a suggested follow-up entry without introducing duplicates."""
    followups = metadata.setdefault("suggested_followups", [])
    entry = {"tool": tool, "note": note}
    if entry not in followups:
        followups.append(entry)


def _truncate_string(value: str, *, limit: int = _SANITIZED_STRING_LIMIT) -> str:
    """Return a truncated string with a note when long values are trimmed."""
    if len(value) <= limit:
        return value
    trimmed = value[:limit]
    remaining = len(value) - limit
    return f"{trimmed}... ({remaining} chars truncated)"


def _summarize_policy_status(
    entries: Any, *, limit: int = _POLICY_STATUS_LIMIT
) -> tuple[list[dict[str, Any]], int]:
    """Condense Automox policy status records into a compact summary."""
    if not isinstance(entries, Sequence):
        return [], 0

    summary: list[dict[str, Any]] = []
    total = 0
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        total += 1
        if len(summary) >= limit:
            continue
        result_text = item.get("result")
        if isinstance(result_text, str):
            result_text = result_text.strip()
            if result_text == "{}":
                result_text = None
        summary_item = {
            "policy_id": item.get("policy_id") or item.get("id"),
            "policy_name": item.get("policy_name") or item.get("name"),
            "status": _normalize_status(
                item.get("status") or item.get("policy_status") or item.get("result_status")
            ),
            "execution_time": item.get("create_time") or item.get("updated_at"),
            "pending_count": item.get("pending_count"),
            "will_reboot": item.get("will_reboot"),
        }
        if result_text:
            summary_item["result"] = result_text
        summary.append({k: v for k, v in summary_item.items() if v not in (None, "", [], {})})

    return summary, total


def _summarize_policy_assignments(
    entries: Any, *, limit: int = _POLICY_ASSIGNMENTS_LIMIT
) -> tuple[list[dict[str, Any]], Counter[str], int]:
    """Summarize assigned Automox policies without embedding full scripts."""
    if not isinstance(entries, Sequence):
        return [], Counter(), 0

    summary: list[dict[str, Any]] = []
    status_counter: Counter[str] = Counter()
    total = 0

    for item in entries:
        if not isinstance(item, Mapping):
            continue
        total += 1
        status = _normalize_status(item.get("status"))
        status_counter[status] += 1
        if len(summary) >= limit:
            continue

        configuration_raw = item.get("configuration")
        configuration: Mapping[str, Any] = (
            configuration_raw if isinstance(configuration_raw, Mapping) else {}
        )

        server_groups_raw = item.get("server_groups")
        group_names: list[str] = []
        group_remaining = 0
        server_group_count: int | None = None
        if isinstance(server_groups_raw, Sequence) and not isinstance(
            server_groups_raw, (str, bytes, bytearray)
        ):
            server_group_count = len(server_groups_raw)
            group_names = [
                str(group.get("name"))
                for group in server_groups_raw[:_SANITIZED_SEQUENCE_LIMIT]
                if isinstance(group, Mapping) and group.get("name")
            ]
            group_remaining = max(len(server_groups_raw) - _SANITIZED_SEQUENCE_LIMIT, 0)

        summary_item: dict[str, Any] = {
            "policy_id": item.get("id"),
            "policy_uuid": item.get("uuid") or item.get("policy_uuid"),
            "policy_name": item.get("name"),
            "policy_type": item.get("policy_type_name"),
            "status": status,
            "next_remediation": item.get("next_remediation"),
            "server_group_count": server_group_count,
            "server_groups": group_names if group_names else None,
            "auto_reboot": configuration.get("auto_reboot")
            if isinstance(configuration.get("auto_reboot"), bool)
            else configuration.get("auto_reboot"),
        }
        device_filters = configuration.get("device_filters")
        if isinstance(device_filters, Sequence) and not isinstance(
            device_filters, (str, bytes, bytearray)
        ):
            summary_item["device_filter_count"] = len(device_filters)
        if group_remaining:
            summary_item["server_groups_truncated"] = group_remaining

        summary.append({k: v for k, v in summary_item.items() if v not in (None, "", [], {})})

    return summary, status_counter, total


def _extract_detail_facts(detail: Any) -> dict[str, Any] | None:
    """Pull notable inventory facts out of Automox device detail payloads."""
    if not isinstance(detail, Mapping):
        return None

    facts: dict[str, Any] = {}
    for raw_key, output_key in _DETAIL_KEY_MAP.items():
        value = detail.get(raw_key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            preview = value[:_SANITIZED_SEQUENCE_LIMIT]
            if len(value) > _SANITIZED_SEQUENCE_LIMIT:
                preview = preview + [f"... {len(value) - _SANITIZED_SEQUENCE_LIMIT} more"]
            facts[output_key] = preview
            continue
        if isinstance(value, Mapping):
            inner = {k.lower(): v for k, v in value.items() if v not in (None, "", [], {})}
            if inner:
                facts[output_key] = inner
            continue
        facts[output_key] = value

    return facts or None


def _sanitize_raw_device_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Trim large strings and sequences so raw payloads stay within token budgets."""

    def sanitize(value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "... (max depth reached)"

        if isinstance(value, Mapping):
            sanitized: dict[str, Any] = {}
            for key, inner_value in value.items():
                if key in _SCRIPT_FIELDS and isinstance(inner_value, str):
                    sanitized[key] = "... (script omitted to reduce payload size)"
                    continue
                sanitized[key] = sanitize(inner_value, depth + 1)
            return sanitized

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            trimmed = [sanitize(item, depth + 1) for item in value[:_SANITIZED_SEQUENCE_LIMIT]]
            if len(value) > _SANITIZED_SEQUENCE_LIMIT:
                trimmed.append(
                    {
                        "_note": (
                            f"{len(value) - _SANITIZED_SEQUENCE_LIMIT} additional items truncated"
                        )
                    }
                )
            return trimmed

        if isinstance(value, str):
            return _truncate_string(value)

        return value

    sanitized_payload = sanitize(dict(payload))
    return cast(dict[str, Any], sanitized_payload)


async def list_devices_needing_attention(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    group_id: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Highlight devices that Automox flags as needing attention."""

    resolved_org_id = org_id or client.org_id
    if not resolved_org_id:
        raise ValueError("org_id required - pass explicitly or set AUTOMOX_ORG_ID")

    params = {"o": resolved_org_id, "limit": limit, "offset": 0}
    if group_id is not None:
        params["groupId"] = group_id

    report = await client.get("/reports/needs-attention", params=params, api="console")

    items = report.get("data") if isinstance(report, Mapping) else None
    devices: Sequence[Mapping[str, Any]] = items if isinstance(items, Sequence) else []

    curated_devices = []
    for item in devices:
        curated_devices.append(
            {
                "device_id": item.get("device_id") or item.get("id"),
                "device_name": _format_device_display_name(item),
                "policy_status": item.get("policy_status") or item.get("status"),
                "pending_patches": item.get("pending_updates") or item.get("pending"),
                "last_check_in": item.get("last_check_in") or item.get("last_seen"),
                "server_group_id": item.get("server_group_id"),
            }
        )

    data = {
        "group_id": group_id,
        "device_count": len(curated_devices),
        "devices": curated_devices,
    }

    metadata = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "group_id": group_id,
        "requested_limit": limit,
    }

    return {
        "data": data,
        "metadata": metadata,
    }


async def list_device_inventory(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    group_id: int | None = None,
    limit: int = 25,
    include_unmanaged: bool = False,
    policy_status: str | None = None,
    managed: bool | None = None,
) -> dict[str, Any]:
    """Return a list of devices in the organization with optional filtering."""

    resolved_org_id = org_id or client.org_id
    if not resolved_org_id:
        raise ValueError("org_id required - pass explicitly or set AUTOMOX_ORG_ID")

    params = {"o": resolved_org_id}
    if group_id is not None:
        params["groupId"] = group_id
    if limit is not None:
        params["limit"] = limit

    payload = await client.get("/servers", params=params, api="console")
    devices: Sequence[Mapping[str, Any]] = payload if isinstance(payload, list) else []

    policy_status_filter = _normalize_status(policy_status) if policy_status else None

    curated_devices = []
    for item in devices:
        summary_fields = _summarize_device_common_fields(item)
        is_managed = summary_fields["is_managed"]

        if managed is not None and is_managed != managed:
            continue
        if not include_unmanaged and not is_managed:
            continue
        policy_status = summary_fields["policy_status"]
        if policy_status_filter and policy_status != policy_status_filter:
            continue

        curated_devices.append(
            {
                "device_id": item.get("id") or item.get("device_id"),
                "hostname": _format_device_display_name(item),
                "managed": is_managed,
                "os": item.get("os_name") or item.get("platform"),
                "policy_status": policy_status,
                "policy_failures": _count_failed_policies(item) or None,
                "pending_patches": summary_fields["pending_patches"],
                "needs_attention": summary_fields["needs_attention"],
                "last_check_in": summary_fields["last_check_in"],
                "server_group_id": item.get("server_group_id"),
            }
        )

    preview = curated_devices[:limit]

    data = {
        "total_devices_returned": len(curated_devices),
        "devices": preview,
    }

    metadata = payload.get("metadata", {}) if isinstance(payload, Mapping) else {}
    metadata.update(
        {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
            "group_id": group_id,
            "requested_limit": limit,
            "include_unmanaged": include_unmanaged,
            "filters": {
                "policy_status": policy_status_filter,
                "managed": managed,
            },
        }
    )

    return {
        "data": data,
        "metadata": metadata,
    }


async def describe_device(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    device_id: int,
    include_packages: bool = False,
    include_inventory: bool = True,
    include_queue: bool = True,
    include_raw_details: bool = False,
) -> dict[str, Any]:
    """Provide a consolidated view of an Automox device."""

    resolved_org_id = org_id or client.org_id
    if not resolved_org_id:
        raise ValueError("org_id required - pass explicitly or set AUTOMOX_ORG_ID")

    params = {
        "o": resolved_org_id,
        "includeDetails": 1,
        "includeServerEvents": 1,
        "includeNextPatchTime": 1,
    }
    device_response = await client.get(f"/servers/{device_id}", params=params, api="console")
    device_data: Mapping[str, Any] = device_response if isinstance(device_response, Mapping) else {}

    packages_preview: list[dict[str, Any]] = []
    inventory_summary: dict[str, Any] | None = None
    queue_preview: list[dict[str, Any]] = []

    if include_packages:
        pkg_params: dict[str, Any] = {"o": resolved_org_id, "limit": 10}
        packages_raw = await client.get(
            f"/servers/{device_id}/packages", params=pkg_params, api="console"
        )
        if isinstance(packages_raw, Sequence):
            packages_preview = [
                {
                    "name": pkg.get("name") or pkg.get("package_name"),
                    "version": pkg.get("version"),
                    "status": pkg.get("status"),
                }
                for pkg in packages_raw[:10]
                if isinstance(pkg, Mapping)
            ]

    if include_inventory:
        org_uuid_str = (
            device_data.get("org_uuid")
            or device_data.get("organization_uuid")
            or device_data.get("orgId")
        )
        device_uuid_str = device_data.get("device_uuid") or device_data.get("uuid")
        try:
            if org_uuid_str and device_uuid_str:
                org_uuid_val = UUID(str(org_uuid_str))
                device_uuid_uuid = UUID(str(device_uuid_str))
                path = f"/device-details/orgs/{org_uuid_val}/devices/{device_uuid_uuid}/inventory"
                inventory_raw = await client.get(path, api="console")
                if isinstance(inventory_raw, Mapping):
                    inventory_map: Mapping[str, Any] = inventory_raw
                    categories: list[dict[str, Any]] = []
                    for name, items in inventory_map.items():
                        entry: dict[str, Any] = {"name": name}
                        if isinstance(items, Sequence) and not isinstance(
                            items, (str, bytes, bytearray)
                        ):
                            entry["item_count"] = len(items)
                        elif isinstance(items, Mapping):
                            entry["item_count"] = len(items)
                        categories.append(entry)
                        if len(categories) >= 15:
                            break
                    inventory_summary = {
                        "total_categories": len(inventory_map),
                        "categories": categories,
                    }
        except (ValueError, TypeError):
            inventory_summary = None

    if include_queue:
        queue_params: dict[str, Any] = {"o": resolved_org_id}
        queue_raw = await client.get(
            f"/servers/{device_id}/queues", params=queue_params, api="console"
        )
        if isinstance(queue_raw, Sequence):
            queue_preview = [
                {
                    "command": item.get("command") or item.get("type"),
                    "scheduled_time": item.get("scheduled_time") or item.get("scheduledAt"),
                    "status": item.get("status"),
                }
                for item in queue_raw[:10]
                if isinstance(item, Mapping)
            ]

    policy_status_summary, policy_status_total = _summarize_policy_status(
        device_data.get("policy_status")
    )
    policy_assignments_summary, policy_assignments_breakdown, policy_assignments_total = (
        _summarize_policy_assignments(device_data.get("server_policies"))
    )
    detail_facts = _extract_detail_facts(device_data.get("detail"))

    tags_preview: list[str] | None = None
    raw_tags = device_data.get("tags") or device_data.get("labels")
    if isinstance(raw_tags, Sequence) and not isinstance(raw_tags, (str, bytes, bytearray)):
        tags_preview = [str(tag) for tag in raw_tags[:_SANITIZED_SEQUENCE_LIMIT]]
        if len(raw_tags) > _SANITIZED_SEQUENCE_LIMIT:
            tags_preview.append(f"... {len(raw_tags) - _SANITIZED_SEQUENCE_LIMIT} more")
    elif raw_tags is not None:
        tags_preview = [str(raw_tags)]

    ip_addresses_preview: list[str] | None = None
    for ip_key in ("ip_addrs", "ip_addrs_private"):
        raw_ips = device_data.get(ip_key)
        if isinstance(raw_ips, Sequence) and not isinstance(raw_ips, (str, bytes, bytearray)):
            ip_addresses_preview = [str(ip) for ip in raw_ips[:_SANITIZED_SEQUENCE_LIMIT]]
            if len(raw_ips) > _SANITIZED_SEQUENCE_LIMIT:
                ip_addresses_preview.append(f"... {len(raw_ips) - _SANITIZED_SEQUENCE_LIMIT} more")
            break

    status_value: Any = device_data.get("status")
    if isinstance(status_value, Mapping):
        status_value = (
            status_value.get("policy_status")
            or status_value.get("device_status")
            or status_value.get("status")
        )

    core: dict[str, Any] = {"device_id": device_id}
    device_uuid_val = device_data.get("device_uuid") or device_data.get("uuid")
    if device_uuid_val:
        core["device_uuid"] = device_uuid_val

    display_name = _format_device_display_name(device_data)
    if display_name:
        core["hostname"] = display_name

    os_name = device_data.get("os_name") or device_data.get("platform")
    if os_name:
        core["os"] = os_name

    os_version = device_data.get("os_version")
    if os_version:
        core["os_version"] = os_version

    agent_version = device_data.get("agent_version")
    if agent_version:
        core["agent_version"] = agent_version

    ip_address = device_data.get("ip_address")
    if ip_address:
        core["ip_address"] = ip_address

    if ip_addresses_preview:
        core["ip_addresses"] = ip_addresses_preview

    server_group_id = device_data.get("server_group_id")
    if server_group_id:
        core["server_group_id"] = server_group_id

    last_check_in = device_data.get("last_check_in")
    if last_check_in:
        core["last_check_in"] = last_check_in

    last_refresh_time = device_data.get("last_refresh_time")
    if last_refresh_time:
        core["last_refresh_time"] = last_refresh_time

    uptime = device_data.get("uptime")
    if uptime is not None:
        core["uptime"] = uptime

    next_patch_time = device_data.get("next_patch_time")
    if next_patch_time:
        core["next_patch_time"] = next_patch_time

    managed_value = device_data.get("managed")
    if managed_value is not None:
        core["managed"] = managed_value

    patch_status = device_data.get("patch_status") or device_data.get("patchStatus")
    if patch_status:
        core["patch_status"] = patch_status

    normalized_status = _normalize_status(status_value)
    if normalized_status != "unknown":
        core["status"] = normalized_status

    if tags_preview:
        core["tags"] = tags_preview

    core["policy_status"] = policy_status_summary

    try:
        raw_payload_bytes = len(json.dumps(device_data))
    except (TypeError, ValueError):
        raw_payload_bytes = None

    if include_raw_details and device_data:
        raw_details = {
            "included": True,
            "notice": (
                "Payload sanitized: long strings truncated to "
                f"{_SANITIZED_STRING_LIMIT} chars and sequences limited "
                f"to {_SANITIZED_SEQUENCE_LIMIT} items."
            ),
            "payload": _sanitize_raw_device_payload(device_data),
        }
    else:
        available_fields = sorted(device_data.keys()) if device_data else []
        raw_details = {
            "included": False,
            "available_fields": available_fields,
        }

    data: dict[str, Any] = {
        "core": core,
        "software_preview": packages_preview,
        "inventory_overview": inventory_summary,
        "pending_commands": queue_preview,
        "policy_assignments": {
            "total": policy_assignments_total,
            "truncated": policy_assignments_total > len(policy_assignments_summary),
            "status_breakdown": dict(policy_assignments_breakdown),
            "policies": policy_assignments_summary,
        },
        "raw_details": raw_details,
    }

    if detail_facts:
        data["device_facts"] = detail_facts

    metadata = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "device_id": device_id,
        "include_packages": include_packages,
        "include_inventory": include_inventory,
        "include_queue": include_queue,
        "include_raw_details": include_raw_details,
        "policy_status_total": policy_status_total,
        "policy_status_displayed": len(policy_status_summary),
        "policy_status_truncated": policy_status_total > len(policy_status_summary),
        "policy_assignments_total": policy_assignments_total,
        "policy_assignments_displayed": len(policy_assignments_summary),
        "policy_assignments_truncated": policy_assignments_total > len(policy_assignments_summary),
        "policy_assignments_status_breakdown": dict(policy_assignments_breakdown),
        "software_preview_count": len(packages_preview),
        "pending_commands_count": len(queue_preview),
        "device_facts_available": detail_facts is not None,
    }

    if inventory_summary:
        metadata["inventory_category_count"] = inventory_summary.get("total_categories")

    if raw_payload_bytes is not None:
        metadata["raw_payload_bytes"] = raw_payload_bytes

    return {
        "data": data,
        "metadata": metadata,
    }


async def search_devices(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    hostname_contains: str | None = None,
    ip_address: str | None = None,
    tag: str | None = None,
    patch_status: Literal["missing"] | None = None,
    severity: Sequence[str] | str | None = None,
    managed: bool | None = None,
    group_id: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search for devices using simple text and attribute filters."""

    resolved_org_id = org_id or client.org_id
    if not resolved_org_id:
        raise ValueError("org_id required - pass explicitly or set AUTOMOX_ORG_ID")

    params: dict[str, Any] = {"o": resolved_org_id, "limit": min(limit, 500)}
    if group_id is not None:
        params["groupId"] = group_id
    if managed is not None:
        params["managed"] = 1 if managed else 0
    if patch_status is not None:
        params["patchStatus"] = patch_status
    severity_values: list[str] = []
    if isinstance(severity, str):
        severity_values = [severity]
    elif isinstance(severity, Sequence) and not isinstance(severity, (str, bytes, bytearray)):
        severity_values = [str(value) for value in severity]
    if severity_values:
        normalized_severity = [
            value.strip().lower() for value in severity_values if str(value).strip()
        ]
        if normalized_severity:
            params["filters[severity][]"] = normalized_severity
            severity_values = normalized_severity
        else:
            severity_values = []

    devices = await client.get("/servers", params=params, api="console")
    devices = devices if isinstance(devices, Sequence) else []

    filtered = []
    hostname_term = (hostname_contains or "").lower()
    ip_term = (ip_address or "").strip()
    tag_term = (tag or "").lower()

    for device in devices:
        if hostname_term:
            name = str(device.get("name") or device.get("hostname") or "").lower()
            custom_name = str(device.get("custom_name") or "").lower()
            # Match if term is in either hostname or custom_name
            if hostname_term not in name and hostname_term not in custom_name:
                continue

        if ip_term:
            ip = str(device.get("ip_address") or device.get("ipAddress") or "").strip()
            if ip != ip_term:
                continue

        if tag_term:
            tags = device.get("tags") or device.get("labels") or []
            tags_lower = {str(t).lower() for t in tags} if isinstance(tags, Sequence) else set()
            if tag_term not in tags_lower:
                continue

        filtered.append(device)
        if len(filtered) >= limit:
            break

    preview = []
    for item in filtered:
        preview.append(
            {
                "device_id": item.get("id") or item.get("device_id"),
                "hostname": _format_device_display_name(item),
                "ip_address": item.get("ip_address"),
                "server_group_id": item.get("server_group_id"),
                "managed": item.get("managed"),
                "pending_patches": item.get("pending_patches"),
                "needs_attention": item.get("needs_attention"),
                "last_check_in": item.get("last_check_in"),
                "tags": item.get("tags") or item.get("labels"),
            }
        )

    metadata = {}
    metadata.update(
        {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
            "group_id": group_id,
            "request_limit": limit,
            "filters": {
                "hostname_contains": hostname_contains,
                "ip_address": ip_address,
                "tag": tag,
                "patch_status": patch_status,
                "severity": severity_values if severity_values else None,
                "managed": managed,
            },
        }
    )

    data = {
        "matches": len(preview),
        "devices": preview,
    }

    return {
        "data": data,
        "metadata": metadata,
    }


async def summarize_device_health(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    group_id: int | None = None,
    include_unmanaged: bool = False,
    limit: int | None = 500,
    max_stale_devices: int | None = _DEFAULT_MAX_STALE_DEVICES,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate high-level health signals for devices in the organization."""

    resolved_org_id = org_id or client.org_id
    if not resolved_org_id:
        raise ValueError("org_id required - pass explicitly or set AUTOMOX_ORG_ID")

    effective_limit = 500
    if limit is not None:
        effective_limit = max(1, min(limit, 500))

    params = {"o": resolved_org_id, "limit": effective_limit}
    if group_id is not None:
        params["groupId"] = group_id

    devices = await client.get("/servers", params=params, api="console")
    devices = devices if isinstance(devices, Sequence) else []

    totals: Counter[str] = Counter()
    device_status_counts: Counter[str] = Counter()
    policy_execution_counts: Counter[str] = Counter()
    platform_counts: Counter[str] = Counter()
    compliant_counts: Counter[str] = Counter()
    devices_with_pending_patches = 0
    devices_needing_attention = 0
    check_in_recency_counts: Counter[str] = Counter()
    stale_devices: list[dict[str, Any]] = []

    stale_limit: int | None
    if max_stale_devices is None:
        stale_limit = None
    else:
        normalized_limit = max(0, min(int(max_stale_devices), _MAX_STALE_DEVICE_LIMIT))
        stale_limit = normalized_limit

    for device in devices:
        summary_fields = _summarize_device_common_fields(device)
        is_managed = summary_fields["is_managed"]
        totals["managed" if is_managed else "unmanaged"] += 1
        if not include_unmanaged and not is_managed:
            continue

        device_status_counts[summary_fields["device_status"]] += 1
        policy_execution_counts[summary_fields["policy_status"]] += 1
        platform = summary_fields["platform"] or "unknown"
        platform_counts[platform] += 1

        device_compliant = device.get("compliant")
        device_pending = device.get("pending")
        if device_compliant is True and device_pending is False:
            compliant_counts["compliant"] += 1
        elif device_compliant is False or device_pending is True:
            compliant_counts["non_compliant"] += 1
        else:
            compliant_counts["unknown"] += 1

        pending_patches = summary_fields.get("pending_patches")
        if isinstance(pending_patches, (int, float)) and pending_patches > 0:
            devices_with_pending_patches += 1

        if summary_fields.get("needs_attention"):
            devices_needing_attention += 1

        # Calculate check-in recency
        last_check_in = summary_fields["last_check_in"]
        days_since = _calculate_days_since_check_in(last_check_in, now=current_time)

        if days_since is None:
            check_in_recency_counts["never_connected"] += 1
        elif days_since == 0:
            check_in_recency_counts["last_24_hours"] += 1
        elif days_since <= 7:
            check_in_recency_counts["last_7_days"] += 1
        elif days_since <= 30:
            check_in_recency_counts["last_30_days"] += 1
        else:
            check_in_recency_counts["30_plus_days"] += 1

        stale_reason = None
        if last_check_in is None:
            stale_reason = "no check-in recorded"
        elif days_since is None:
            stale_reason = "invalid check-in timestamp"
        elif days_since > _STALE_CHECK_IN_THRESHOLD_DAYS:
            stale_reason = (
                f"last check-in {days_since} days ago "
                f"(>{_STALE_CHECK_IN_THRESHOLD_DAYS} day threshold)"
            )

        if stale_reason:
            stale_devices.append(
                {
                    "device_id": device.get("id"),
                    "display_name": _format_device_display_name(device) or device.get("name"),
                    "platform": platform,
                    "policy_status": summary_fields["policy_status"],
                    "last_check_in": last_check_in,
                    "days_since_check_in": days_since,
                    "needs_attention": summary_fields.get("needs_attention"),
                    "reason": stale_reason,
                }
            )

    total_devices = sum(totals.values()) if include_unmanaged else totals["managed"]
    if stale_limit is None:
        stale_preview = list(stale_devices)
    else:
        stale_preview = stale_devices[:stale_limit]

    data = {
        "total_devices": total_devices,
        "managed_breakdown": dict(totals),
        "device_status_breakdown": dict(device_status_counts),
        "policy_execution_breakdown": dict(policy_execution_counts),
        "platform_breakdown": dict(platform_counts),
        "compliant_devices": compliant_counts["compliant"],
        "devices_with_pending_patches": devices_with_pending_patches,
        "devices_needing_attention": devices_needing_attention,
        "check_in_recency_breakdown": dict(check_in_recency_counts),
        "stale_devices": stale_preview,
    }

    metadata = {}
    metadata.update(
        {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
            "group_id": group_id,
            "include_unmanaged": include_unmanaged,
            "requested_limit": limit,
            "effective_limit": effective_limit,
            "fetched_device_count": len(devices),
            "max_stale_devices": stale_limit,
            "stale_device_count": len(stale_devices),
            "stale_check_in_threshold_days": _STALE_CHECK_IN_THRESHOLD_DAYS,
        }
    )
    if stale_limit is not None and len(stale_devices) > stale_limit:
        metadata["stale_devices_truncated"] = True

    response = {"data": data, "metadata": metadata}
    try:
        response_size = len(json.dumps(response))
    except (TypeError, ValueError):
        response_size = None

    if response_size and response_size > _MAX_HEALTH_RESPONSE_BYTES:
        metadata["response_truncated"] = True
        _add_followup(
            metadata,
            "device_health_summary",
            "Reduce the limit or group by server group to shrink the response.",
        )
        _add_followup(
            metadata,
            "search_devices",
            "Filter by hostname, tag, or pending patches to focus on specific devices.",
        )
        response = {"data": data, "metadata": metadata}
        try:
            response_size = len(json.dumps(response))
        except (TypeError, ValueError):
            response_size = None

    if response_size is not None:
        metadata["approx_response_bytes"] = response_size

    return response


async def issue_device_command(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    device_id: int,
    command_type: str,
    patch_names: str | None = None,
) -> dict[str, Any]:
    """Issue an immediate command to an Automox device.

    Args:
        client: Automox API client
        org_id: Organization ID (optional, uses client default)
        device_id: Device ID to send command to
        command_type: Command type - "scan", "patch_all", "patch_specific",
            "reboot", or "refresh_os"
        patch_names: Comma-separated patch names (required for patch_specific command)

    Returns:
        Dictionary with command execution data and metadata
    """
    resolved_org_id = org_id or client.org_id
    if not resolved_org_id:
        raise ValueError("org_id required - pass explicitly or set AUTOMOX_ORG_ID")

    # Normalize command type to API values
    command_normalized = command_type.lower().replace("-", "_").replace(" ", "_")
    command_map = {
        "scan": "GetOS",
        "get_os": "GetOS",
        "getos": "GetOS",
        "refresh": "GetOS",
        "refresh_os": "GetOS",
        "patch": "InstallAllUpdates",
        "patch_all": "InstallAllUpdates",
        "install_all": "InstallAllUpdates",
        "installallupdates": "InstallAllUpdates",
        "patch_specific": "InstallUpdate",
        "install_update": "InstallUpdate",
        "installupdate": "InstallUpdate",
        "reboot": "Reboot",
        "restart": "Reboot",
    }
    command_value = command_map.get(command_normalized, command_type)

    # Validate command type
    valid_commands = {"GetOS", "InstallUpdate", "InstallAllUpdates", "Reboot"}
    if command_value not in valid_commands:
        raise ValueError(
            f"Invalid command '{command_type}'. Use: 'scan', 'patch_all', "
            f"'patch_specific', or 'reboot'"
        )

    # Validate patch_names requirement
    if command_value == "InstallUpdate" and not patch_names:
        raise ValueError("patch_names is required when command_type is 'patch_specific'")

    body: dict[str, Any] = {"command_type_name": command_value}
    if patch_names:
        body["args"] = patch_names

    params = {"o": resolved_org_id}
    response_data = await client.post(
        f"/servers/{device_id}/queues", json_data=body, params=params, api="console"
    )

    data = {
        "device_id": device_id,
        "command_type": command_value,
        "patch_names": patch_names,
        "command_queued": True,
        "response": response_data,
    }

    metadata = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "device_id": device_id,
    }

    return {
        "data": data,
        "metadata": metadata,
    }
