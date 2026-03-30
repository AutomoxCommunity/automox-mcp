"""Data extract workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient


async def list_data_extracts(
    client: AutomoxClient,
    *,
    org_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List available data extracts for the organization."""
    params: dict[str, Any] = {"o": org_id}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    results = await client.get("/data-extracts", params=params)

    if not isinstance(results, list):
        results = [results] if isinstance(results, Mapping) else []

    extracts: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": item.get("id"),
            "name": item.get("name"),
            "status": item.get("status"),
        }
        for optional in ("type", "created_at", "updated_at", "file_size", "download_url"):
            val = item.get(optional)
            if val is not None:
                entry[optional] = val
        extracts.append(entry)

    return {
        "data": {
            "total_extracts": len(extracts),
            "extracts": extracts,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def get_data_extract(
    client: AutomoxClient,
    *,
    org_id: int,
    extract_id: str,
) -> dict[str, Any]:
    """Get details and download info for a specific data extract."""
    result = await client.get(f"/data-extracts/{extract_id}", params={"o": org_id})

    if not isinstance(result, Mapping):
        result = {}

    detail: dict[str, Any] = {
        "id": result.get("id"),
        "name": result.get("name"),
        "status": result.get("status"),
    }
    for optional in (
        "type",
        "created_at",
        "updated_at",
        "file_size",
        "download_url",
        "expires_at",
        "row_count",
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


async def create_data_extract(
    client: AutomoxClient,
    *,
    org_id: int,
    extract_data: dict[str, Any],
) -> dict[str, Any]:
    """Request a new data extract."""
    result = await client.post(
        "/data-extracts",
        params={"o": org_id},
        json_data=extract_data,
    )

    if not isinstance(result, Mapping):
        result = {}

    return {
        "data": {
            "id": result.get("id"),
            "name": result.get("name"),
            "status": result.get("status", "pending"),
            "message": "Data extract request submitted.",
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }
