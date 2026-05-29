"""Advanced device search workflows (Server Groups API v2) for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..client import AutomoxClient
from ..utils import resolve_org_uuid
from ..utils.response import build_pagination_metadata, require_org_id
from ..utils.response import extract_list as _extract_list


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
    """Get device-to-policy/group assignments.

    The upstream `/server-groups-api/v1/organizations/{uuid}/assignments`
    endpoint returns a Spring `Page<T>` envelope with `content`,
    `pageable`, `total_elements`, `number_of_elements`, etc. Earlier
    revisions of this wrapper passed the envelope through `_extract_list`
    which has no special-case for Spring pages — it fell through to
    wrapping the entire envelope as a single record, leaking
    `pageable`/`total_elements`/`number_of_elements` into responses.
    Now we explicitly extract `content` and re-emit the Spring
    pagination fields under `metadata.pagination` in the project's
    canonical shape.
    """
    org_uuid = await _resolve_org(client, org_id)

    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/assignments",
    )

    assignments: list[Mapping[str, Any]]
    pagination: dict[str, Any] | None = None
    if isinstance(response, Mapping) and "content" in response:
        content = response.get("content")
        assignments = (
            [item for item in content if isinstance(item, Mapping)]
            if isinstance(content, Sequence) and not isinstance(content, (str, bytes))
            else []
        )
        raw_pageable = response.get("pageable")
        pageable: Mapping[str, Any] = raw_pageable if isinstance(raw_pageable, Mapping) else {}
        sort_block = response.get("sort") if isinstance(response.get("sort"), Mapping) else None

        # Use _first_present to preserve falsy values (e.g. page=0).
        def _first_present(*candidates: Any) -> Any:
            for value in candidates:
                if value is not None:
                    return value
            return None

        total_elements = _first_present(
            response.get("total_elements"), response.get("totalElements")
        )
        total_pages = _first_present(response.get("total_pages"), response.get("totalPages"))
        is_last = response.get("last")
        pagination = build_pagination_metadata(
            page=response.get("number"),
            page_size=response.get("size"),
            total_elements=total_elements,
            total_pages=total_pages,
            has_more=(not is_last) if is_last is not None else None,
            extra={
                "first": response.get("first"),
                "last": is_last,
                "page_number": _first_present(
                    pageable.get("page_number"), pageable.get("pageNumber")
                ),
                "offset": pageable.get("offset"),
                "sort": sort_block,
            },
        )
        pagination = pagination or None
    else:
        assignments = _extract_list(response)

    metadata: dict[str, Any] = {"deprecated_endpoint": False}
    if pagination:
        metadata["pagination"] = pagination

    return {
        "data": {
            "total_assignments": len(assignments),
            "assignments": assignments,
        },
        "metadata": metadata,
    }


async def get_device_by_uuid(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    device_uuid: str,
) -> dict[str, Any]:
    """Get device details by UUID via the canonical `/servers/{id}` endpoint.

    The upstream OpenAPI spec types `id` as `integer/int64`, but the live tenant
    accepts UUIDs and returns the same device-detail payload (issue #92, #86).
    The previously-used `/server-groups-api/v1/organizations/{X}/server/{uuid}`
    path does not exist; it returned an empty Spring Page wrapper from a
    catch-all route, masking the bug behind a `200` response.
    """
    resolved_org_id = require_org_id(client, org_id)

    params = {"o": resolved_org_id, "includeDetails": 1}
    response = await client.get(f"/servers/{device_uuid}", params=params)

    if isinstance(response, Mapping):
        detail = dict(response)
    else:
        detail = {}

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False},
    }


# ---------------------------------------------------------------------------
# Saved-search CRUD + bulk-assignment (Device Explorer, 2025-12-11)
# ---------------------------------------------------------------------------


async def get_saved_search(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    saved_search_id: str,
) -> dict[str, Any]:
    """Retrieve a single saved device search by ID."""
    org_uuid = await _resolve_org(client, org_id)
    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/saved-search/{saved_search_id}",
    )

    detail: dict[str, Any] = dict(response) if isinstance(response, Mapping) else {}

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False},
    }


async def create_saved_search(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    name: str,
    query: dict[str, Any],
    description: str | None = None,
) -> dict[str, Any]:
    """Create a new saved device search."""
    org_uuid = await _resolve_org(client, org_id)

    body: dict[str, Any] = {"name": name, "query": query}
    if description is not None:
        body["description"] = description

    response = await client.post(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/saved-search",
        json_data=body,
    )

    data: dict[str, Any] = dict(response) if isinstance(response, Mapping) else {"raw": response}
    data["created"] = True

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def update_saved_search(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    saved_search_id: str,
    name: str | None = None,
    query: dict[str, Any] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Update an existing saved device search."""
    org_uuid = await _resolve_org(client, org_id)

    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if query is not None:
        body["query"] = query
    if description is not None:
        body["description"] = description

    response = await client.put(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/saved-search/{saved_search_id}",
        json_data=body,
    )

    data: dict[str, Any] = dict(response) if isinstance(response, Mapping) else {}
    data["saved_search_id"] = saved_search_id
    data["updated"] = True

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def delete_saved_search(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    saved_search_id: str,
) -> dict[str, Any]:
    """Delete a saved device search permanently."""
    org_uuid = await _resolve_org(client, org_id)
    await client.delete(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/saved-search/{saved_search_id}",
    )

    return {
        "data": {"saved_search_id": saved_search_id, "deleted": True},
        "metadata": {"deprecated_endpoint": False},
    }


async def get_saved_search_results(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    saved_search_id: str,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Execute a saved search and retrieve its current device results."""
    org_uuid = await _resolve_org(client, org_id)

    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/saved-search/{saved_search_id}/results",
        params=params or None,
    )

    devices = _extract_list(response)
    total: Any = None
    if isinstance(response, Mapping):
        total = (
            response.get("total") or response.get("totalCount") or response.get("total_elements")
        )

    return {
        "data": {
            "saved_search_id": saved_search_id,
            "total_devices": total if total is not None else len(devices),
            "devices": devices,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_cached_search_results(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    search_id: str,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Retrieve cached results for a previously-run device search.

    Distinct from `get_saved_search_results`: this returns the cached
    server-side result set keyed by search execution `search_id` rather
    than re-executing a saved-search definition.
    """
    org_uuid = await _resolve_org(client, org_id)

    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/search/{search_id}/saved",
        params=params or None,
    )

    devices = _extract_list(response)
    total: Any = None
    if isinstance(response, Mapping):
        total = (
            response.get("total") or response.get("totalCount") or response.get("total_elements")
        )

    return {
        "data": {
            "search_id": search_id,
            "total_devices": total if total is not None else len(devices),
            "devices": devices,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def assign_policies_to_saved_search(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    saved_search_uuid: str,
    policy_ids: list[int],
) -> dict[str, Any]:
    """Bulk-assign one or more policies to a saved search's result set."""
    org_uuid = await _resolve_org(client, org_id)

    body: dict[str, Any] = {"policy_ids": policy_ids}
    response = await client.post(
        f"/server-groups-api/v1/organizations/{org_uuid}/saved-searches/{saved_search_uuid}",
        json_data=body,
    )

    data: dict[str, Any]
    if isinstance(response, Mapping):
        data = dict(response)
    else:
        data = {"raw": response}
    data.setdefault("saved_search_uuid", saved_search_uuid)
    data.setdefault("policy_ids", list(policy_ids))
    data["assigned"] = True

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def get_search_scopes(client: AutomoxClient) -> dict[str, Any]:
    """List available device-search scope options (org-independent metadata)."""
    response = await client.get("/server-groups-api/device/metadata/scopes")
    scopes = _extract_list(response)

    return {
        "data": {
            "total_scopes": len(scopes),
            "scopes": scopes,
        },
        "metadata": {"deprecated_endpoint": False},
    }


# ---------------------------------------------------------------------------
# Search & metadata enrichment (issue #91 category D)
# ---------------------------------------------------------------------------


async def get_searchable_fields(client: AutomoxClient) -> dict[str, Any]:
    """List searchable device fields grouped by scope, with type metadata.

    Org-independent metadata. Richer than `get_device_metadata_fields`, which
    returns the flat `device-fields` string array: this endpoint groups fields
    by scope and carries per-field type info, so an LLM can construct typed
    queries.
    """
    response = await client.get("/server-groups-api/device/metadata/fields")

    data: dict[str, Any] = dict(response) if isinstance(response, Mapping) else {"fields": response}

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def list_searches_for_device(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    device_uuid: str,
    search_type: str | None = None,
) -> dict[str, Any]:
    """List saved searches whose result set currently contains a device."""
    org_uuid = await _resolve_org(client, org_id)

    params: dict[str, Any] = {}
    if search_type:
        params["type"] = search_type

    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/saved-search/server/{device_uuid}",
        params=params or None,
    )

    # The endpoint returns a bare array of saved-search identifiers (strings),
    # so extract_list (which keeps only mappings) would drop them — handle the
    # sequence directly.
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        searches: list[Any] = list(response)
    elif isinstance(response, Mapping):
        searches = _extract_list(response)
    else:
        searches = []

    return {
        "data": {
            "device_uuid": device_uuid,
            "total_searches": len(searches),
            "saved_searches": searches,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def run_saved_search(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    search_id: str,
    page: int | None = None,
    size: int | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Execute a saved search by UUID with paging and optional field projection.

    Lighter-weight than `get_saved_search_results`: returns the Spring
    `PageObject` envelope, supports a `fields` projection, and pages with
    `page`/`size`. The Spring pagination fields are re-emitted under
    `metadata.pagination` in the project's canonical shape.
    """
    org_uuid = await _resolve_org(client, org_id)

    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if size is not None:
        params["size"] = size
    if fields:
        params["fields"] = fields

    response = await client.get(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/search/{search_id}",
        params=params or None,
    )

    devices: list[Any]
    pagination: dict[str, Any] | None = None
    if isinstance(response, Mapping) and "content" in response:
        content = response.get("content")
        devices = list(content) if isinstance(content, Sequence) else []
        is_last = response.get("last")
        pagination = (
            build_pagination_metadata(
                page=response.get("number"),
                page_size=response.get("size"),
                total_elements=response.get("totalElements"),
                total_pages=response.get("totalPages"),
                has_more=(not is_last) if is_last is not None else None,
                extra={"first": response.get("first"), "last": is_last},
            )
            or None
        )
    else:
        devices = _extract_list(response)

    metadata: dict[str, Any] = {"deprecated_endpoint": False}
    if pagination:
        metadata["pagination"] = pagination

    return {
        "data": {
            "search_id": search_id,
            "total_devices": len(devices),
            "devices": devices,
        },
        "metadata": metadata,
    }


async def refresh_saved_search_cache(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    search_id: str,
) -> dict[str, Any]:
    """Force a re-cache of a saved search's results when they may be stale."""
    org_uuid = await _resolve_org(client, org_id)

    response = await client.post(
        f"/server-groups-api/v1/organizations/{org_uuid}/device/search/{search_id}/refresh",
    )

    data: dict[str, Any] = dict(response) if isinstance(response, Mapping) else {}
    data["search_id"] = search_id
    data["refreshed"] = True

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }
