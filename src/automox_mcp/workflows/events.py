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
    if count_only:
        # Count mode is camelCase `countOnly` with the INTEGER 1. The upstream
        # validator is a Laravel boolean rule: it accepts 1/0 (and "1"/"0") but
        # *rejects* the strings "true"/"false" (400 "must be true or false").
        # snake_case `count_only` is an unknown param the API silently ignores,
        # which is why the original `count_only=true` returned a full page.
        # The response shape changes to {"size": <total>, "results": []} —
        # honors all the same filters (event_name, date range, etc.).
        params["countOnly"] = 1
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

    events = await client.get("/events", params=params)

    # A normal /events query returns a bare JSON list of event objects.
    # Count mode (countOnly=1) returns {"size": <total>, "results": []} — the
    # total under `size`, no event bodies.
    api_total: int | None = None
    if isinstance(events, Mapping):
        raw = events.get("results")
        if isinstance(raw, list):
            events_list: list[Any] = raw
        else:
            events_list = []
        size = events.get("size")
        if isinstance(size, int):
            api_total = size
    elif isinstance(events, list):
        events_list = events
    else:
        events_list = [events] if events else []

    total = api_total if api_total is not None else len(events_list)
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
