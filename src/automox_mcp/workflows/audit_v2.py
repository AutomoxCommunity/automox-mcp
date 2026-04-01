"""Audit Service v2 (OCSF) workflows for Automox MCP.

Exposes the /audit-service/v1 API with OCSF-formatted events and
cursor-based pagination. Complements the existing audit_trail_user_activity
tool with direct event type filtering and simpler output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from ..client import AutomoxClient
from ..utils import resolve_org_uuid


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
            "next_cursor": next_cursor,
            "events_before_filter": len(events),
            "applied_filters": {
                "category_name": category_name,
                "type_name": type_name,
            },
        },
    }
