"""Report workflows for Automox MCP."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..client import AutomoxClient


_SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "none": 0,
}


def _highest_patch_severity(patches: Any) -> str:
    """Return the highest severity found across a device's patches."""
    if not patches:
        return "unknown"
    items: Sequence[Any]
    if isinstance(patches, Mapping):
        items = list(patches.values())
    elif isinstance(patches, Sequence) and not isinstance(patches, (str, bytes)):
        items = patches
    else:
        return "unknown"

    max_rank = -1
    for patch in items:
        if not isinstance(patch, Mapping):
            continue
        sev = str(
            patch.get("severity") or patch.get("cve_severity") or ""
        ).lower().strip()
        rank = _SEVERITY_RANK.get(sev, -1)
        if rank > max_rank:
            max_rank = rank

    for sev_name, rank in _SEVERITY_RANK.items():
        if rank == max_rank:
            return sev_name
    return "unknown"


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
    """Retrieve the pre-patch readiness report.

    Automatically paginates to fetch all devices unless an explicit
    limit/offset is provided (single-page mode).
    """
    params: dict[str, Any] = {"o": org_id}
    if group_id is not None:
        params["groupId"] = group_id

    # If caller provided explicit limit/offset, do a single request (backwards compat)
    single_page = limit is not None or offset is not None
    if single_page:
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

    page_size = limit or 500
    params.setdefault("limit", page_size)
    params.setdefault("offset", 0)

    device_list: list[Any] = []
    summary: dict[str, Any] = {}

    while True:
        report = await client.get("/reports/prepatch", params=params)

        # Response shape: {"prepatch": {"total": N, ..., "devices": [...]}}
        page_devices = _extract_devices(report, "prepatch", "devices")
        if not summary:
            summary = _extract_summary(report, "prepatch")

        device_list.extend(page_devices)

        if single_page:
            break

        total = summary.get("total") or 0
        if len(device_list) >= total or not page_devices:
            break

        params["offset"] = params["offset"] + page_size

    devices: list[dict[str, Any]] = []
    severity_counter: Counter[str] = Counter()
    for item in device_list:
        if not isinstance(item, Mapping):
            continue
        patches = item.get("patches")
        patch_count: int | None = None
        if isinstance(patches, Sequence) and not isinstance(patches, (str, bytes)):
            patch_count = len(patches)
        elif isinstance(patches, Mapping):
            patch_count = sum(1 for _ in patches)

        device_severity = _highest_patch_severity(patches)
        severity_counter[device_severity] += 1

        entry: dict[str, Any] = {
            "server_id": item.get("id"),
            "server_name": item.get("name"),
            "group": item.get("group"),
            "os_family": item.get("os_family"),
            "connected": item.get("connected"),
            "compliant": item.get("compliant"),
            "needs_reboot": item.get("needsReboot"),
            "pending_patches": patch_count,
            "highest_severity": device_severity,
        }
        devices.append(entry)

    total_org_devices = summary.get("total") or 0
    devices_needing_patches = len(devices)
    device_severity_summary = {
        "total_org_devices": total_org_devices,
        "devices_needing_patches": devices_needing_patches,
        "critical": severity_counter.get("critical", 0),
        "high": severity_counter.get("high", 0),
        "medium": severity_counter.get("medium", 0),
        "low": severity_counter.get("low", 0),
        "none": severity_counter.get("none", 0),
        "unknown": severity_counter.get("unknown", 0),
    }

    return {
        "data": {
            "total_org_devices": total_org_devices,
            "total_devices": devices_needing_patches,
            "summary": device_severity_summary,
            "api_summary": summary,
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
