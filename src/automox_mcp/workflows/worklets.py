"""Worklet catalog workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..client import AutomoxClient


def _extract_worklet_list(response: Any) -> list[Mapping[str, Any]]:
    """Extract a list of worklets from the API response.

    The /wis/search endpoint may return a plain list or a dict wrapping a list.
    """
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        return [item for item in response if isinstance(item, Mapping)]
    if isinstance(response, Mapping):
        for key in ("data", "results", "items", "worklets"):
            val = response.get(key)
            if isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
                return [item for item in val if isinstance(item, Mapping)]
        # Single worklet wrapped in a dict
        return [response]
    return []


async def search_worklet_catalog(
    client: AutomoxClient,
    *,
    org_id: int,
    query: str | None = None,
) -> dict[str, Any]:
    """Search the Automox community worklet catalog."""
    params: dict[str, Any] = {"o": org_id}
    if query:
        params["q"] = query

    response = await client.get("/wis/search", params=params)
    results = _extract_worklet_list(response)

    total = len(results)
    worklets: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": item.get("uuid") or item.get("id"),
            "name": item.get("name"),
            "description": item.get("description"),
            "category": item.get("category"),
        }
        for optional in (
            "os_family",
            "os_families",
            "created_at",
            "updated_at",
            "update_time",
            "create_time",
            "author",
        ):
            val = item.get(optional)
            if val is not None:
                entry[optional] = val
        worklets.append(entry)

    return {
        "data": {
            "total_worklets": total,
            "worklets": worklets,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def get_worklet_detail(
    client: AutomoxClient,
    *,
    org_id: int,
    item_id: str,
) -> dict[str, Any]:
    """Get detailed information for a specific worklet."""
    result = await client.get(f"/wis/search/{item_id}", params={"o": org_id})

    if not isinstance(result, Mapping):
        result = {}

    detail: dict[str, Any] = {
        "id": result.get("uuid") or result.get("id"),
        "name": result.get("name"),
        "description": result.get("description"),
        "category": result.get("category"),
    }
    for optional in (
        "os_family",
        "os_families",
        "created_at",
        "updated_at",
        "author",
        "evaluation_code",
        "remediation_code",
        "notes",
    ):
        val = result.get(optional)
        if val is not None:
            detail[optional] = val

    return {
        "data": detail,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }
