"""Report workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..client import AutomoxClient


def _extract_devices(response: Any, *wrapper_keys: str) -> list[Any]:
    """Extract a device list from a potentially nested API response.

    The Automox reports API returns nested structures like
    ``{"prepatch": {"devices": [...]}}`` or an array of
    ``{"nonCompliant": {"devices": [...]}}``.  This helper walks
    *wrapper_keys* to reach the device list.
    """
    current: Any = response

    # If the response is a list, check inside the first element
    if isinstance(current, list) and current:
        current = current[0]

    # Walk through wrapper keys (e.g. "prepatch" -> "devices")
    for key in wrapper_keys:
        if isinstance(current, Mapping):
            current = current.get(key)
        else:
            return []

    if isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
        return list(current)
    return []


def _extract_summary(response: Any, wrapper_key: str) -> dict[str, Any]:
    """Extract top-level summary counters from a report response."""
    current: Any = response
    if isinstance(current, list) and current:
        current = current[0]
    if isinstance(current, Mapping):
        section = current.get(wrapper_key)
        if isinstance(section, Mapping):
            return {k: v for k, v in section.items() if k != "devices"}
    return {}


async def get_prepatch_report(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Retrieve the pre-patch readiness report."""
    params: dict[str, Any] = {"o": org_id}
    if group_id is not None:
        params["groupId"] = group_id
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    report = await client.get("/reports/prepatch", params=params)

    # Response shape: {"prepatch": {"total": N, ..., "devices": [...]}}
    device_list = _extract_devices(report, "prepatch", "devices")
    summary = _extract_summary(report, "prepatch")

    devices: list[dict[str, Any]] = []
    for item in device_list:
        if not isinstance(item, Mapping):
            continue
        patches = item.get("patches")
        patch_count: int | None = None
        if isinstance(patches, Sequence) and not isinstance(patches, (str, bytes)):
            patch_count = len(patches)
        elif isinstance(patches, Mapping):
            patch_count = sum(1 for _ in patches)

        entry: dict[str, Any] = {
            "server_id": item.get("id"),
            "server_name": item.get("name"),
            "group": item.get("group"),
            "os_family": item.get("os_family"),
            "connected": item.get("connected"),
            "compliant": item.get("compliant"),
            "needs_reboot": item.get("needsReboot"),
            "pending_patches": patch_count,
        }
        devices.append(entry)

    return {
        "data": {
            "total_devices": summary.get("total") or len(devices),
            "summary": summary,
            "devices": devices,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def get_noncompliant_report(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Retrieve the non-compliant devices report."""
    params: dict[str, Any] = {"o": org_id}
    if group_id is not None:
        params["groupId"] = group_id
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    report = await client.get(
        "/reports/needs-attention", params=params,
    )

    # Response shape: array or {"nonCompliant": {"total": N, ..., "devices": [...]}}
    device_list = _extract_devices(report, "nonCompliant", "devices")
    summary = _extract_summary(report, "nonCompliant")

    devices: list[dict[str, Any]] = []
    for item in device_list:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "server_id": item.get("id"),
            "server_name": item.get("name") or item.get("customName"),
            "server_group_id": item.get("groupId"),
            "os_family": item.get("os_family"),
            "connected": item.get("connected"),
            "needs_reboot": item.get("needsReboot"),
            "last_refresh_time": item.get("lastRefreshTime"),
        }
        policies = item.get("policies")
        if isinstance(policies, list):
            entry["failing_policies"] = [
                {"id": p.get("id"), "name": p.get("name")}
                for p in policies
                if isinstance(p, Mapping)
            ]
        devices.append(entry)

    return {
        "data": {
            "total_devices": summary.get("total") or len(devices),
            "summary": summary,
            "devices": devices,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }
