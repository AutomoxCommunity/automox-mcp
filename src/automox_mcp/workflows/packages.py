"""Package workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient


async def list_device_packages(
    client: AutomoxClient,
    *,
    org_id: int,
    device_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List software packages installed on a specific device."""
    params: dict[str, Any] = {"o": org_id}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    raw_response = await client.get(f"/servers/{device_id}/packages", params=params)

    packages: list[Any]
    total: int
    if isinstance(raw_response, Mapping):
        packages = (
            raw_response.get("data", []) if isinstance(raw_response.get("data"), list) else []
        )
        total = raw_response.get("total", len(packages))
    elif isinstance(raw_response, list):
        packages = raw_response
        total = len(packages)
    else:
        packages = []
        total = 0
    summary: list[dict[str, Any]] = []
    for pkg in packages:
        if not isinstance(pkg, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": pkg.get("id"),
            "name": pkg.get("display_name") or pkg.get("name"),
            "version": pkg.get("version"),
            "installed": pkg.get("installed"),
            "repo": pkg.get("repo"),
        }
        severity = pkg.get("severity")
        if severity is not None:
            entry["severity"] = severity
        patch_status = pkg.get("status") or pkg.get("patch_status")
        if patch_status is not None:
            entry["patch_status"] = patch_status
        is_managed = pkg.get("is_managed")
        if is_managed is not None:
            entry["is_managed"] = is_managed
        summary.append(entry)

    return {
        "data": {
            "device_id": device_id,
            "total_packages": total,
            "packages": summary,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def search_org_packages(
    client: AutomoxClient,
    *,
    org_id: int,
    include_unmanaged: bool | None = None,
    awaiting: bool | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Search packages across the organization."""
    params: dict[str, Any] = {}
    if include_unmanaged is not None:
        params["includeUnmanaged"] = 1 if include_unmanaged else 0
    if awaiting is not None:
        params["awaiting"] = 1 if awaiting else 0
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    raw_response = await client.get(f"/orgs/{org_id}/packages", params=params)

    packages: list[Any]
    total: int
    if isinstance(raw_response, Mapping):
        packages = (
            raw_response.get("data", []) if isinstance(raw_response.get("data"), list) else []
        )
        total = raw_response.get("total", len(packages))
    elif isinstance(raw_response, list):
        packages = raw_response
        total = len(packages)
    else:
        packages = []
        total = 0
    summary: list[dict[str, Any]] = []
    for pkg in packages:
        if not isinstance(pkg, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": pkg.get("id"),
            "name": pkg.get("display_name") or pkg.get("name"),
            "version": pkg.get("version"),
            "severity": pkg.get("severity"),
        }
        device_count = pkg.get("device_count")
        if device_count is not None:
            entry["device_count"] = device_count
        is_managed = pkg.get("is_managed")
        if is_managed is not None:
            entry["is_managed"] = is_managed
        awaiting_flag = pkg.get("awaiting")
        if awaiting_flag is not None:
            entry["awaiting"] = awaiting_flag
        summary.append(entry)

    return {
        "data": {
            "total_packages": total,
            "packages": summary,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }
