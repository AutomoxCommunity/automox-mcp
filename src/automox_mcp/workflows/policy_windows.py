"""Policy windows (maintenance/exclusion windows) workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient


def _summarize_window(window: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a policy window record."""
    return {
        "window_uuid": window.get("window_uuid"),
        "window_type": window.get("window_type"),
        "window_name": window.get("window_name"),
        "window_description": window.get("window_description"),
        "org_uuid": window.get("org_uuid"),
        "rrule": window.get("rrule"),
        "duration_minutes": window.get("duration_minutes"),
        "dtstart": window.get("dtstart"),
        "use_local_tz": window.get("use_local_tz"),
        "status": window.get("status"),
        "recurrence": window.get("recurrence"),
        "group_uuids": window.get("group_uuids"),
        "created_at": window.get("created_at"),
        "updated_at": window.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_policy_window(
    client: AutomoxClient,
    *,
    org_uuid: str,
    window_type: str,
    window_name: str,
    window_description: str,
    rrule: str,
    duration_minutes: int,
    use_local_tz: bool,
    recurrence: str,
    group_uuids: list[str],
    dtstart: str,
    status: str,
) -> dict[str, Any]:
    """Create a new maintenance/exclusion window."""
    body: dict[str, Any] = {
        "window_type": window_type,
        "window_name": window_name,
        "window_description": window_description,
        "rrule": rrule,
        "duration_minutes": duration_minutes,
        "use_local_tz": use_local_tz,
        "recurrence": recurrence,
        "group_uuids": group_uuids,
        "dtstart": dtstart,
        "status": status,
    }

    result = await client.post(f"/policy-windows/org/{org_uuid}", json_data=body)

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = _summarize_window(result)
        data["created"] = True
    else:
        data = {"created": True, "raw": result}

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def get_policy_window(
    client: AutomoxClient,
    *,
    org_uuid: str,
    window_uuid: str,
) -> dict[str, Any]:
    """Retrieve details for a specific maintenance window."""
    result = await client.get(
        f"/policy-windows/org/{org_uuid}/window/{window_uuid}",
    )

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = _summarize_window(result)
    else:
        data = {"window_uuid": window_uuid, "raw": result}

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def update_policy_window(
    client: AutomoxClient,
    *,
    org_uuid: str,
    window_uuid: str,
    dtstart: str,
    window_type: str | None = None,
    window_name: str | None = None,
    window_description: str | None = None,
    rrule: str | None = None,
    duration_minutes: int | None = None,
    use_local_tz: bool | None = None,
    recurrence: str | None = None,
    group_uuids: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update an existing maintenance window (partial update, dtstart required)."""
    body: dict[str, Any] = {"dtstart": dtstart}
    if window_type is not None:
        body["window_type"] = window_type
    if window_name is not None:
        body["window_name"] = window_name
    if window_description is not None:
        body["window_description"] = window_description
    if rrule is not None:
        body["rrule"] = rrule
    if duration_minutes is not None:
        body["duration_minutes"] = duration_minutes
    if use_local_tz is not None:
        body["use_local_tz"] = use_local_tz
    if recurrence is not None:
        body["recurrence"] = recurrence
    if group_uuids is not None:
        body["group_uuids"] = group_uuids
    if status is not None:
        body["status"] = status

    result = await client.put(
        f"/policy-windows/org/{org_uuid}/window/{window_uuid}",
        json_data=body,
    )

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = _summarize_window(result)
        data["updated"] = True
    else:
        data = {"window_uuid": window_uuid, "updated": True, "raw": result}

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def delete_policy_window(
    client: AutomoxClient,
    *,
    org_uuid: str,
    window_uuid: str,
) -> dict[str, Any]:
    """Delete a maintenance window permanently."""
    await client.delete(f"/policy-windows/org/{org_uuid}/window/{window_uuid}")

    return {
        "data": {
            "window_uuid": window_uuid,
            "deleted": True,
        },
        "metadata": {"deprecated_endpoint": False},
    }


# ---------------------------------------------------------------------------
# Query & Status
# ---------------------------------------------------------------------------


async def search_policy_windows(
    client: AutomoxClient,
    *,
    org_uuid: str,
    group_uuids: list[str] | None = None,
    statuses: list[str] | None = None,
    recurrences: list[str] | None = None,
    page: int | None = None,
    size: int | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """Search and list maintenance windows with optional filtering and pagination."""
    body: dict[str, Any] = {}
    if group_uuids is not None:
        body["group_uuids"] = group_uuids
    if statuses is not None:
        body["statuses"] = statuses
    if recurrences is not None:
        body["recurrences"] = recurrences
    if page is not None:
        body["page"] = page
    if size is not None:
        body["size"] = size
    if sort is not None:
        body["sort"] = sort
    if direction is not None:
        body["direction"] = direction

    result = await client.post(
        f"/policy-windows/org/{org_uuid}/search",
        json_data=body,
    )

    windows: list[dict[str, Any]] = []
    total_elements: int | None = None
    total_pages: int | None = None
    if isinstance(result, Mapping):
        raw_items = result.get("content") or result.get("data") or result.get("windows") or []
        if isinstance(raw_items, list):
            windows = [_summarize_window(w) for w in raw_items if isinstance(w, Mapping)]
        total_elements = result.get("total_elements") or result.get("totalElements")
        total_pages = result.get("total_pages") or result.get("totalPages")
    elif isinstance(result, list):
        windows = [_summarize_window(w) for w in result if isinstance(w, Mapping)]

    data: dict[str, Any] = {
        "total_windows": len(windows),
        "windows": windows,
    }
    if total_elements is not None:
        data["total_elements"] = total_elements
    if total_pages is not None:
        data["total_pages"] = total_pages

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def check_group_exclusion_status(
    client: AutomoxClient,
    *,
    org_uuid: str,
    group_uuids: list[str],
) -> dict[str, Any]:
    """Check whether groups are currently within an active exclusion window."""
    body: dict[str, Any] = {"group_uuids": group_uuids}

    result = await client.post(
        f"/policy-windows/org/{org_uuid}/groups/exclusion-status",
        json_data=body,
    )

    statuses: list[dict[str, Any]] = []
    if isinstance(result, list):
        statuses = [
            {
                "group_uuid": s.get("group_uuid"),
                "in_exclusion_window": s.get("in_exclusion_window"),
            }
            for s in result
            if isinstance(s, Mapping)
        ]
    elif isinstance(result, Mapping):
        raw = result.get("data") or result.get("statuses") or []
        if isinstance(raw, list):
            statuses = [
                {
                    "group_uuid": s.get("group_uuid"),
                    "in_exclusion_window": s.get("in_exclusion_window"),
                }
                for s in raw
                if isinstance(s, Mapping)
            ]

    return {
        "data": {"group_statuses": statuses},
        "metadata": {"deprecated_endpoint": False},
    }


async def check_window_active(
    client: AutomoxClient,
    *,
    org_uuid: str,
    window_uuid: str,
) -> dict[str, Any]:
    """Check whether a specific maintenance window is currently active."""
    result = await client.get(
        f"/policy-windows/org/{org_uuid}/window/{window_uuid}/is-active",
    )

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = {
            "window_uuid": result.get("window_uuid", window_uuid),
            "in_exclusion_window": result.get("in_exclusion_window"),
        }
    else:
        data = {"window_uuid": window_uuid, "raw": result}

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


async def get_group_scheduled_windows(
    client: AutomoxClient,
    *,
    org_uuid: str,
    group_uuid: str,
    date: str | None = None,
) -> dict[str, Any]:
    """Get upcoming scheduled maintenance periods for a server group."""
    params: dict[str, Any] = {}
    if date is not None:
        params["date"] = date

    result = await client.get(
        f"/policy-windows/org/{org_uuid}/group/{group_uuid}/scheduled-windows",
        params=params,
    )

    periods: list[dict[str, Any]] = []
    if isinstance(result, list):
        periods = [
            {
                "start": p.get("start"),
                "end": p.get("end"),
                "window_type": p.get("window_type"),
            }
            for p in result
            if isinstance(p, Mapping)
        ]
    elif isinstance(result, Mapping):
        raw = result.get("data") or result.get("periods") or []
        if isinstance(raw, list):
            periods = [
                {
                    "start": p.get("start"),
                    "end": p.get("end"),
                    "window_type": p.get("window_type"),
                }
                for p in raw
                if isinstance(p, Mapping)
            ]

    return {
        "data": {
            "group_uuid": group_uuid,
            "periods": periods,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_device_scheduled_windows(
    client: AutomoxClient,
    *,
    org_uuid: str,
    device_uuid: str,
    date: str | None = None,
) -> dict[str, Any]:
    """Get upcoming scheduled maintenance periods for a specific device."""
    params: dict[str, Any] = {}
    if date is not None:
        params["date"] = date

    result = await client.get(
        f"/policy-windows/org/{org_uuid}/device/{device_uuid}/scheduled-windows",
        params=params,
    )

    periods: list[dict[str, Any]] = []
    if isinstance(result, list):
        periods = [
            {
                "start": p.get("start"),
                "end": p.get("end"),
                "window_type": p.get("window_type"),
            }
            for p in result
            if isinstance(p, Mapping)
        ]
    elif isinstance(result, Mapping):
        raw = result.get("data") or result.get("periods") or []
        if isinstance(raw, list):
            periods = [
                {
                    "start": p.get("start"),
                    "end": p.get("end"),
                    "window_type": p.get("window_type"),
                }
                for p in raw
                if isinstance(p, Mapping)
            ]

    return {
        "data": {
            "device_uuid": device_uuid,
            "periods": periods,
        },
        "metadata": {"deprecated_endpoint": False},
    }
