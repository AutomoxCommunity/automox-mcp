"""Report workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient


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
        params["l"] = limit
    if offset is not None:
        params["p"] = offset

    report = await client.get("/reports/prepatch", params=params, api="console")

    if not isinstance(report, list):
        report_list: list[Any] = [report] if report else []
    else:
        report_list = report

    total = len(report_list)
    devices: list[dict[str, Any]] = []
    for item in report_list:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "server_id": item.get("server_id") or item.get("id"),
            "server_name": item.get("server_name") or item.get("name"),
            "server_group_id": item.get("server_group_id"),
            "pending_patches": item.get("pending_patches") or item.get("patch_count"),
            "os_family": item.get("os_family"),
            "status": item.get("status"),
        }
        devices.append(entry)

    return {
        "data": {
            "total_devices": total,
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
        params["l"] = limit
    if offset is not None:
        params["p"] = offset

    report = await client.get(
        "/reports/needs-attention", params=params, api="console"
    )

    if not isinstance(report, list):
        report_list: list[Any] = [report] if report else []
    else:
        report_list = report

    total = len(report_list)
    devices: list[dict[str, Any]] = []
    for item in report_list:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "server_id": item.get("server_id") or item.get("id"),
            "server_name": item.get("server_name") or item.get("name"),
            "server_group_id": item.get("server_group_id"),
            "os_family": item.get("os_family"),
            "status": item.get("status"),
            "is_compatible": item.get("is_compatible"),
            "needs_reboot": item.get("needs_reboot"),
            "last_refresh_time": item.get("last_refresh_time"),
        }
        devices.append(entry)

    return {
        "data": {
            "total_devices": total,
            "devices": devices,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }
