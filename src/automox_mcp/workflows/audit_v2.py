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

# The upstream OCSF audit events carry NO `category_name` field (verified live
# 2026-06-05: 0 occurrences across all event variants; only an integer
# `category_uid` is present, and per the spec examples category_uid maps 1:N
# across categories — live-confirmed, e.g. category_uid=3 covers BOTH
# Authentication and Entity Management). The one string the upstream actually
# populates is `type_name`, whose live values are prefixed by a human category
# label using a colon+space boundary ("Authentication: Logon",
# "Entity Management: Create", "Web Resources Activity: Delete"). We therefore
# narrow a `category_name` filter against the `type_name` PREFIX rather than the
# non-existent `category_name` field.
#
# `authentication` / `entity_management` / `web_resource_activity` prefixes are
# LIVE-VERIFIED (2026-06-05). `account_change` / `user_access` are SPEC-EXAMPLE
# DERIVED ONLY (no events of those categories existed in the live tenant to
# confirm the exact prefix) — labeled unverified in the field_notes legend.
_CATEGORY_TYPE_PREFIXES = {
    "authentication": "authentication: ",  # live-verified
    "entity_management": "entity management: ",  # live-verified
    "web_resource_activity": "web resources activity: ",  # live-verified
    "account_change": "account change: ",  # spec-example only, unverified live
    "user_access": "user access: ",  # spec-example only, unverified live
}
_CATEGORY_PREFIXES_VERIFIED = frozenset(
    {"authentication", "entity_management", "web_resource_activity"}
)


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

    category_name filtering is applied client-side against the event ``type_name``
    prefix because the upstream events carry no ``category_name`` field; an
    unmappable token leaves the results unfiltered and sets
    ``applied_filters.category_name_matched=false`` rather than zeroing the set.
    type_name filtering is an exact (case-insensitive) match.
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

    # Apply client-side filtering.
    #
    # category_name: the upstream has NO category_name field (see
    # _CATEGORY_TYPE_PREFIXES). We narrow against the type_name prefix instead.
    # An UNKNOWN/underivable token must NOT silently zero the result (that is the
    # exact "empty looks like no activity" failure mode this fix removes) — when
    # we cannot map the token to a prefix, we leave the events unfiltered and
    # surface category_name_matched=false so the model can tell the difference.
    filtered: list[Mapping[str, Any]] = events
    field_notes: list[str] = []
    category_name_matched: bool | None = None
    if category_name:
        token = category_name.strip().lower()
        prefix = _CATEGORY_TYPE_PREFIXES.get(token)
        if prefix:
            filtered = [
                e for e in filtered if str(e.get("type_name") or "").lower().startswith(prefix)
            ]
            category_name_matched = True
            source = (
                "live-verified 2026-06-05"
                if token in _CATEGORY_PREFIXES_VERIFIED
                else "spec examples only, unverified live"
            )
            field_notes.append(
                f"category_name filter is applied client-side against the event "
                f"type_name prefix '{prefix}' (the upstream events carry no "
                f"category_name field). Prefix source: {source}."
            )
        else:
            # Unknown token: do not zero the result. Leave unfiltered and flag.
            category_name_matched = False
            field_notes.append(
                f"category_name '{category_name}' could not be mapped to a known "
                f"type_name prefix; the category filter was NOT applied and all "
                f"events for the date are returned. Known tokens: "
                f"{', '.join(sorted(_CATEGORY_TYPE_PREFIXES))}."
            )
    if type_name:
        type_lower = type_name.strip().lower()
        filtered = [e for e in filtered if str(e.get("type_name") or "").lower() == type_lower]

    summaries = [_summarize_ocsf_event(e) for e in filtered]

    # report-only finding 3: the OCSF taxonomy uids are raw integers with no
    # decode table in the upstream spec (no x-enumDescriptions on
    # category_uid/type_uid/class_uid/activity_id), and category_uid is not a
    # clean discriminator (live: category_uid=3 spans both Authentication and
    # Entity Management). Point the model at the populated string siblings.
    field_notes.append(
        "category_uid/type_uid/class_uid/activity_id are raw OCSF taxonomy "
        "integers with no decode table in the upstream spec; category_uid maps "
        "1:N across categories (e.g. 3 covers both Authentication and Entity "
        "Management). Prefer the human-readable sibling strings type_name and "
        "activity, which the upstream populates."
    )

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
                "category_name_matched": category_name_matched,
                "type_name": type_name,
            },
            "field_notes": field_notes,
        },
    }
