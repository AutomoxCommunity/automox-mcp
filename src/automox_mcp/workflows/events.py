"""Event workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient
from ..utils.response import build_pagination_metadata


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

    data: dict[str, Any] = {}
    metadata: dict[str, Any] = {"deprecated_endpoint": False}

    if api_total is not None:
        # Count mode (countOnly=1): upstream supplies a real org-wide total
        # under `size`, with no event bodies. Only here can we claim a grand
        # total; count_only suppresses the events array.
        data["total_events"] = api_total
        data["events"] = []
        return {"data": data, "metadata": metadata}

    # Normal mode: the live /events endpoint returns a bare list with no
    # upstream total, so we can only report how many came back on THIS page —
    # never a grand total (presenting len(page) as `total_events`
    # under-reported by a page on any limited query).
    events_returned = len(summary)
    data["events_returned"] = events_returned
    data["events"] = summary

    # /events is offset-paginated with no total, so "more pages exist" is
    # inferred from a full page (returned == limit) rather than a counter.
    has_more = limit is not None and events_returned >= limit
    current_page = page if page is not None else 0
    next_page = current_page + 1 if has_more else None
    metadata["pagination"] = build_pagination_metadata(
        page=current_page,
        page_size=limit,
        has_more=has_more,
        extra={
            "returned_count": events_returned,
            "next_page": next_page,
        },
    )
    if has_more:
        metadata["suggested_next_call"] = {
            "tool": "list_events",
            "args": {
                k: v
                for k, v in {
                    "page": next_page,
                    "limit": limit,
                    "policy_id": policy_id,
                    "server_id": server_id,
                    "user_id": user_id,
                    "event_name": event_name,
                    "start_date": start_date,
                    "end_date": end_date,
                }.items()
                if v is not None
            },
        }

    return {"data": data, "metadata": metadata}
