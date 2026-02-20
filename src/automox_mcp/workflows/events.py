"""Event workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient


async def list_events(
    client: AutomoxClient,
    *,
    org_id: int,
    page: int | None = None,
    limit: int | None = None,
    count_only: bool | None = None,
    policy_id: int | None = None,
    server_id: int | None = None,
    user_id: int | None = None,
    event_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """List organization events with optional filters."""
    params: dict[str, Any] = {"o": org_id}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    if count_only is not None:
        params["count_only"] = str(count_only).lower()
    if policy_id is not None:
        params["policyId"] = policy_id
    if server_id is not None:
        params["serverId"] = server_id
    if user_id is not None:
        params["userId"] = user_id
    if event_name is not None:
        params["eventName"] = event_name
    if start_date is not None:
        params["startDate"] = start_date
    if end_date is not None:
        params["endDate"] = end_date

    events = await client.get("/events", params=params, api="console")

    if not isinstance(events, list):
        events_list: list[Any] = [events] if events else []
    else:
        events_list = events

    total = len(events_list)
    summary: list[dict[str, Any]] = []
    for event in events_list:
        if not isinstance(event, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": event.get("id"),
            "name": event.get("name"),
            "server_id": event.get("server_id"),
            "server_name": event.get("server_name"),
            "policy_id": event.get("policy_id"),
            "policy_name": event.get("policy_name"),
            "policy_type_name": event.get("policy_type_name"),
            "user_id": event.get("user_id"),
            "data": event.get("data"),
            "create_time": event.get("create_time"),
        }
        summary.append(entry)

    return {
        "data": {
            "total_events": total,
            "events": summary,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }
