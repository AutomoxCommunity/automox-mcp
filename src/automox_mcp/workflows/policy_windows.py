"""Policy windows (maintenance/exclusion windows) workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from ..client import AutomoxClient
from ..utils.response import build_pagination_metadata

# Field-level legends surfaced in metadata.field_notes so the model can read
# the verified vocabularies/units alongside the raw projection. All claims here
# are live-verified (controlled-object probes 2026-06-05/2026-06-06). The
# use_local_tz=true timezone semantics remain spec-attributed by construction:
# the upstream rejects use_local_tz=true outright on this tenant (2026-06-06),
# and even where allowed the entity exposes no device-resolved time field, so
# the true-case behavior is device-side and unprovable from the API entity.
_WINDOW_FIELD_NOTES: dict[str, str] = {
    "status": "Lowercase: active | inactive (live-verified 2026-06-05).",
    "recurrence": (
        "Read responses normalize to UPPERCASE (ONCE | RECURRING) even though "
        "create/update accept lowercase (once/recurring) — live-verified 2026-06-05."
    ),
    "dtstart": (
        "ISO 8601, echoed verbatim with no normalization (live-verified "
        "2026-06-06: sent and read back identically, trailing Z preserved). "
        "When use_local_tz=false this is literal UTC — the only persistable "
        "case here, since the upstream rejects use_local_tz=true with HTTP 400 "
        '(invalidFields.useLocalTz="use_local_tz cannot be set to true", '
        "unconditional of recurrence on this tenant — may be tenant/plan-"
        "conditional, not asserted universal). The use_local_tz=true wall-clock-"
        "in-each-device's-local-timezone semantics are spec-only AND device-side: "
        "the entity carries no timezone-resolution field, so even where the flag "
        "is allowed the API cannot confirm them."
    ),
    "use_local_tz": (
        "false = interpret dtstart as UTC (live-verified; the only persistable "
        "value here). true is REJECTED at create with HTTP 400 "
        '(invalidFields.useLocalTz="use_local_tz cannot be set to true", '
        "verified 2026-06-06, unconditional of recurrence on this tenant — may "
        "be tenant/plan-conditional). Its spec meaning (interpret dtstart's "
        "wall-clock in each device's local timezone) is device-side and carries "
        "no entity field, so it is structurally unprovable from the API."
    ),
    "duration_minutes": (
        "May be recomputed upstream for recurrence=once windows: live "
        "2026-06-06 sent 30, create AND get echoed 389494 (≈ the dtstart→UNTIL "
        "span). The wrapper passes the value verbatim, so read back the echoed "
        "value rather than trusting the submitted input."
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
        # The spec declares the recurrences filter as an UPPERCASE enum
        # (ONCE | RECURRING) — read responses also normalize to uppercase. The
        # tool's Literal accepts lowercase tokens for ergonomics, so coerce to
        # uppercase before sending; a lowercase token could otherwise silently
        # match zero windows (audit finding N11; spec-attributed, not
        # live-verified — tenant had 0 windows so neither casing could be
        # exercised). Case-insensitive accept, uppercase on the wire.
        body["recurrences"] = [r.upper() if isinstance(r, str) else r for r in recurrences]
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

    windows_returned = len(windows)

    data: dict[str, Any] = {
        # `windows_returned` is the count on THIS page; the grand total across
        # all pages is `total_elements` (the upstream Spring Page total). The
        # earlier `total_windows` named the per-page length as if it were a
        # total — retained below as a deprecated alias for backwards-compat.
        "windows_returned": windows_returned,
        "total_windows": windows_returned,
        "windows": windows,
    }
    # Legacy aliases retained for backwards-compat (#52). Canonical location
    # for these fields is metadata.pagination.
    if total_elements is not None:
        data["total_elements"] = total_elements
    if total_pages is not None:
        data["total_pages"] = total_pages

    # On the default call (page/size unset) the upstream returns the first page;
    # default to the page/size actually in effect so build_pagination_metadata
    # can derive has_more from total_elements instead of silently omitting it.
    effective_page = page if page is not None else 0
    effective_size = size if size is not None else windows_returned

    pagination = build_pagination_metadata(
        page=effective_page,
        page_size=effective_size,
        total_elements=total_elements,
        total_pages=total_pages,
    )

    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "field_notes": dict(_WINDOW_FIELD_NOTES),
        "pagination": pagination,
    }
    # When more pages remain, hand the model the exact next invocation rather
    # than making it infer the next page from raw counters.
    if pagination.get("has_more"):
        metadata["suggested_next_call"] = {
            "tool": "search_policy_windows",
            "args": {
                k: v
                for k, v in {
                    "group_uuids": group_uuids,
                    "statuses": statuses,
                    "recurrences": recurrences,
                    "page": effective_page + 1,
                    "size": effective_size,
                    "sort": sort,
                    "direction": direction,
                }.items()
                if v is not None
            },
        }

    return {
        "data": data,
        "metadata": metadata,
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
