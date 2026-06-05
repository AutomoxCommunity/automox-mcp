"""Audit Service v2 (OCSF) workflows for Automox MCP.

Exposes the /audit-service/v1 API with OCSF-formatted events and
cursor-based pagination. Complements the existing audit_trail_user_activity
tool with direct event type filtering and simpler output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ..client import AutomoxClient
from ..utils import resolve_org_uuid
from ..utils.response import build_pagination_metadata

# OCSF enum labels from the Console API spec (components/schemas
# `severity_id` / `status_id` x-enumDescriptions), live-confirmed 2026-06-05.
# NOTE: these integers do NOT mean the same thing as the /servers
# policy_status enum (where 1 = up_to_date and 2 = pending) — never share a
# mapping between the two.
_SEVERITY_ID_LABELS = {
    0: "unknown",
    1: "informational",
    2: "low",
    3: "medium",
    4: "high",
    5: "critical",
    6: "fatal",
    99: "other",
}
_STATUS_ID_LABELS = {
    0: "unknown",
    1: "success",
    2: "failure",
    99: "other",
}


def _ocsf_time_to_iso(value: Any) -> Any:
    """Convert the OCSF event ``time`` to an ISO 8601 UTC string.

    The Automox audit service emits ``time`` as epoch SECONDS (float) —
    verified live 2026-06-05 — even though the OCSF standard specifies epoch
    milliseconds. Values too large to be seconds (past year ~5138) are
    treated as milliseconds defensively. Non-numeric values pass through.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    seconds = value / 1000 if value > 1e11 else value
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return value


def _summarize_ocsf_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key OCSF fields from an audit event."""
    entry: dict[str, Any] = {}
    for key in (
        "uid",
        "time",
        "category_uid",
        "category_name",
        "type_uid",
        "type_name",
        "class_uid",
        "class_name",
        "activity",
        "activity_id",
        "message",
        "severity",
        "severity_id",
        "status",
        "status_id",
    ):
        val = event.get(key)
        if val is not None:
            entry[key] = val

    if "time" in entry:
        entry["time"] = _ocsf_time_to_iso(entry["time"])

    # Make the integer enums self-describing when the upstream omits the
    # string sibling — otherwise the model has to guess the OCSF scale.
    severity_id = entry.get("severity_id")
    if (
        "severity" not in entry
        and isinstance(severity_id, int)
        and not isinstance(severity_id, bool)
    ):
        label = _SEVERITY_ID_LABELS.get(severity_id)
        if label:
            entry["severity"] = label
    status_id = entry.get("status_id")
    if "status" not in entry and isinstance(status_id, int) and not isinstance(status_id, bool):
        label = _STATUS_ID_LABELS.get(status_id)
        if label:
            entry["status"] = label

    # Extract actor info
    actor = event.get("actor")
    if isinstance(actor, Mapping):
        actor_info: dict[str, Any] = {}
        user = actor.get("user")
        if isinstance(user, Mapping):
            for field in ("email_addr", "name", "uid", "type"):
                val = user.get(field)
                if val is not None:
                    actor_info[field] = val
        if actor_info:
            entry["actor"] = actor_info

    # Extract resource/object info
    for resource_key in ("resource", "object", "device"):
        resource = event.get(resource_key)
        if isinstance(resource, Mapping):
            entry[resource_key] = {
                k: v
                for k, v in resource.items()
                if v is not None
                and k
                in (
                    "uid",
                    "name",
                    "type",
                    "type_id",
                    "id",
                )
            }

    return entry


async def audit_events_ocsf(
    client: AutomoxClient,
    *,
    org_id: int,
    date: str,
    org_uuid: str | UUID | None = None,
    category_name: str | None = None,
    type_name: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Query OCSF-formatted audit events with filtering and cursor pagination.

    Supports filtering by event category (authentication, account_change,
    entity_management, user_access, web_resource_activity) and event type name.
    """
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    params: dict[str, Any] = {"date": date}
    if cursor:
        params["cursor"] = cursor
    if limit is not None:
        params["limit"] = limit

    headers = {"x-ax-organization-uuid": resolved_uuid}
    response = await client.get(
        f"/audit-service/v1/orgs/{resolved_uuid}/events",
        params=params,
        headers=headers,
    )

    # Parse response
    api_metadata: Mapping[str, Any] | None = None
    events: list[Mapping[str, Any]]
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        events = [item for item in response if isinstance(item, Mapping)]
    elif isinstance(response, Mapping):
        api_metadata = (
            response.get("metadata") if isinstance(response.get("metadata"), Mapping) else None
        )
        data_block = response.get("data")
        if isinstance(data_block, Sequence) and not isinstance(data_block, (str, bytes)):
            events = [item for item in data_block if isinstance(item, Mapping)]
        else:
            events = []
    else:
        events = []

    # Apply client-side filtering
    filtered: list[Mapping[str, Any]] = events
    if category_name:
        cat_lower = category_name.strip().lower()
        filtered = [e for e in filtered if str(e.get("category_name") or "").lower() == cat_lower]
    if type_name:
        type_lower = type_name.strip().lower()
        filtered = [e for e in filtered if str(e.get("type_name") or "").lower() == type_lower]

    summaries = [_summarize_ocsf_event(e) for e in filtered]

    # Extract next cursor
    next_cursor = None
    if api_metadata:
        next_cursor = api_metadata.get("next") or api_metadata.get("cursor")
    if not next_cursor and events:
        last = events[-1]
        metadata_block = last.get("metadata")
        if isinstance(metadata_block, Mapping):
            next_cursor = metadata_block.get("uid")

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "date": date,
            "total_events": len(summaries),
            "events": summaries,
        },
        "metadata": {
            "deprecated_endpoint": False,
            # Legacy alias retained for backwards-compat (#52). The canonical
            # location is metadata.pagination.next_cursor.
            "next_cursor": next_cursor,
            "pagination": build_pagination_metadata(
                page_size=limit,
                has_more=bool(next_cursor),
                next_cursor=next_cursor,
            ),
            "events_before_filter": len(events),
            "applied_filters": {
                "category_name": category_name,
                "type_name": type_name,
            },
        },
    }
