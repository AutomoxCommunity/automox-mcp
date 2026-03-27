"""Advanced device search workflows (Server Groups API v2) for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from ..client import AutomoxClient
from ..utils import resolve_org_uuid


def _extract_list(response: Any) -> list[Mapping[str, Any]]:
    """Normalize API response into a list of mappings."""
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        return [item for item in response if isinstance(item, Mapping)]
    if isinstance(response, Mapping):
        data = response.get("data")
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
            return [item for item in data if isinstance(item, Mapping)]
        return [response]
    return []


async def _resolve_org(client: AutomoxClient, org_id: int | None = None) -> str:
    """Resolve org UUID for Server Groups API v2 endpoints."""
    return await resolve_org_uuid(
        client,
        org_id=org_id or client.org_id,
    )


async def list_saved_searches(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
) -> dict[str, Any]:
    """List saved device searches."""
    org_uuid = await _resolve_org(client, org_id)
    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/saved-search/list",
    )

    searches = _extract_list(response)
    summaries: list[dict[str, Any]] = []
    for item in searches:
        entry: dict[str, Any] = {}
        for key in ("id", "name", "description", "query", "created_at", "updated_at"):
            val = item.get(key)
            if val is not None:
                entry[key] = val
        summaries.append(entry)

    return {
        "data": {
            "total_searches": len(summaries),
            "saved_searches": summaries,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def advanced_device_search(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    query: dict[str, Any] | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Execute an advanced device search using the Server Groups API v2."""
    org_uuid = await _resolve_org(client, org_id)

    body: dict[str, Any] = {}
    if query:
        body["query"] = query
    if page is not None:
        body["page"] = page
    if limit is not None:
        body["limit"] = limit

    response = await client.post(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/search",
        json_data=body,
    )

    devices = _extract_list(response)

    total = None
    if isinstance(response, Mapping):
        total = response.get("total") or response.get("totalCount")

    return {
        "data": {
            "total_devices": total if total is not None else len(devices),
            "devices": devices,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def device_search_typeahead(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    field: str,
    prefix: str,
) -> dict[str, Any]:
    """Get typeahead suggestions for device search fields."""
    org_uuid = await _resolve_org(client, org_id)

    body: dict[str, Any] = {"field": field, "prefix": prefix}

    response = await client.post(
        f"/server-groups-api/v1/organizations/{org_uuid}/search/typeahead",
        json_data=body,
    )

    suggestions: list[Any]
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        suggestions = list(response)
    elif isinstance(response, Mapping):
        suggestions = list(response.get("suggestions") or response.get("data") or [])
    else:
        suggestions = []

    return {
        "data": {
            "field": field,
            "prefix": prefix,
            "total_suggestions": len(suggestions),
            "suggestions": suggestions,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_device_metadata_fields(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
) -> dict[str, Any]:
    """Get available fields for device queries.

    Uses the metadata endpoint which does not require org in the path.
    """
    response = await client.get(
        "/server-groups-api/device/metadata/device-fields",
    )

    fields = _extract_list(response)

    return {
        "data": {
            "total_fields": len(fields),
            "fields": fields,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_device_assignments(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
) -> dict[str, Any]:
    """Get device-to-policy/group assignments."""
    org_uuid = await _resolve_org(client, org_id)

    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/assignments",
    )

    assignments = _extract_list(response)

    return {
        "data": {
            "total_assignments": len(assignments),
            "assignments": assignments,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_device_by_uuid(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    device_uuid: str,
) -> dict[str, Any]:
    """Get device details by UUID via the Server Groups API v2."""
    org_uuid = await _resolve_org(client, org_id)

    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/server/{device_uuid}",
    )

    if isinstance(response, Mapping):
        detail = dict(response)
    else:
        detail = {}

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False},
    }
