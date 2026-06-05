"""Policy windows (maintenance/exclusion windows) workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from ..client import AutomoxClient
from ..utils.response import build_pagination_metadata

# Field-level legends surfaced in metadata.field_notes so the model can read
# the verified vocabularies/units alongside the raw projection. All claims here
# are live-verified (controlled-object probe 2026-06-05) EXCEPT the
# use_local_tz=true timezone semantics, which the probe could not exercise
# (the probed object used use_local_tz=false) and are therefore attributed to
# the spec/input semantics, not verified live.
_WINDOW_FIELD_NOTES: dict[str, str] = {
    "status": "Lowercase: active | inactive (live-verified 2026-06-05).",
    "recurrence": (
        "Read responses normalize to UPPERCASE (ONCE | RECURRING) even though "
        "create/update accept lowercase (once/recurring) — live-verified 2026-06-05."
    ),
    "dtstart": (
        "ISO 8601, echoed exactly as submitted. When use_local_tz=false the "
        "trailing Z is literal UTC (live-verified 2026-06-05). When "
        "use_local_tz=true the same wall-clock is applied in each device's "
        "local timezone, so the Z suffix does NOT mean UTC (per spec/input "
        "semantics, not live-verified)."
    ),
    "use_local_tz": (
        "false = interpret dtstart as UTC (live-verified); true = interpret "
        "dtstart's wall-clock in each device's local timezone (per spec/input "
        "semantics, not live-verified)."
    ),
}

_SCHEDULED_WINDOWS_FIELD_NOTES: dict[str, str] = {
    "start": (
        "Derived occurrence start; the window entity has no stored start/end "
        "(it is dtstart + duration_minutes + rrule). Timezone basis follows "
        "the parent window's use_local_tz, which this endpoint does not return."
    ),
    "end": (
        "Derived occurrence end (start + duration_minutes). See start note for timezone basis."
    ),
}


def _first_present(m: Mapping[str, Any], *keys: str) -> Any:
    """Return the first key whose value is not None.

    Used for pagination totals so a genuine zero (``total_elements == 0``,
    falsy) is preserved instead of being coalesced away by an ``or`` chain.
    """
    for k in keys:
        v = m.get(k)
        if v is not None:
            return v
    return None


def _scheduled_windows_path(base_path: str, date: str | None) -> str:
    """Append a date query param without percent-encoding the colons.

    The Automox `/policy-windows/.../scheduled-windows` endpoint validates
    the `date` query parameter as `YYYY-MM-DDTHH:mm:ss` and rejects the
    request when colons are encoded as `%3A` (which httpx's default
    params-encoder produces). We construct the query string manually and
    keep `:` in the safe set so the literal value survives transport.
    """
    if date is None:
        return base_path
    encoded = quote(date.rstrip("Z"), safe=":")
    return f"{base_path}?date={encoded}"


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
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": dict(_WINDOW_FIELD_NOTES),
        },
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
        # Use explicit None-coalescing (not `or`) so a genuine zero count
        # survives. A Spring Page with total_elements=0 is falsy; an `or`
        # chain would fall through to the absent camelCase key (None) and
        # drop the totals from pagination metadata. The camelCase fallback is
        # defensive only — the live envelope is snake_case (probe 2026-06-05).
        total_elements = _first_present(result, "total_elements", "totalElements")
        total_pages = _first_present(result, "total_pages", "totalPages")
    elif isinstance(result, list):
        windows = [_summarize_window(w) for w in result if isinstance(w, Mapping)]

    data: dict[str, Any] = {
        "total_windows": len(windows),
        "windows": windows,
    }
    # Legacy aliases retained for backwards-compat (#52). Canonical location
    # for these fields is metadata.pagination.
    if total_elements is not None:
        data["total_elements"] = total_elements
    if total_pages is not None:
        data["total_pages"] = total_pages

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": dict(_WINDOW_FIELD_NOTES),
            "pagination": build_pagination_metadata(
                page=page,
                page_size=size,
                total_elements=total_elements,
                total_pages=total_pages,
            ),
        },
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
    base = f"/policy-windows/org/{org_uuid}/group/{group_uuid}/scheduled-windows"
    path = _scheduled_windows_path(base, date)

    result = await client.get(path)

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
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": dict(_SCHEDULED_WINDOWS_FIELD_NOTES),
        },
    }


async def get_device_scheduled_windows(
    client: AutomoxClient,
    *,
    org_uuid: str,
    device_uuid: str,
    date: str | None = None,
) -> dict[str, Any]:
    """Get upcoming scheduled maintenance periods for a specific device."""
    base = f"/policy-windows/org/{org_uuid}/device/{device_uuid}/scheduled-windows"
    path = _scheduled_windows_path(base, date)

    result = await client.get(path)

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
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": dict(_SCHEDULED_WINDOWS_FIELD_NOTES),
        },
    }
